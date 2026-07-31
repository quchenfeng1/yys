"""
01-设备连接模块

心跳检测线程（仅检测，不重连）。
职责:
- 定期检查设备连接状态（adb shell echo ok, timeout=5s）
- 检测到断线后发布事件 + 设置 _conn_pause_event
- 不执行重连（重连由 ConnectionManager 或上层决定）
"""
from __future__ import annotations

import threading
import time
from typing import Any

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.exceptions import HeartbeatError
from device.connection import ConnectionManager


class HeartbeatMonitor:
    """心跳检测监视器（仅检测，不重连）"""

    def __init__(
        self,
        connection: ConnectionManager,
        event_bus: EventBus | None = None,
        interval: float = 30.0,
    ):
        self._conn = connection
        self._bus = event_bus or get_global_bus()
        self._interval = interval
        self._running = False
        self._thread: threading.Thread | None = None
        self._fail_count = 0
        self._max_fails = 3

    # ── 生命周期 ──────────────────────────────────────────────

    def start(self) -> None:
        """启动心跳检测"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="heartbeat"
        )
        self._thread.start()

    def stop(self) -> None:
        """停止心跳检测。join(timeout=5)，超时后记录警告"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                import logging
                logging.warning("心跳线程未能在 5s 内退出，可能卡在 ADB 命令中")
            self._thread = None

    def _loop(self) -> None:
        """心跳检测主循环"""
        while self._running:
            try:
                if self._conn.is_connected():
                    # 使用 echo 检测（adb shell echo ok, timeout=5s）
                    ok = self._conn.echo()
                    if ok:
                        self._fail_count = 0
                    else:
                        self._on_disconnect()
                else:
                    self._fail_count += 1

            except Exception:
                self._fail_count += 1
                # 异常也视为断线，立即暂停操作
                self._on_disconnect()

            # 连续失败告警
            if self._fail_count >= self._max_fails:
                self._bus.publish(
                    Events.CONNECTION_ERROR,
                    source="heartbeat",
                    error=f"心跳连续失败 {self._fail_count} 次",
                )
                # 设置连接暂停事件（阻止设备操作）
                self._conn.pause_operations()

            time.sleep(self._interval)

    def _on_disconnect(self) -> None:
        """检测到断线后的处理（只发布事件，不重连）"""
        self._bus.publish(Events.CONNECTION_LOST, source="heartbeat")
        self._conn.pause_operations()  # 暂停操作

    # ── 状态 ──────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def fail_count(self) -> int:
        return self._fail_count

    def reset_fails(self) -> None:
        """重置失败计数"""
        self._fail_count = 0
