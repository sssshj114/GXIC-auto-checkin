# -*- coding: utf-8 -*-
"""
课表模块 - 获取和解析课表
"""

from __future__ import annotations

import re
import html as html_module
import requests
from urllib.parse import urlparse, parse_qs
from auto_checkin.logger import log
from auto_checkin.network import validate_json_response, ApiResponseError
from auto_checkin.config import BASE_URL
from auto_checkin.core.session import session_manager, auto_login
from auto_checkin.core.state import course_registry


def fetch_schedule():
    """获取并解析课表"""
    url = f"{BASE_URL}/Weixin/partialSchedule"
    relogin_attempted = False

    while True:
        headers = session_manager.get_headers_copy()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        try:
            res = requests.post(url, headers=headers, timeout=10)

            final_url = res.url
            need_relogin = (
                "login" in final_url.lower()
                or "account" in final_url.lower()
                or res.status_code in (401, 403)
                or "请登录" in res.text
                or "loginForm" in res.text
                or "登录账号" in res.text
            )

            if need_relogin:
                if relogin_attempted:
                    log("⚠️ [警告] Cookie 刷新后仍无法拉取课表，本次不再重复重试。")
                    return
                log("⚠️ [警告] 检测到 Cookie 已失效！尝试自动重新登录...")
                if not auto_login(session_manager):
                    return
                relogin_attempted = True
                continue

            new_courses = _parse_schedule(res.text)

            schedule_html = (
                "课表数据已更新。" if new_courses else "未识别到可监控课程。"
            )
            course_registry.update(new_courses, schedule_html)

            log(
                f"课表数据获取成功！共识别出 {len(new_courses)} 门课程。将同时监控【签到】+【资料回复】+【AI做题】。"
            )
            return

        except requests.RequestException as e:
            log(f"课表拉取失败（网络请求异常）: {e}")
            return
        except Exception as e:
            log(f"课表拉取失败（课表解析异常）: {e}")
            return


def _parse_schedule(html_text: str) -> dict:
    """解析课表HTML"""
    courses = {}
    matches = re.finditer(
        r'href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>',
        html_text,
        re.DOTALL | re.IGNORECASE,
    )

    for m in matches:
        url_str = m.group(1).replace("&amp;", "&")
        if "icid=" not in url_str.lower():
            continue

        qs = parse_qs(urlparse(url_str).query)
        lid = qs.get("lessionid", [None])[0]
        sid = qs.get("scheduleid", [None])[0]
        if not sid:
            sid = qs.get("schduleid", [None])[0]
        icid = qs.get("icid", [None])[0]

        if not icid:
            continue

        name_html = m.group(2).strip()
        name = html_module.unescape(re.sub(r"<[^>]+>", " ", name_html)).strip()
        name = " ".join(name.split())
        if len(name) > 15:
            name = name[:15] + "..."

        courses[icid] = {
            "name": name,
            "checked": False,
            "lid": lid,
            "sid": sid,
            "material_count": 0,
            "exam_count": 0,
        }

    return courses
