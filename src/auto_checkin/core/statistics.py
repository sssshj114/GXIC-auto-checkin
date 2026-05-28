# -*- coding: utf-8 -*-
"""
统计模块 - 记录和统计系统运行数据（支持持久化）
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from auto_checkin.config import DATA_DIR

_STATS_FILE = os.path.join(DATA_DIR, "statistics.json")
_OPS_FILE = os.path.join(DATA_DIR, "operations.json")
_MAX_OPERATIONS = 500


def _write_json(path, data):
    """原子写入 JSON 文件"""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def _read_json(path, default=None):
    """读取 JSON 文件，失败时返回默认值"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return default


class Statistics:
    """运行统计管理器 - 支持持久化到磁盘"""

    def __init__(self):
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()
        self._start_time = time.time()
        self._dirty = False

        self._accumulated_uptime = 0.0

        self._checkin_total = 0
        self._checkin_success = 0
        self._checkin_failed = 0

        self._exam_total = 0
        self._exam_success = 0
        self._exam_failed = 0
        self._exam_questions = 0

        self._material_total = 0
        self._material_success = 0
        self._material_failed = 0

        self._deepseek_calls = 0
        self._deepseek_cache_hits = 0
        self._deepseek_errors = 0

        self._last_error = None
        self._last_error_time = None
        self._error_count = 0

        self._operations: list[dict] = []

    # ================= 持久化 =================
    def load(self):
        """从磁盘恢复统计数据和操作记录"""
        stats = _read_json(_STATS_FILE, {})
        ops = _read_json(_OPS_FILE, [])

        with self._lock:
            if stats:
                self._accumulated_uptime = stats.get("accumulated_uptime", 0.0)
                self._checkin_total = stats.get("checkin_total", 0)
                self._checkin_success = stats.get("checkin_success", 0)
                self._checkin_failed = stats.get("checkin_failed", 0)
                self._exam_total = stats.get("exam_total", 0)
                self._exam_success = stats.get("exam_success", 0)
                self._exam_failed = stats.get("exam_failed", 0)
                self._exam_questions = stats.get("exam_questions", 0)
                self._material_total = stats.get("material_total", 0)
                self._material_success = stats.get("material_success", 0)
                self._material_failed = stats.get("material_failed", 0)
                self._deepseek_calls = stats.get("deepseek_calls", 0)
                self._deepseek_cache_hits = stats.get("deepseek_cache_hits", 0)
                self._deepseek_errors = stats.get("deepseek_errors", 0)
                self._error_count = stats.get("error_count", 0)
                self._last_error = stats.get("last_error")
                self._last_error_time = stats.get("last_error_time")

            if isinstance(ops, list):
                self._operations = ops[-_MAX_OPERATIONS:]

            self._start_time = time.time()
            self._dirty = False

    def save(self):
        """持久化统计数据和操作记录到磁盘"""
        with self._save_lock:
            with self._lock:
                stats = self._to_dict()
                ops = list(self._operations)
                self._dirty = False
            _write_json(_STATS_FILE, stats)
            _write_json(_OPS_FILE, ops)

    def save_if_dirty(self):
        """如果有未保存的变更，执行持久化"""
        with self._lock:
            if not self._dirty:
                return
        self.save()

    def _to_dict(self) -> dict:
        """序列化计数器为字典（需在 _lock 内调用）"""
        current_session = time.time() - self._start_time
        return {
            "accumulated_uptime": self._accumulated_uptime + current_session,
            "checkin_total": self._checkin_total,
            "checkin_success": self._checkin_success,
            "checkin_failed": self._checkin_failed,
            "exam_total": self._exam_total,
            "exam_success": self._exam_success,
            "exam_failed": self._exam_failed,
            "exam_questions": self._exam_questions,
            "material_total": self._material_total,
            "material_success": self._material_success,
            "material_failed": self._material_failed,
            "deepseek_calls": self._deepseek_calls,
            "deepseek_cache_hits": self._deepseek_cache_hits,
            "deepseek_errors": self._deepseek_errors,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "last_error_time": self._last_error_time,
        }

    # ================= 操作记录 =================
    def log_operation(self, op_type: str, course: str, detail: str, success: bool):
        """记录一条结构化操作事件并立即持久化"""
        entry = {
            "type": op_type,
            "course": course,
            "detail": detail,
            "success": success,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with self._lock:
            self._operations.append(entry)
            if len(self._operations) > _MAX_OPERATIONS:
                self._operations = self._operations[-_MAX_OPERATIONS:]
            self._dirty = True
        self.save()

    def get_operations(self, limit: int = 50) -> list[dict]:
        """获取最近的操作记录（最新在前）"""
        with self._lock:
            return list(reversed(self._operations[-limit:]))

    # ================= 签到统计 =================
    def record_checkin_attempt(self):
        with self._lock:
            self._checkin_total += 1
            self._dirty = True

    def record_checkin_success(self):
        with self._lock:
            self._checkin_success += 1
            self._dirty = True

    def record_checkin_failed(self):
        with self._lock:
            self._checkin_failed += 1
            self._dirty = True

    # ================= 答题统计 =================
    def record_exam_attempt(self):
        with self._lock:
            self._exam_total += 1
            self._dirty = True

    def record_exam_success(self, questions_count: int = 0):
        with self._lock:
            self._exam_success += 1
            self._exam_questions += questions_count
            self._dirty = True

    def record_exam_failed(self):
        with self._lock:
            self._exam_failed += 1
            self._dirty = True

    # ================= 资料回复统计 =================
    def record_material_attempt(self):
        with self._lock:
            self._material_total += 1
            self._dirty = True

    def record_material_success(self):
        with self._lock:
            self._material_success += 1
            self._dirty = True

    def record_material_failed(self):
        with self._lock:
            self._material_failed += 1
            self._dirty = True

    # ================= DeepSeek API 统计 =================
    def record_deepseek_call(self):
        with self._lock:
            self._deepseek_calls += 1
            self._dirty = True

    def record_deepseek_cache_hit(self):
        with self._lock:
            self._deepseek_cache_hits += 1
            self._dirty = True

    def record_deepseek_error(self):
        with self._lock:
            self._deepseek_errors += 1
            self._dirty = True

    # ================= 错误统计 =================
    def record_error(self, error_msg: str):
        with self._lock:
            self._last_error = error_msg
            self._last_error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._error_count += 1
            self._dirty = True

    # ================= 获取统计 =================
    def get_summary(self) -> dict[str, object]:
        with self._lock:
            total_uptime = self._accumulated_uptime + (time.time() - self._start_time)

            return {
                "uptime_seconds": int(total_uptime),
                "uptime_human": self._format_uptime(total_uptime),
                "checkin": {
                    "total": self._checkin_total,
                    "success": self._checkin_success,
                    "failed": self._checkin_failed,
                    "success_rate": self._calc_rate(
                        self._checkin_success, self._checkin_total
                    ),
                },
                "exam": {
                    "total": self._exam_total,
                    "success": self._exam_success,
                    "failed": self._exam_failed,
                    "questions": self._exam_questions,
                    "success_rate": self._calc_rate(
                        self._exam_success, self._exam_total
                    ),
                },
                "material": {
                    "total": self._material_total,
                    "success": self._material_success,
                    "failed": self._material_failed,
                    "success_rate": self._calc_rate(
                        self._material_success, self._material_total
                    ),
                },
                "deepseek": {
                    "calls": self._deepseek_calls,
                    "cache_hits": self._deepseek_cache_hits,
                    "errors": self._deepseek_errors,
                    "cache_hit_rate": self._calc_rate(
                        self._deepseek_cache_hits,
                        self._deepseek_calls + self._deepseek_cache_hits,
                    ),
                },
                "errors": {
                    "total": self._error_count,
                    "last_error": self._last_error,
                    "last_error_time": self._last_error_time,
                },
            }

    def _calc_rate(self, success: int, total: int) -> str:
        if total == 0:
            return "N/A"
        return f"{success / total * 100:.1f}%"

    def _format_uptime(self, seconds: float) -> str:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        if minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    def reset(self):
        with self._lock:
            self._start_time = time.time()
            self._accumulated_uptime = 0.0
            self._checkin_total = 0
            self._checkin_success = 0
            self._checkin_failed = 0
            self._exam_total = 0
            self._exam_success = 0
            self._exam_failed = 0
            self._exam_questions = 0
            self._material_total = 0
            self._material_success = 0
            self._material_failed = 0
            self._deepseek_calls = 0
            self._deepseek_cache_hits = 0
            self._deepseek_errors = 0
            self._last_error = None
            self._last_error_time = None
            self._error_count = 0
            self._operations.clear()
            self._dirty = True
        self.save()


statistics = Statistics()
