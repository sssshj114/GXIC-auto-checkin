# -*- coding: utf-8 -*-
"""
Session管理模块 - HTTP Headers、Cookie、自动登录
"""

from __future__ import annotations

import os
import time
import threading
import requests
from auto_checkin.config import (
    COOKIE,
    WEIXIN_ID,
    STUDENT_CODE,
    LOGIN_PASSWORD,
    PHOTO_ADDRESS,
    LOGIN_INTERVAL,
    DATA_DIR,
    BASE_URL,
    COOKIE_PERSIST_ENABLED,
)
from auto_checkin.logger import log


class SessionManager:
    """Session和Cookie管理"""

    def __init__(self):
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf254162e) XWEB/18163 Flue",
            "Accept": "application/json, text/plain, */*",
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": COOKIE,
        }
        self._last_login_time = 0.0
        self._lock = threading.RLock()

    def get_headers_copy(self) -> dict:
        with self._lock:
            return self._headers.copy()

    def get_last_login_time(self) -> float:
        with self._lock:
            return self._last_login_time

    def update_cookie(self, cookie_str: str):
        with self._lock:
            self._headers["Cookie"] = cookie_str
            self._last_login_time = time.time()

    def try_refresh_cookie(self, label: str = ""):
        """定时续期检查"""
        if time.time() - self.get_last_login_time() > LOGIN_INTERVAL:
            if auto_login(self):
                log(f"[续期] {label}Cookie 自动续期成功")


def auto_login(session_manager: SessionManager) -> bool:
    """调用 RegWeixinUser 接口自动获取新 Cookie"""
    if not all([WEIXIN_ID, STUDENT_CODE, LOGIN_PASSWORD]):
        log(
            "[自动登录] 缺少登录凭证（WEIXIN_ID / STUDENT_CODE / LOGIN_PASSWORD），跳过自动登录。"
        )
        return False

    log("[自动登录] 正在重新登录获取新 Cookie...")
    base_ua = session_manager.get_headers_copy()["User-Agent"]

    try:
        sess = requests.Session()
        try:
            sess.get(
                f"{BASE_URL}/Weixin/Schedule",
                headers={"User-Agent": base_ua, "Accept": "text/html"},
                timeout=5,
            )
        except requests.RequestException:
            pass

        login_headers = {
            "User-Agent": base_ua,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        payload = {
            "oper": {
                "weixinID": WEIXIN_ID,
                "Code": STUDENT_CODE,
                "Password": LOGIN_PASSWORD,
                "Status": True,
                "PhotoAddress": PHOTO_ADDRESS,
            }
        }
        r = sess.post(
            f"{BASE_URL}/Weixin/RegWeixinUser",
            headers=login_headers,
            json=payload,
            timeout=10,
        )
        cookies = sess.cookies.get_dict()
        if ".ASPXAUTH" not in cookies:
            log(f"[自动登录] 登录失败，服务器响应: {r.text[:200]}")
            return False

        ordered = {}
        if "ASP.NET_SessionId" in cookies:
            ordered["ASP.NET_SessionId"] = cookies.pop("ASP.NET_SessionId")
        ordered.update(cookies)
        cookie_str = "; ".join(f"{k}={v}" for k, v in ordered.items())

        session_manager.update_cookie(cookie_str)
        if COOKIE_PERSIST_ENABLED:
            _update_env("COOKIE", cookie_str)
            log(
                "✅ [自动登录] Cookie 已自动刷新成功，新 Cookie 有效期约 48 小时，已回写 .env。"
            )
        else:
            log("✅ [自动登录] Cookie 已自动刷新成功，新 Cookie 仅保存在当前进程。")
        return True

    except requests.RequestException as e:
        log(f"[自动登录] 网络请求异常: {e}")
        return False
    except Exception as e:
        log(f"[自动登录] 登录流程异常: {e}")
        return False


def _update_env(key: str, value: str):
    """更新 .env 文件中指定 key 的值"""
    env_path = os.path.join(DATA_DIR, ".env")
    try:
        lines = []
        found = False
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith(f"{key}="):
                        lines.append(f"{key}={value}\n")
                        found = True
                    else:
                        lines.append(line)
        if not found:
            lines.append(f"{key}={value}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception as e:
        log(f"[.env更新] 写入失败: {e}")


session_manager = SessionManager()
