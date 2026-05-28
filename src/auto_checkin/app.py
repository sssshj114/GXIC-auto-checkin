# -*- coding: utf-8 -*-
"""
自动签到系统 - 入口模块
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from web import run_gui


if __name__ == "__main__":
    run_gui()
