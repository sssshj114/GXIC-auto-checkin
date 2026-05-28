# -*- coding: utf-8 -*-
"""
Core 模块 - 自动签到核心功能

使用惰性导入避免循环依赖：导入子模块时不会触发整个包的初始化。
"""

from __future__ import annotations

import importlib

_LAZY_IMPORTS = {
    "checkin_state": ("auto_checkin.core.state", "checkin_state"),
    "reply_state": ("auto_checkin.core.state", "reply_state"),
    "exam_state": ("auto_checkin.core.state", "exam_state"),
    "course_registry": ("auto_checkin.core.state", "course_registry"),
    "retro_checkin_log": ("auto_checkin.core.state", "retro_checkin_log"),
    "session_manager": ("auto_checkin.core.session", "session_manager"),
    "get_scan_mode": ("auto_checkin.core.scan_mode", "get_scan_mode"),
    "run": ("auto_checkin.core.scheduler", "run"),
    "shutdown": ("auto_checkin.core.scheduler", "shutdown"),
    "get_exit_event": ("auto_checkin.core.scheduler", "get_exit_event"),
    "fetch_schedule": ("auto_checkin.core.course", "fetch_schedule"),
    "statistics": ("auto_checkin.core.statistics", "statistics"),
}

__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)
    raise AttributeError(f"module 'core' has no attribute {name!r}")
