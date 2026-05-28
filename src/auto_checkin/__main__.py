# -*- coding: utf-8 -*-
"""
python -m auto_checkin 入口
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from auto_checkin.web import run_gui

if __name__ == "__main__":
    run_gui()
