"""
10-参数桥接模块

运行传参（启停信号桥接，§5.3 RunBridge）。
通过事件总线发布启停信号，不直接调 RunController。
"""
from __future__ import annotations

from typing import Any

from core.event_bus import EventBus, get_global_bus
from core.events import Events


class RunBridge:
    """运行控制桥接（§5.3）"""

    def __init__(self, event_bus: EventBus | None = None, **kwargs):
        self._bus = event_bus or get_global_bus()
        # 兼容旧构造：直接传 RunController
        self._ctrl = kwargs.get('controller')

    # ── §5.3 发布事件 ────────────────────────────────────

    def request_start(self) -> None:
        """发布 start_requested 事件（§5.3）"""
        self._bus.publish(Events.START_REQUESTED, source="RunBridge")

    def request_stop(self) -> None:
        """发布 stop_requested 事件（§5.3）"""
        self._bus.publish(Events.STOP_REQUESTED, source="RunBridge")

    def request_pause(self) -> None:
        """发布 pause_requested 事件（§5.3）"""
        self._bus.publish(Events.PAUSE_REQUESTED, source="RunBridge")

    def request_resume(self) -> None:
        """发布 resume_requested 事件（§5.3）"""
        self._bus.publish(Events.RESUME_REQUESTED, source="RunBridge")

    # ── 兼容旧名（直接调用旧版 RunController）─────────────

    def start(self) -> None:
        if self._ctrl:
            self._ctrl.start()
        else:
            self.request_start()

    def stop(self) -> None:
        if self._ctrl:
            self._ctrl.stop()
        else:
            self.request_stop()

    def pause(self) -> None:
        if self._ctrl:
            self._ctrl.pause()
        else:
            self.request_pause()

    def resume(self) -> None:
        if self._ctrl:
            self._ctrl.resume()
        else:
            self.request_resume()
