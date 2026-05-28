# -*- coding: utf-8 -*-
"""
Web 模块 - HTTP 服务器和前端页面
"""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

try:
    from http.server import ThreadingHTTPServer
except ImportError:
    ThreadingHTTPServer = HTTPServer

from auto_checkin.core.scheduler import run, shutdown, get_exit_event
from auto_checkin.core.scan_mode import get_scan_mode
from auto_checkin.core.state import course_registry, retro_checkin_log
from auto_checkin.core.session import session_manager
from auto_checkin.core.course import fetch_schedule
from auto_checkin.core.statistics import statistics
from auto_checkin.core.material import scan_unsubmitted_items, reply_material
from auto_checkin.core.checkin import scan_checkin, retro_checkin
from auto_checkin.core.exam import process_exam_manual
from auto_checkin.config import UI_TOKEN, SCRIPT_DIR, COOKIE, DEEPSEEK_API_KEY, BASE_URL
from auto_checkin.logger import log, LOGS
from auto_checkin.network import get_rate_limiter_stats

_HTML_PATH = f"{SCRIPT_DIR}/static/index.html"


def _is_loopback_ip(client_ip: str) -> bool:
    """仅允许本机地址在无 Token 模式访问敏感接口。"""
    return client_ip in ("127.0.0.1", "::1", "localhost")


def _is_request_authorized(ui_token: str, auth_header: str, client_ip: str) -> bool:
    """统一鉴权逻辑。"""
    if ui_token:
        if auth_header.startswith("Bearer "):
            return auth_header[7:] == ui_token
        return False
    return _is_loopback_ip(client_ip)


def _load_html():
    """读取 index.html 内容"""
    try:
        with open(_HTML_PATH, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1 style='color:red;padding:40px'>找不到 index.html，请确保它和 .py 文件在同一目录下！</h1>"
    except Exception as e:
        return f"<h1 style='color:red;padding:40px'>读取 index.html 失败: {e}</h1>"


def _check_cookie_validity() -> dict:
    """检查 Cookie 有效性"""
    result = {"valid": False, "message": "未知"}

    if not COOKIE:
        result["message"] = "未配置 Cookie"
        return result

    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Cookie": COOKIE,
        }
        res = requests.get(
            f"{BASE_URL}/Weixin/Schedule",
            headers=headers,
            timeout=5,
            allow_redirects=False,
        )

        if res.status_code == 200 and "login" not in res.text.lower():
            result["valid"] = True
            result["message"] = "有效"
        elif (
            res.status_code in (302, 301)
            and "login" in res.headers.get("Location", "").lower()
        ):
            result["message"] = "已过期"
        else:
            result["message"] = f"状态码 {res.status_code}"
    except requests.Timeout:
        result["message"] = "连接超时"
    except requests.ConnectionError:
        result["message"] = "无法连接"
    except Exception as e:
        result["message"] = f"检查失败: {str(e)[:30]}"

    return result


def _check_deepseek_api() -> dict:
    """检查 DeepSeek API 可用性"""
    result = {"available": False, "message": "未知"}

    if not DEEPSEEK_API_KEY:
        result["message"] = "未配置 API Key"
        return result

    try:
        res = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            },
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 1,
            },
            timeout=10,
        )

        if res.status_code == 200:
            result["available"] = True
            result["message"] = "可用"
        elif res.status_code == 401:
            result["message"] = "API Key 无效"
        elif res.status_code == 429:
            result["message"] = "请求过于频繁"
        else:
            result["message"] = f"状态码 {res.status_code}"
    except requests.Timeout:
        result["message"] = "连接超时"
    except requests.ConnectionError:
        result["message"] = "无法连接"
    except Exception as e:
        result["message"] = f"检查失败: {str(e)[:30]}"

    return result


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _check_auth(self):
        """验证请求认证"""
        auth_header = self.headers.get("Authorization", "")
        client_ip = self.client_address[0] if self.client_address else ""
        if _is_request_authorized(UI_TOKEN, auth_header, client_ip):
            return True
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("WWW-Authenticate", 'Bearer realm="AutoCheckin"')
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
        return False

    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_load_html().encode("utf-8"))

        elif self.path == "/health":
            self._handle_health()

        elif self.path == "/api/data":
            if not self._check_auth():
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            runtime = course_registry.get_runtime_snapshot()
            data = {
                "schedule_text": runtime["schedule_text"],
                "logs": list(LOGS),
                "courses": runtime["courses"],
                "mode": get_scan_mode(),
                "last_login": session_manager.get_last_login_time(),
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))

        elif self.path == "/api/statistics":
            if not self._check_auth():
                return
            self._handle_statistics()

        elif self.path.startswith("/api/checkin/history"):
            if not self._check_auth():
                return
            data = {"records": retro_checkin_log.get_all(limit=50)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

        elif self.path.startswith("/api/homework/scan"):
            if not self._check_auth():
                return
            qs = parse_qs(urlparse(self.path).query)
            icid = (qs.get("icid", [""])[0])
            if not icid:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"missing icid"}')
                return
            courses = course_registry.get_snapshot()
            course_info = courses.get(icid)
            if not course_info:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":"course not found"}')
                return
            items = scan_unsubmitted_items(icid, course_info)
            data = {"items": items, "course": course_info.get("name", "")}
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/api/scan-all":
            if not self._check_auth():
                return
            courses = course_registry.get_snapshot()
            result = {"courses": {}}
            for icid, info in courses.items():
                items = scan_unsubmitted_items(icid, info)
                has_active_signin = bool(scan_checkin(icid))
                result["courses"][icid] = {
                    "name": info.get("name", ""),
                    "items": items,
                    "has_active_signin": has_active_signin,
                }
            result["total_items"] = sum(len(c["items"]) for c in result["courses"].values())
            result["total_signins"] = sum(1 for c in result["courses"].values() if c["has_active_signin"])
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def _handle_health(self):
        """处理健康检查请求"""
        health_data = {
            "status": "ok",
            "timestamp": time.time(),
            "components": {
                "server": {"status": "up"},
                "cookie": _check_cookie_validity(),
                "deepseek_api": _check_deepseek_api(),
            },
        }

        # 如果任一关键组件不可用，返回 degraded 状态
        if not health_data["components"]["cookie"]["valid"]:
            health_data["status"] = "degraded"
        if not health_data["components"]["deepseek_api"]["available"]:
            health_data["status"] = "degraded"

        status_code = 200 if health_data["status"] == "ok" else 503

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(health_data, ensure_ascii=False).encode("utf-8"))

    def _handle_statistics(self):
        """处理统计信息请求"""
        stats = statistics.get_summary()
        rate_limiter = get_rate_limiter_stats()

        data = {
            "statistics": stats,
            "rate_limiter": rate_limiter,
            "operations": statistics.get_operations(limit=50),
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_POST(self):
        if not self._check_auth():
            return
        if self.path == "/api/refresh":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            threading.Thread(target=fetch_schedule, daemon=True).start()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
        elif self.path == "/api/statistics/reset":
            statistics.reset()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))

        elif self.path == "/api/checkin/retro":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                req = json.loads(body)
                icid = req.get("icid", "")
                cname = req.get("cname", "未知课程")
            except (json.JSONDecodeError, ValueError):
                self.send_response(400)
                self.end_headers()
                return
            result = retro_checkin(icid, cname)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/api/homework/submit":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                req = json.loads(body)
                icid = req.get("icid", "")
                course_element_id = req.get("courseElmentId", "")
                cname = req.get("cname", "未知课程")
                exam_name = req.get("examName", "未知试卷")
            except (json.JSONDecodeError, ValueError):
                self.send_response(400)
                self.end_headers()
                return
            result = process_exam_manual(icid, course_element_id, cname, exam_name)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/api/material/reply":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                req = json.loads(body)
                element_id = req.get("courseElmentId", "")
                cname = req.get("cname", "未知课程")
                item_name = req.get("itemName", "未知资料")
            except (json.JSONDecodeError, ValueError):
                self.send_response(400)
                self.end_headers()
                return
            result = reply_material(element_id, cname, item_name)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/api/process-all":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                req = json.loads(body)
                items = req.get("items", [])
            except (json.JSONDecodeError, ValueError):
                self.send_response(400)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            threading.Thread(target=self._process_all_items, args=(items,), daemon=True).start()
            self.wfile.write(json.dumps({"ok": True, "total": len(items)}).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def _process_all_items(self, items):
        """后台批量处理所有待办项"""
        total = len(items)
        log(f"[批量处理] 开始处理 {total} 个待办项...")
        for i, item in enumerate(items):
            category = item.get("category", "")
            icid = item.get("icid", "")
            cname = item.get("cname", "")
            name = item.get("name", "未命名")

            if category == "signin":
                result = retro_checkin(icid, cname)
                log(f"  [{i+1}/{total}] 补签 {cname}: {result.get('detail', '')}")
            elif category == "exam":
                result = process_exam_manual(icid, item.get("courseElmentId", ""), cname, name)
                log(f"  [{i+1}/{total}] 补做 {name}: {result.get('detail', '')}")
            elif category == "material":
                result = reply_material(item.get("courseElmentId", ""), cname, name)
                log(f"  [{i+1}/{total}] 回复 {name}: {result.get('detail', '')}")

        log(f"[批量处理] 全部完成！共处理 {total} 项。")


def run_gui():
    print("=" * 60)
    print("      学会学课堂 - 自动签到系统 V4.1")
    print("=" * 60)

    _headless = os.environ.get("HEADLESS", "0") in ("1", "true", "yes")
    host = "0.0.0.0" if _headless else "127.0.0.1"
    server_address = (host, 8080)
    httpd = ThreadingHTTPServer(server_address, RequestHandler)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    display_host = "0.0.0.0" if _headless else "127.0.0.1"
    url = f"http://{display_host}:{server_address[1]}"
    print(f"控制台地址：{url}")
    if UI_TOKEN:
        print("已启用 Token 认证，请在页面中手动输入令牌访问数据接口。")
    if not _headless:
        print("正在打开浏览器控制面板...")
        time.sleep(1.5)
        webbrowser.open(url)
    else:
        print("[Docker 模式] 无头启动，请在容器外用浏览器访问以上地址。")

    print("系统已启动，请保持窗口开启。")
    print("如果浏览器没有弹出来，请手动在浏览器里输入 127.0.0.1:8080 打开面板。")

    try:
        while not get_exit_event().is_set():
            if not t.is_alive() or not server_thread.is_alive():
                break
            get_exit_event().wait(timeout=1)
    except KeyboardInterrupt:
        log("[退出] 收到 Ctrl+C，正在关闭...")
    finally:
        httpd.shutdown()
        shutdown()
        log("[退出] Web 服务已关闭。")
