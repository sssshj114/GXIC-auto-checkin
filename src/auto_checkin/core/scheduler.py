# -*- coding: utf-8 -*-
"""
调度模块 - 主循环调度
"""

from __future__ import annotations

import time
import random
import threading
import signal
from auto_checkin.logger import log
from auto_checkin.config import SCAN_CONFIG, CLASS_PERIODS
from auto_checkin.core.scan_mode import get_scan_mode, _now_minutes
from auto_checkin.core.session import session_manager
from auto_checkin.core.course import fetch_schedule
from auto_checkin.core.state import checkin_state, course_registry
from auto_checkin.core.checkin import scan_checkin, steal_code, submit_checkin_task
from auto_checkin.core.material import scan_and_reply_material
from auto_checkin.core.statistics import statistics

_exit_event = threading.Event()


def _signal_handler(signum, frame):
    log(f"[退出] 收到信号 {signum}，正在优雅关闭...")
    _exit_event.set()


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


def get_exit_event():
    """获取退出事件对象"""
    return _exit_event


def shutdown():
    """优雅关闭"""
    log("[退出] 触发优雅关闭...")
    _exit_event.set()
    statistics.save()
    log("[退出] 进程即将退出。")


SCHEDULE_REFRESH_INTERVAL = 30 * 60  # 每 30 分钟刷新一次课表


def _get_current_period_index():
    """获取当前所处的课时段索引，不在任何时段内返回 -1。"""
    now_min = _now_minutes()
    for idx, (sh, sm, eh, em) in enumerate(CLASS_PERIODS):
        start = sh * 60 + sm
        end = eh * 60 + em
        if start <= now_min <= end:
            return idx
    return -1


def run():
    """主循环"""
    log(">> 正在启动自动签到监控系统...")
    checkin_state.load()
    statistics.load()
    session_manager.try_refresh_cookie("启动 - ")
    fetch_schedule()

    scan_count = 0
    slow_scan_count = 0
    sleeping = False
    last_period_index = -2  # -2 表示尚未初始化，与 -1(非上课) 区分
    last_schedule_fetch = time.time()

    while not _exit_event.is_set():
        # 周期性刷新课表（每 30 分钟）
        if time.time() - last_schedule_fetch > SCHEDULE_REFRESH_INTERVAL:
            log("[课表] 定期刷新课表数据...")
            fetch_schedule()
            last_schedule_fetch = time.time()

        mode = get_scan_mode()

        if mode is None:
            if not sleeping:
                log("💤 非上课时间，系统待机中...(将在最近课程开始前5分钟自动唤醒)")
                sleeping = True
            for _ in range(6):
                if _exit_event.is_set():
                    break
                time.sleep(10)
            session_manager.try_refresh_cookie("待机模式 - ")
            continue

        sleeping = False

        # 检测课时段变化，进入新时段时重置 checked 标记
        current_period = _get_current_period_index()
        if current_period != last_period_index:
            if last_period_index != -2:
                reset_count = course_registry.reset_checked()
                if reset_count > 0:
                    log(f"[时段切换] 进入新课时段，重置 {reset_count} 门课程的签到标记")
            last_period_index = current_period

        if mode == "fast":
            scan_count += 1
            log(f"[🔥高警戒 #{scan_count}] 课程开始前后，快速巡查签到状态...")
            _run_scan(is_fast=True)
            sleep_sec = random.randint(
                SCAN_CONFIG["fast_scan_interval_min"],
                SCAN_CONFIG["fast_scan_interval_max"],
            )
        else:
            slow_scan_count += 1
            if slow_scan_count % 10 == 1:
                log(
                    f"[🔵低频巡查 #{slow_scan_count}] 课程进行中，每3~5分钟扫一次资料/测验..."
                )
            _run_scan(is_fast=False)
            sleep_sec = random.randint(
                SCAN_CONFIG["slow_scan_interval_min"],
                SCAN_CONFIG["slow_scan_interval_max"],
            )

        for _ in range(sleep_sec // 10):
            if _exit_event.is_set():
                break
            time.sleep(10)
        session_manager.try_refresh_cookie()
        statistics.save_if_dirty()

    statistics.save()
    log("[退出] 后台任务已停止。")


def _run_scan(is_fast: bool):
    """执行扫描"""
    courses = course_registry.get_snapshot()

    for icid, info in courses.items():
        if _exit_event.is_set():
            break

        scan_and_reply_material(icid, info)

        if not info["checked"]:
            check_id = scan_checkin(icid)
            if check_id and checkin_state.claim(check_id):
                cname = info["name"]
                log(f"🔔 [发现签到] 课程 {cname} 正在点名！")
                code = steal_code(check_id)
                if code:
                    log(
                        f"   [+] 获取签到密文成功：【{code}】，随机延迟 ({SCAN_CONFIG['checkin_delay_min']}-{SCAN_CONFIG['checkin_delay_max']}秒)..."
                    )
                    submit_checkin_task(code, check_id, icid, cname, is_fast)
                else:
                    log("   [-] 提取签到码数据失败！")
                    checkin_state.release(check_id)
