# -*- coding: utf-8 -*-
"""
日志模块 - 负责日志记录和轮转
"""

from __future__ import annotations

import os
import time
import hashlib
from collections import deque
from datetime import datetime
from auto_checkin.config import DATA_DIR, MAX_LOG_SIZE_MB, MAX_LOG_LINES, ERROR_SUPPRESSION_ENABLED, ERROR_SUPPRESSION_WINDOW

LOGS = deque(maxlen=MAX_LOG_LINES)  # 自动淘汰旧条目，O(1) 操作

# 错误抑制机制 - 避免相同错误刷屏
_error_cache = {}  # {error_hash: (last_log_time, count)}
_error_cache_lock = None

def _get_error_hash(msg: str) -> str:
    """生成错误消息的哈希值（忽略时间戳和动态参数）"""
    # 移除时间戳、ID等动态内容
    import re
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}', '', msg)
    normalized = re.sub(r'\d{2}:\d{2}:\d{2}', '', normalized)
    normalized = re.sub(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', 'UUID', normalized)
    normalized = re.sub(r'#\d+', '#N', normalized)
    return hashlib.md5(normalized.encode()).hexdigest()

def _should_suppress_error(msg: str) -> tuple[bool, int]:
    """检查是否应该抑制此错误消息"""
    global _error_cache, _error_cache_lock
    
    if not ERROR_SUPPRESSION_ENABLED:
        return False, 0
    
    if _error_cache_lock is None:
        import threading
        _error_cache_lock = threading.Lock()
    
    error_hash = _get_error_hash(msg)
    now = time.time()
    
    with _error_cache_lock:
        if error_hash in _error_cache:
            last_time, count = _error_cache[error_hash]
            if now - last_time < ERROR_SUPPRESSION_WINDOW:
                _error_cache[error_hash] = (now, count + 1)
                return True, count + 1
        
        _error_cache[error_hash] = (now, 1)
        
        # 清理过期条目
        expired = [k for k, (t, _) in _error_cache.items() if now - t > ERROR_SUPPRESSION_WINDOW * 2]
        for k in expired:
            del _error_cache[k]
    
    return False, 1


def _rotate_log_if_needed() -> None:
    """检查日志文件大小，超过阈值则轮转"""
    log_path = os.path.join(DATA_DIR, "自动签到_运行纪要.log")
    if not os.path.exists(log_path):
        return
    try:
        size = os.path.getsize(log_path)
        if size > MAX_LOG_SIZE_MB:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(DATA_DIR, f"自动签到_运行纪要_{timestamp}.log")
            os.rename(log_path, backup_path)
            print(f"[日志] 文件超过 {MAX_LOG_SIZE_MB // (1024 * 1024)}MB，已轮转到 {os.path.basename(backup_path)}")
    except Exception as e:
        print(f"[日志轮转失败] {e}")


def log(msg: str, error_info: object = None, suppress_duplicates: bool = True) -> None:
    """通用日志函数"""
    global LOGS
    
    # 检查是否应该抑制重复错误
    if suppress_duplicates and ("异常" in msg or "失败" in msg or "错误" in msg):
        should_suppress, count = _should_suppress_error(msg)
        if should_suppress:
            if count % 10 == 0:  # 每10次记录一次
                msg = f"{msg} (已抑制 {count} 次相同错误)"
            else:
                return  # 抑制此日志
    
    now_full = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_time = now_full[-8:]

    line_console = f"[{now_time}] {msg}"
    print(line_console)

    log_path = os.path.join(DATA_DIR, "自动签到_运行纪要.log")
    try:
        _rotate_log_if_needed()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{now_full}] {msg}\n")
            if error_info:
                f.write(f"    [错误追踪] => {str(error_info)}\n")
    except Exception as log_err:
        print(f"[日志写入失败] {log_err}")

    LOGS.append(line_console)  # deque 自动淘汰最旧条目
