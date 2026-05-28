# -*- coding: utf-8 -*-
"""
状态管理模块 - 全局状态、锁、持久化
"""

from __future__ import annotations

import os
import json
import threading
from auto_checkin.config import DATA_DIR
from auto_checkin.logger import log


class CheckinState:
    """签到状态管理"""

    MAX_FAILURES = 3

    def __init__(self):
        self._checked = set()
        self._processing = set()
        self._failure_counts: dict = {}
        self._lock = threading.Lock()

    def claim(self, check_id) -> bool:
        """占用签到任务，返回是否成功"""
        with self._lock:
            if (
                check_id
                and check_id not in self._checked
                and check_id not in self._processing
            ):
                self._processing.add(check_id)
                return True
            return False

    def finish(self, check_id):
        """完成签到（成功或永久放弃）"""
        with self._lock:
            self._processing.discard(check_id)
            self._failure_counts.pop(check_id, None)
            if check_id:
                self._checked.add(check_id)
        self._save()

    def release(self, check_id):
        """释放签到任务；累计失败达到上限后自动标记完成，不再重试"""
        with self._lock:
            self._processing.discard(check_id)
            if check_id:
                count = self._failure_counts.get(check_id, 0) + 1
                self._failure_counts[check_id] = count
                if count >= self.MAX_FAILURES:
                    self._checked.add(check_id)
                    self._failure_counts.pop(check_id, None)
                    log(f"   [放弃] 签到 {check_id[:8]}... 连续失败 {count} 次，本轮不再重试")
                    self._save()

    def load(self):
        """从磁盘加载状态"""
        state_path = f"{DATA_DIR}/checkin_state.json"
        try:
            if os.path.exists(state_path):
                with open(state_path, encoding="utf-8") as f:
                    data = json.load(f)
                    self._checked.update(data.get("checked_ids", []))
                log(f"[状态恢复] 加载了 {len(self._checked)} 条历史签到记录")
        except Exception as e:
            log(f"[状态恢复] 读取失败: {e}")

    def _save(self):
        """持久化到磁盘"""
        state_path = f"{DATA_DIR}/checkin_state.json"
        tmp_path = f"{state_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"checked_ids": list(self._checked)}, f, ensure_ascii=False)
            os.replace(tmp_path, state_path)
        except Exception as e:
            log(f"[状态保存] 写入失败: {e}")


class ReplyState:
    """资料回复状态管理"""

    def __init__(self):
        self._replied = set()
        self._processing = set()
        self._lock = threading.Lock()

    def claim(self, element_id) -> bool:
        with self._lock:
            if (
                element_id
                and element_id not in self._replied
                and element_id not in self._processing
            ):
                self._processing.add(element_id)
                return True
            return False

    def finish(self, element_id):
        with self._lock:
            self._processing.discard(element_id)
            if element_id:
                self._replied.add(element_id)

    def release(self, element_id):
        with self._lock:
            self._processing.discard(element_id)


class ExamState:
    """答题状态管理"""

    def __init__(self):
        self._examined = set()
        self._processing = set()
        self._lock = threading.Lock()

    def claim(self, element_id) -> bool:
        with self._lock:
            if (
                element_id
                and element_id not in self._examined
                and element_id not in self._processing
            ):
                self._processing.add(element_id)
                return True
            return False

    def finish(self, element_id):
        with self._lock:
            self._processing.discard(element_id)
            if element_id:
                self._examined.add(element_id)

    def release(self, element_id):
        with self._lock:
            self._processing.discard(element_id)


class RetroCheckinLog:
    """补签记录管理"""

    def __init__(self):
        self._entries = []
        self._lock = threading.Lock()

    def record(self, icid: str, course_name: str, success: bool, detail: str):
        from datetime import datetime
        entry = {
            "icid": icid,
            "course": course_name,
            "success": success,
            "detail": detail,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > 200:
                self._entries = self._entries[-200:]

    def get_all(self, limit: int = 50) -> list:
        with self._lock:
            return list(reversed(self._entries[-limit:]))


class CourseRegistry:
    """课程注册表"""

    def __init__(self):
        self._courses = {}
        self._schedule_html = "正在获取课表数据..."
        self._lock = threading.Lock()

    def get_snapshot(self) -> dict:
        """获取课程快照"""
        with self._lock:
            return {icid: info.copy() for icid, info in self._courses.items()}

    def update(self, courses: dict, schedule_html: str = None):
        """更新课程"""
        with self._lock:
            for icid, course in courses.items():
                old = self._courses.get(icid)
                if old:
                    course["checked"] = old.get("checked", False)
                    course["material_count"] = old.get("material_count", 0)
                    course["exam_count"] = old.get("exam_count", 0)
            self._courses = courses
            if schedule_html:
                self._schedule_html = schedule_html

    def mark_checked(self, icid):
        """标记已签到"""
        with self._lock:
            if icid in self._courses:
                self._courses[icid]["checked"] = True

    def reset_checked(self) -> int:
        """重置所有 checked 标记，允许同一节课多次签到。返回重置数量。"""
        with self._lock:
            count = 0
            for info in self._courses.values():
                if info.get("checked"):
                    info["checked"] = False
                    count += 1
            return count

    def increment_counter(self, icid, field: str):
        """增加计数"""
        with self._lock:
            if icid in self._courses:
                self._courses[icid][field] = self._courses[icid].get(field, 0) + 1

    def get_schedule_html(self) -> str:
        with self._lock:
            return self._schedule_html

    def get_runtime_snapshot(self) -> dict:
        """获取运行时快照"""
        with self._lock:
            return {
                "schedule_text": self._schedule_html,
                "courses": {icid: info.copy() for icid, info in self._courses.items()},
            }


checkin_state = CheckinState()
reply_state = ReplyState()
exam_state = ExamState()
course_registry = CourseRegistry()
retro_checkin_log = RetroCheckinLog()
