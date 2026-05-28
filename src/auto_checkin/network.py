# -*- coding: utf-8 -*-
"""
网络模块 - 负责 HTTP 请求、重试机制、请求限流
"""

from __future__ import annotations

import os
import json
import requests
import time
import threading
import hashlib
from functools import wraps
from auto_checkin.config import DEEPSEEK_API_KEY, SCAN_CONFIG, DATA_DIR
from auto_checkin.logger import log
from auto_checkin.core.health_check import health_monitor
from auto_checkin.core.statistics import statistics


# ================= 请求限流器 =================
class RateLimiter:
    """
    请求限流器 - 控制请求频率，防止触发服务器防护
    使用令牌桶算法实现
    """

    def __init__(self, max_requests_per_second: float = 5.0):
        self._interval = 1.0 / max_requests_per_second
        self._last_request_time = 0.0
        self._lock = threading.Lock()
        self._total_requests = 0
        self._total_wait_time = 0.0

    def acquire(self):
        """获取请求许可，必要时等待（不持有锁等待，避免阻塞其他线程）"""
        wait_time = 0.0
        with self._lock:
            now = time.time()
            wait_time = self._last_request_time + self._interval - now
            if wait_time > 0:
                # 预先占用时间槽，然后释放锁再等待
                self._last_request_time += self._interval
            else:
                self._last_request_time = now
            self._total_requests += 1
        if wait_time > 0:
            time.sleep(wait_time)
            with self._lock:
                self._total_wait_time += wait_time

    def get_stats(self) -> dict:
        """获取限流统计"""
        with self._lock:
            return {
                "total_requests": self._total_requests,
                "total_wait_time": round(self._total_wait_time, 2),
                "rate_limit": round(1.0 / self._interval, 2),
            }

    def reset(self):
        """重置统计"""
        with self._lock:
            self._total_requests = 0
            self._total_wait_time = 0.0


# 全局限流器实例
rate_limiter = RateLimiter(max_requests_per_second=3.0)


class ApiResponseError(Exception):
    """HTTP 或业务层响应不符合预期。"""


def validate_json_response(
    response: requests.Response,
    context: str,
    validator: callable = None,
) -> dict:
    """统一校验外部接口响应，确保 HTTP 与业务层结果都符合预期。"""
    if response.status_code != 200:
        health_monitor.record_failure(f"HTTP_{response.status_code}")
        raise ApiResponseError(f"{context} HTTP {response.status_code}")

    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError) as e:
        # 记录响应内容的前200字符用于调试
        preview = response.text[:200] if hasattr(response, 'text') else 'N/A'
        health_monitor.record_failure("non_json_response")
        raise ApiResponseError(f"{context} 返回了非 JSON 响应 (预览: {preview})") from e

    if validator is not None:
        ok, detail = validator(data)
        if not ok:
            health_monitor.record_failure("validation_failed")
            raise ApiResponseError(f"{context} 业务失败: {detail}")

    # 请求成功
    health_monitor.record_success()
    return data


# ================= 答案缓存 =================
_ANSWER_CACHE = {}
_ANSWER_CACHE_LOCK = threading.Lock()
_MAX_CACHE_SIZE = 2000
_CACHE_FILE = os.path.join(DATA_DIR, "answer_cache.json")


def _cache_key(prompt):
    """生成缓存 key（题目文本的 SHA256）"""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _load_cache():
    """启动时从磁盘加载缓存文件"""
    global _ANSWER_CACHE
    if not os.path.exists(_CACHE_FILE):
        return
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            _ANSWER_CACHE = json.load(f)
        log(f"[答案缓存] 加载了 {len(_ANSWER_CACHE)} 条历史记录")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
        log(f"[答案缓存] 加载失败，使用空缓存: {e}")
        _ANSWER_CACHE = {}


def _save_cache():
    """持久化缓存到磁盘"""
    try:
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_ANSWER_CACHE, f, ensure_ascii=False)
        os.replace(tmp, _CACHE_FILE)
    except OSError as e:
        log(f"[答案缓存] 写入失败: {e}")


_load_cache()


# ================= 重试装饰器 =================
def with_retry(max_attempts=3, delay=1.0, backoff=2.0):
    """
    请求重试装饰器
    - max_attempts: 最大尝试次数
    - delay: 初始等待秒数
    - backoff: 退避倍数
    - 重试耗尽后抛出最后一次异常，避免调用方误用 None
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except (requests.RequestException, ApiResponseError, OSError) as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        wait = delay * (backoff**attempt)
                        log(
                            f"[重试] {func.__name__} 第 {attempt + 1} 次失败，{wait:.1f}秒后重试..."
                        )
                        time.sleep(wait)
            log(f"[重试耗尽] {func.__name__} 最终失败: {last_exception}")
            raise last_exception

        return wrapper

    return decorator


# ================= DeepSeek API =================
@with_retry(max_attempts=3, delay=2.0, backoff=2.0)
def call_deepseek(prompt):
    """调用 DeepSeek API 进行智能答题（带缓存和限流）"""
    rate_limiter.acquire()

    cache_k = _cache_key(prompt)
    with _ANSWER_CACHE_LOCK:
        if cache_k in _ANSWER_CACHE:
            log("[缓存命中] 使用缓存答案")
            statistics.record_deepseek_cache_hit()
            return _ANSWER_CACHE[cache_k]
        if len(_ANSWER_CACHE) >= _MAX_CACHE_SIZE:
            keys_to_remove = list(_ANSWER_CACHE.keys())[: _MAX_CACHE_SIZE // 2]
            for k in keys_to_remove:
                del _ANSWER_CACHE[k]
            _save_cache()

    statistics.record_deepseek_call()

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    data = {
        "model": "deepseek-v4-flash",
        "messages": [
            {
                "role": "system",
                "content": "你是一个答题专家。根据题干和选项，选择正确的选项ID并只输出该ID。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=30)
        resp_data = validate_json_response(
            r,
            "DeepSeek API",
            validator=lambda data: (
                isinstance(data.get("choices"), list)
                and len(data["choices"]) > 0
                and isinstance(data["choices"][0], dict)
                and isinstance(data["choices"][0].get("message"), dict)
                and bool(data["choices"][0]["message"].get("content", "").strip()),
                data.get("error", {}).get("message")
                or data.get("message")
                or "缺少有效响应",
            ),
        )
        result = resp_data["choices"][0]["message"]["content"].strip()
        with _ANSWER_CACHE_LOCK:
            _ANSWER_CACHE[cache_k] = result
        _save_cache()
        return result
    except (
        requests.RequestException,
        ApiResponseError,
        KeyError,
        TypeError,
        ValueError,
    ) as e:
        log(f"[DeepSeek] API 调用失败: {e}")
        statistics.record_deepseek_error()
        raise


def get_rate_limiter_stats() -> dict:
    """获取限流器统计信息"""
    return rate_limiter.get_stats()


def get_cache_stats() -> dict:
    """获取缓存统计信息"""
    with _ANSWER_CACHE_LOCK:
        return {
            "size": len(_ANSWER_CACHE),
            "max_size": _MAX_CACHE_SIZE,
        }
