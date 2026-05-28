# -*- coding: utf-8 -*-
"""
配置模块 - 负责所有配置加载和环境变量读取
"""

from __future__ import annotations

import os


# ================= 路径配置 =================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))


# ================= 从 .env 文件读取敏感配置 =================
def _load_env():
    """从项目 data/ 目录下的 .env 文件加载 KEY=VALUE 键值对到环境变量。"""
    env_path = os.path.join(PROJECT_ROOT, "data", ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


_load_env()

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(PROJECT_ROOT, "data"))

# ================= 服务地址配置 =================
BASE_URL = os.environ.get("BASE_URL", "https://gxic.itolearn.com").rstrip("/")

# ================= 凭证配置 =================
COOKIE = os.environ.get("COOKIE", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
COOKIE_PERSIST_ENABLED = (
    os.environ.get("COOKIE_PERSIST_ENABLED", "false").lower() == "true"
)

# ================= 认证配置 =================
UI_TOKEN = os.environ.get("UI_TOKEN", "")

# ================= 自动登录凭证 =================
WEIXIN_ID = os.environ.get("WEIXIN_ID", "")
STUDENT_CODE = os.environ.get("STUDENT_CODE", "")
LOGIN_PASSWORD = os.environ.get("LOGIN_PASSWORD", "")
PHOTO_ADDRESS = os.environ.get("PHOTO_ADDRESS", "")


# ================= 作息时间配置 =================
def _parse_time_list_env(env_key: str, default: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """从环境变量解析时间点配置，格式：HH:MM,HH:MM,..."""
    val = os.environ.get(env_key, "")
    if not val:
        return default
    result = []
    for part in val.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if ":" in part:
                h, m = map(int, part.split(":"))
            else:
                h, m = map(int, part.split("."))
            result.append((h, m))
        except ValueError:
            return default
    return result if result else default


def _parse_period_list_env(env_key: str, default: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """从环境变量解析时间段配置，格式：HH:MM-HH:MM,HH:MM-HH:MM,..."""
    val = os.environ.get(env_key, "")
    if not val:
        return default

    result = []
    for part in val.split(","):
        part = part.strip()
        if not part or "-" not in part:
            return default
        start_str, end_str = [item.strip() for item in part.split("-", 1)]
        try:
            start_h, start_m = map(int, start_str.replace(".", ":").split(":"))
            end_h, end_m = map(int, end_str.replace(".", ":").split(":"))
        except ValueError:
            return default
        result.append((start_h, start_m, end_h, end_m))

    return result if result else default


# 课程开始时间列表，格式：(小时, 分钟)
CLASS_STARTS = _parse_time_list_env(
    "SCHEDULE_CLASS_STARTS",
    [
        (8, 40),
        (9, 30),
        (10, 30),
        (11, 20),
        (14, 30),
        (15, 20),
        (16, 10),
        (17, 0),
        (19, 40),
        (20, 30),
    ],
)

# 课程时段列表，格式：(开始时, 开始分, 结束时, 结束分)
CLASS_PERIODS = _parse_period_list_env(
    "SCHEDULE_CLASS_PERIODS",
    [
        (8, 40, 9, 20),
        (9, 30, 10, 10),
        (10, 30, 11, 10),
        (11, 20, 12, 0),
        (14, 30, 15, 10),
        (15, 20, 16, 0),
        (16, 10, 16, 50),
        (17, 0, 17, 40),
        (19, 40, 20, 20),
        (20, 30, 21, 10),
    ],
)

# ================= 扫描配置 =================
HIGH_ALERT_BEFORE = int(os.environ.get("HIGH_ALERT_BEFORE", "5"))  # 课前几分钟
HIGH_ALERT_AFTER = int(os.environ.get("HIGH_ALERT_AFTER", "20"))  # 课后几分钟

SCAN_CONFIG = {
    "fast_scan_interval_min": int(os.environ.get("FAST_SCAN_INTERVAL_MIN", "12")),
    "fast_scan_interval_max": int(os.environ.get("FAST_SCAN_INTERVAL_MAX", "15")),
    "slow_scan_interval_min": int(os.environ.get("SLOW_SCAN_INTERVAL_MIN", "180")),
    "slow_scan_interval_max": int(os.environ.get("SLOW_SCAN_INTERVAL_MAX", "300")),
    "checkin_delay_min": int(os.environ.get("CHECKIN_DELAY_MIN", "5")),
    "checkin_delay_max": int(os.environ.get("CHECKIN_DELAY_MAX", "10")),
    "material_reply_delay_min": int(os.environ.get("MATERIAL_REPLY_DELAY_MIN", "10")),
    "material_reply_delay_max": int(os.environ.get("MATERIAL_REPLY_DELAY_MAX", "35")),
    "exam_think_time_min": int(os.environ.get("EXAM_THINK_TIME_MIN", "3")),
    "exam_think_time_max": int(os.environ.get("EXAM_THINK_TIME_MAX", "12")),
}

# ================= 线程池配置 =================
EXECUTOR_MAX_WORKERS = int(
    os.environ.get("EXECUTOR_MAX_WORKERS", "10")
)  # 最大并发线程数

# ================= 日志配置 =================
MAX_LOG_SIZE_MB = int(os.environ.get("MAX_LOG_SIZE_MB", "5")) * 1024 * 1024
MAX_LOG_LINES = int(os.environ.get("MAX_LOG_LINES", "100"))  # Web UI 显示的最大日志条数

# ================= 错误抑制配置 =================
ERROR_SUPPRESSION_ENABLED = os.environ.get("ERROR_SUPPRESSION_ENABLED", "true").lower() == "true"
ERROR_SUPPRESSION_WINDOW = int(os.environ.get("ERROR_SUPPRESSION_WINDOW", "60"))  # 秒

# ================= 登录配置 =================
LOGIN_INTERVAL = 43 * 3600  # Cookie 有效期 48h，提前 5h 主动续期
