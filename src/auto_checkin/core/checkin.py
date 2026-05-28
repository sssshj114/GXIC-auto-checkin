# -*- coding: utf-8 -*-
"""
签到模块 - 扫描和执行签到
"""

from __future__ import annotations

import time
import random
import requests
from concurrent.futures import ThreadPoolExecutor
from auto_checkin.logger import log
from auto_checkin.network import validate_json_response, ApiResponseError, with_retry
from auto_checkin.config import SCAN_CONFIG, EXECUTOR_MAX_WORKERS, BASE_URL
from auto_checkin.core.session import session_manager, auto_login
from auto_checkin.core.state import checkin_state, course_registry, retro_checkin_log
from auto_checkin.core.statistics import statistics

_executor = ThreadPoolExecutor(max_workers=EXECUTOR_MAX_WORKERS)


def scan_checkin(icid: str) -> str:
    """扫描签到状态，返回 CheckId"""
    # 检查是否需要刷新 Cookie
    session_manager.try_refresh_cookie("扫描签到")

    url = f"{BASE_URL}/Checkin/GetIccList"
    headers = session_manager.get_headers_copy()
    headers["Content-Type"] = "application/json;charset=UTF-8"

    try:
        res = requests.post(url, headers=headers, json={"IC_ID": icid}, timeout=3)
        data = validate_json_response(
            res,
            f"scan_checkin(icid={icid})",
            validator=lambda d: (
                d.get("code") == 1,
                f"code={d.get('code')}, msg={d.get('msg') or d.get('message') or '无'}",
            ),
        )
        if data.get("code") == 1 and data.get("data"):
            cur_checkin = data["data"].get("CurCheckin")
            if cur_checkin and cur_checkin.get("Status") == 1:
                return cur_checkin.get("CheckId")
    except (requests.RequestException, ApiResponseError, TypeError, ValueError) as e:
        error_msg = str(e)

        # 关键修复：检测到非JSON响应（Cookie过期），立即刷新
        if "非 JSON 响应" in error_msg or "JSON" in error_msg:
            log(f"   [警告] scan_checkin检测到Cookie可能过期，立即尝试刷新...")
            if auto_login(session_manager):
                log(f"   [成功] Cookie已刷新，将在下次扫描使用新Cookie")
            else:
                log(f"   [失败] Cookie刷新失败")
        elif "非 JSON 响应" not in error_msg:
            # 只在非 JSON 响应错误时记录详细信息，避免日志刷屏
            log(f"   [!] scan_checkin 请求异常（icid={icid}）: {e}")
    return None


def steal_code(check_id: str) -> str:
    """获取签到码"""
    url = f"{BASE_URL}/Checkin/RefreshCheckInCode"
    headers = session_manager.get_headers_copy()
    headers["Content-Type"] = "application/json;charset=UTF-8"

    try:
        res = requests.post(
            url,
            headers=headers,
            json={"CheckId": check_id, "Refresh": False},
            timeout=5,
        )
        data = validate_json_response(
            res,
            f"steal_code(check_id={check_id})",
            validator=lambda d: (
                d.get("code") == 1 and d.get("data") is not None,
                f"code={d.get('code')}, msg={d.get('msg') or d.get('message') or '无'}, data={d.get('data')}",
            ),
        )
        code_info = data.get("data")
        if isinstance(code_info, dict):
            code_str = str(code_info.get("Code", "")).strip()
        else:
            code_str = str(code_info).strip()
        return code_str if code_str else None
    except (requests.RequestException, ApiResponseError, TypeError, ValueError) as e:
        log(f"   [!] steal_code 请求异常（check_id={check_id}）: {e}")
    return None


@with_retry(max_attempts=3, delay=1.0, backoff=2.0)
def do_checkin(icid: str, code: str) -> bool:
    """执行签到"""
    url = f"{BASE_URL}/Checkin/CheckIn"
    headers = session_manager.get_headers_copy()
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    data = {"IC_ID": icid, "CheckInType": "1", "Code": code}

    try:
        res = requests.post(url, headers=headers, data=data, timeout=5)
        try:
            json_data = res.json()
            if json_data.get("code") == 1 or json_data.get("status") == 1:
                return True
            # JSON 明确表示失败，直接返回
            msg = str(json_data.get("msg") or json_data.get("message") or "")
            if msg:
                log(f"   [签到响应] {msg}")
                return False
        except (ValueError, TypeError):
            pass
        # 文本匹配：排除已知失败关键词，避免误判
        text = res.text
        failure_keywords = ["失败", "错误", "过期", "无效", "已达上限", "已签", "不存在"]
        if any(kw in text for kw in failure_keywords):
            return False
        if "签到成功" in text:
            return True
    except requests.RequestException as e:
        log(f"   [!] do_checkin 请求异常（icid={icid}）: {e}")
        raise
    return False


def _process_checkin(code: str, check_id: str, icid: str, cname: str, is_fast: bool = True):
    """处理签到任务（延迟后执行）"""
    delay = random.randint(
        SCAN_CONFIG["checkin_delay_min"],
        SCAN_CONFIG["checkin_delay_max"],
    )
    time.sleep(delay)

    statistics.record_checkin_attempt()

    try:
        success = do_checkin(icid, code)

        if success:
            log(f"   [签到成功] {cname} 延迟 {delay} 秒后签到成功")
            course_registry.mark_checked(icid)
            checkin_state.finish(check_id)
            statistics.record_checkin_success()
            statistics.log_operation("checkin", cname, f"签到成功，延迟 {delay} 秒", True)
        else:
            log(f"   [签到失败] {cname} 签到失败")
            checkin_state.release(check_id)
            statistics.record_checkin_failed()
            statistics.log_operation("checkin", cname, "签到失败", False)
    except Exception as e:
        log(f"   [签到异常] {cname}: {e}")
        checkin_state.release(check_id)
        statistics.record_checkin_failed()
        statistics.record_error(f"签到异常: {e}")
        statistics.log_operation("checkin", cname, f"签到异常: {e}", False)


def submit_checkin_task(
    code: str, check_id: str, icid: str, cname: str, is_fast: bool = True
):
    """提交签到任务到线程池"""
    _executor.submit(_process_checkin, code, check_id, icid, cname, is_fast)


def retro_checkin(icid: str, cname: str) -> dict:
    """手动补签：扫描 → 获取签到码 → 提交。返回 {"success": bool, "detail": str}。"""
    session_manager.try_refresh_cookie(f"补签({cname})")
    log(f"[补签] 用户手动触发 {cname} 的补签...")

    check_id = scan_checkin(icid)
    if not check_id:
        msg = "当前没有检测到活跃签到"
        log(f"   [补签] {cname}: {msg}")
        retro_checkin_log.record(icid, cname, False, msg)
        return {"success": False, "detail": msg}

    code = steal_code(check_id)
    if not code:
        msg = "获取签到码失败"
        log(f"   [补签] {cname}: {msg}")
        checkin_state.release(check_id)
        retro_checkin_log.record(icid, cname, False, msg)
        return {"success": False, "detail": msg}

    log(f"   [补签] {cname}: 获取到签到码 {code}，正在提交...")
    try:
        log(f"   [补签] {cname}: 调用 do_checkin...")
        success = do_checkin(icid, code)
        log(f"   [补签] {cname}: do_checkin 返回 {success}")
        if success:
            course_registry.mark_checked(icid)
            checkin_state.finish(check_id)
            statistics.record_checkin_success()
            statistics.log_operation("checkin", cname, "补签成功", True)
            retro_checkin_log.record(icid, cname, True, "补签成功")
            return {"success": True, "detail": "补签成功"}
        else:
            msg = "签到提交被拒绝（可能已过期或已签）"
            checkin_state.release(check_id)
            retro_checkin_log.record(icid, cname, False, msg)
            return {"success": False, "detail": msg}
    except Exception as e:
        msg = f"签到异常: {e}"
        checkin_state.release(check_id)
        retro_checkin_log.record(icid, cname, False, msg)
        return {"success": False, "detail": msg}
