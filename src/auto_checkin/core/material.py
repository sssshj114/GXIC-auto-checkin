# -*- coding: utf-8 -*-
"""
资料模块 - 扫描资料并自动回复
"""

from __future__ import annotations

import time
import random
import requests
from concurrent.futures import ThreadPoolExecutor
from auto_checkin.logger import log
from auto_checkin.network import validate_json_response, ApiResponseError
from auto_checkin.config import SCAN_CONFIG, EXECUTOR_MAX_WORKERS, BASE_URL
from auto_checkin.core.session import session_manager, auto_login
from auto_checkin.core.state import reply_state, course_registry, exam_state
from auto_checkin.core.statistics import statistics
from auto_checkin.core.exam import process_exam

_executor = ThreadPoolExecutor(max_workers=EXECUTOR_MAX_WORKERS)


def scan_and_reply_material(icid: str, course_info: dict):
    """扫描资料并自动回复"""
    lid = course_info.get("lid")
    sid = course_info.get("sid")
    cname = course_info.get("name")

    if not (lid and sid):
        return

    # 检查是否需要刷新 Cookie
    session_manager.try_refresh_cookie(f"扫描资料({cname})")

    url = f"{BASE_URL}/Weixin/partialItemClassJson?v=808"
    headers = session_manager.get_headers_copy()
    headers["Content-Type"] = "application/json"

    consecutive_errors = 0
    for item_type in [1, 2, 3]:
        payload = {
            "applayType": item_type,
            "ic_id": icid,
            "batchid": None,
            "schduleid": sid,
            "lessionid": lid,
        }

        try:
            res = requests.post(url, headers=headers, json=payload, timeout=5)
            data = validate_json_response(
                res,
                f"scan_material({icid}, type={item_type})",
                validator=lambda d: (
                    isinstance(d.get("items", []), list),
                    d.get("msg") or "ok",
                ),
            )

            items = data.get("items", [])
            for item in items:
                _process_item(item, icid, cname)
            
            consecutive_errors = 0  # 成功后重置错误计数

        except (
            requests.RequestException,
            ApiResponseError,
            TypeError,
            ValueError,
        ) as e:
            consecutive_errors += 1
            error_msg = str(e)

            # 关键修复：检测到非JSON响应（通常是Cookie过期），立即刷新
            if "非 JSON 响应" in error_msg or "JSON" in error_msg:
                log(f"   [警告] 检测到Cookie可能过期（非JSON响应），立即尝试刷新...")
                if auto_login(session_manager):
                    log(f"   [成功] Cookie已刷新，将在下次扫描使用新Cookie")
                    consecutive_errors = 0
                    # 立即使用新Cookie重试当前请求
                    headers = session_manager.get_headers_copy()
                    headers["Content-Type"] = "application/json"
                    continue  # 跳过本次循环的剩余部分，使用新headers继续
                else:
                    log(f"   [失败] Cookie刷新失败，将在下次循环重试")

            # 只在第一次非刷新类错误时记录，避免日志刷屏
            elif consecutive_errors == 1:
                log(f"   [异常] 扫描资料失败（{cname}）: {e}")


def reply_material(element_id: str, cname: str, item_name: str) -> dict:
    """手动回复学习资料，返回 {"success": bool, "detail": str}。"""
    url = f"{BASE_URL}/webios/addComment"
    payload = {"id": element_id, "content": "收到", "Type": 2}
    try:
        res = requests.post(
            url,
            headers=session_manager.get_headers_copy(),
            json=payload,
            timeout=5,
        )
        validate_json_response(
            res,
            f"reply({item_name})",
            validator=lambda d: (
                d.get("code") == 1 or d.get("status") == 1 or d.get("success") is True,
                f"code={d.get('code')}, msg={d.get('msg') or '无'}",
            ),
        )
        statistics.record_material_success()
        statistics.log_operation("material", cname, f"回复资料: {item_name}", True)
        return {"success": True, "detail": "回复成功"}
    except (requests.RequestException, ApiResponseError) as e:
        statistics.record_material_failed()
        statistics.log_operation("material", cname, f"回复失败: {item_name}", False)
        return {"success": False, "detail": str(e)}


def scan_unsubmitted_items(icid: str, course_info: dict) -> list:
    """扫描指定课程中所有未提交的活动，返回列表（不触发自动处理）。"""
    lid = course_info.get("lid")
    sid = course_info.get("sid")
    if not (lid and sid):
        return []

    session_manager.try_refresh_cookie(f"扫描待做({course_info.get('name')})")
    url = f"{BASE_URL}/Weixin/partialItemClassJson?v=808"
    headers = session_manager.get_headers_copy()
    headers["Content-Type"] = "application/json"

    unsubmitted = []
    for item_type in [1, 2, 3]:
        payload = {
            "applayType": item_type,
            "ic_id": icid,
            "batchid": None,
            "schduleid": sid,
            "lessionid": lid,
        }
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=5)
            data = validate_json_response(
                res,
                f"scan_unsubmitted({icid}, type={item_type})",
                validator=lambda d: (
                    isinstance(d.get("items", []), list),
                    d.get("msg") or "ok",
                ),
            )
            for item in data.get("items", []):
                type_name = item.get("typeName", "")
                status = item.get("StuSubmitStatus")
                element_id = item.get("courseElmentId")
                if not element_id or status == 1:
                    continue
                # 过滤掉无法自动处理的类型
                if type_name in ("举手活动", "抢答", "点将"):
                    continue
                # 分类：作业/测验/课堂活动/思政 → exam，资料 → material
                if type_name == "学习资料":
                    category = "material"
                else:
                    category = "exam"
                unsubmitted.append({
                    "courseElmentId": element_id,
                    "name": item.get("name", "未命名"),
                    "typeName": type_name,
                    "applayType": item_type,
                    "StuSubmitStatus": status,
                    "category": category,
                })
        except (requests.RequestException, ApiResponseError, TypeError, ValueError) as e:
            log(f"   [扫描待做] 获取类型 {item_type} 失败: {e}")

    return unsubmitted


def _process_item(item: dict, icid: str, cname: str):
    """处理单个任务项"""
    element_id = item.get("courseElmentId")
    if not element_id:
        return

    type_name = item.get("typeName", "")
    status = item.get("StuSubmitStatus")
    item_name = item.get("name", "未命名")

    if type_name == "学习资料" and status != 1 and reply_state.claim(element_id):
        log(f"[发现资料] {cname} 发布了新资料：{item_name}")
        _executor.submit(_delayed_reply, element_id, cname, item_name, icid)

    if (
        ("测验" in type_name or "作业" in type_name)
        and status != 1
        and exam_state.claim(element_id)
    ):
        log(f"[发现测验] {cname} 发布了新试卷：{item_name}")
        _executor.submit(process_exam, icid, element_id, cname, item_name)


def _delayed_reply(element_id: str, cname: str, item_name: str, icid: str):
    """延迟回复"""
    delay = random.randint(
        SCAN_CONFIG["material_reply_delay_min"],
        SCAN_CONFIG["material_reply_delay_max"],
    )
    time.sleep(delay)

    statistics.record_material_attempt()

    url = f"{BASE_URL}/webios/addComment"
    payload = {"id": element_id, "content": "收到", "Type": 2}

    try:
        res = requests.post(
            url,
            headers=session_manager.get_headers_copy(),
            json=payload,
            timeout=5,
        )
        validate_json_response(
            res,
            f"reply({item_name})",
            validator=lambda d: (
                d.get("code") == 1 or d.get("status") == 1 or d.get("success") is True,
                f"code={d.get('code')}, msg={d.get('msg') or '无'}",
            ),
        )
        log(f"   [成功] {cname} 资料回复成功，延迟 {delay} 秒")
        course_registry.increment_counter(icid, "material_count")
        reply_state.finish(element_id)
        statistics.record_material_success()
        statistics.log_operation("material", cname, f"回复资料: {item_name}", True)

    except (requests.RequestException, ApiResponseError) as e:
        log(f"   [失败] 资料回复失败（{item_name}）: {e}")
        reply_state.release(element_id)
        statistics.record_material_failed()
        statistics.record_error(f"资料回复失败: {e}")
        statistics.log_operation("material", cname, f"回复失败: {item_name}", False)
