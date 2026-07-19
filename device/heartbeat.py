"""
心跳检测与自动重连（01-连接模块 子模块）

后台线程定期检测 ADB 连接状态。
断线时通过事件总线广播，并按退避策略自动尝试重连。

对应解耦文档：模块说明/01-连接模块.md
"""

import time
import threading
from typing import TYPE_CHECKING

from core.event_bus import event_bus, Events

if TYPE_CHECKING:
    from device.connection import ConnectionManager


class HeartbeatMonitor:
    """心跳检测器。后台线程，定期检测连接状态。"""

    def __init__(
        self,
        connection: "ConnectionManager",
        interval: float = 30,
        auto_reconnect: bool = True,
    ):
        self._connection = connection
        self._interval = interval
        self._auto_reconnect = auto_reconnect
        self._running = False
        self._thread: threading.Thread = None

    def start(self):
        """启动心跳线程。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._check_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止心跳。"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _check_loop(self):
        """心跳检测主循环。"""
        while self._running:
            time.sleep(self._interval)
            if not self._running:
                break

            if not self._connection.is_connected():
                device_id = self._connection._active_device_id
                event_bus.publish(Events.CONNECTION_LOST, device_id=device_id)

                if self._auto_reconnect:
                    self._connection.reconnect(device_id)
