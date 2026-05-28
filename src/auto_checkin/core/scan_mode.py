# -*- coding: utf-8 -*-
"""
扫描模式模块 - 判断当前扫描模式
"""

from __future__ import annotations

from datetime import datetime
from auto_checkin.config import CLASS_STARTS, CLASS_PERIODS, HIGH_ALERT_BEFORE, HIGH_ALERT_AFTER


def _now_minutes():
    """返回当前时间的总分钟数（hour*60+minute）。"""
    now = datetime.now()
    return now.hour * 60 + now.minute


def get_scan_mode():
    """
    返回当前扫描模式
    - None: 待机（非上课时间）
    - 'fast': 高警戒（课程开始前后）
    - 'slow': 低频巡查（课程进行中）
    """
    tot = _now_minutes()

    for h, m in CLASS_STARTS:
        s = h * 60 + m
        if (s - HIGH_ALERT_BEFORE) <= tot <= (s + HIGH_ALERT_AFTER):
            return "fast"

    for sh, sm, eh, em in CLASS_PERIODS:
        if (sh * 60 + sm) <= tot <= (eh * 60 + em):
            return "slow"

    return None
