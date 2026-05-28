# -*- coding: utf-8 -*-
"""
健康检查模块 - 监控系统健康状态并自动恢复
"""

from __future__ import annotations

import time
import threading
from auto_checkin.logger import log
from auto_checkin.core.session import session_manager, auto_login


class HealthMonitor:
    """系统健康监控器"""

    def __init__(self):
        self._consecutive_failures = 0
        self._last_success_time = time.time()
        self._lock = threading.Lock()
        self._failure_threshold = 10  # 连续失败阈值
        self._recovery_cooldown = 300  # 恢复冷却时间（秒）
        self._last_recovery_attempt = 0

    def record_success(self):
        """记录成功请求"""
        with self._lock:
            if self._consecutive_failures > 0:
                log(f"[健康检查] 系统恢复正常，之前连续失败 {self._consecutive_failures} 次")
            self._consecutive_failures = 0
            self._last_success_time = time.time()

    def record_failure(self, error_type: str = "unknown"):
        """记录失败请求"""
        with self._lock:
            self._consecutive_failures += 1
            
            # 达到阈值时触发恢复机制
            if self._consecutive_failures >= self._failure_threshold:
                self._try_recovery(error_type)

    def _try_recovery(self, error_type: str):
        """尝试恢复系统"""
        now = time.time()
        
        # 冷却期内不重复尝试
        if now - self._last_recovery_attempt < self._recovery_cooldown:
            return
        
        self._last_recovery_attempt = now
        log(f"[健康检查] 检测到连续 {self._consecutive_failures} 次失败（{error_type}），尝试恢复...")
        
        # 尝试刷新登录状态
        try:
            if auto_login(session_manager):
                log("[健康检查] ✅ 登录状态已刷新")
                self._consecutive_failures = 0
            else:
                log("[健康检查] ❌ 登录刷新失败")
        except Exception as e:
            log(f"[健康检查] 恢复过程异常: {e}")

    def get_status(self) -> dict:
        """获取健康状态"""
        with self._lock:
            return {
                "consecutive_failures": self._consecutive_failures,
                "last_success_time": self._last_success_time,
                "is_healthy": self._consecutive_failures < self._failure_threshold,
            }


# 全局健康监控实例
health_monitor = HealthMonitor()
