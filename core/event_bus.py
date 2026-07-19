"""
事件总线（08-事件总线模块）

发布-订阅模式的事件总线，模块间松耦合通信枢纽。
线程安全，跨线程通信，支持事件过滤和可选事件溯源。

使用方式：
    from core.event_bus import event_bus
    event_bus.subscribe("task_done", lambda task_name, success: ...)
    event_bus.publish("task_done", task_name="yuhun", success=True)
"""

import threading
import queue
import traceback
from datetime import datetime
from typing import Callable, Optional

from core.events import Events  # noqa: F401 - 方便统一 import


class Event:
    """事件对象。"""

    __slots__ = ("name", "data", "timestamp")

    def __init__(self, name: str, data: dict, timestamp: datetime = None):
        self.name = name
        self.data = data or {}
        self.timestamp = timestamp or datetime.now()

    def __repr__(self):
        return f"Event({self.name}, ts={self.timestamp.isoformat()})"


class EventBus:
    """发布-订阅事件总线。全局单例，线程安全。"""

    def __init__(self, enable_history: bool = False):
        self._subscribers: dict[str, list[tuple[Callable, Optional[Callable], str]]] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._running = True
        self._dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._dispatch_thread.start()

        # 可选事件历史（调试用）
        self._enable_history = enable_history
        self._history: list[Event] = [] if enable_history else None
        self._history_max = 500

    # ==================== 发布 ====================

    def publish(self, event_name: str, **data):
        """发布事件。立即返回，异步分发。"""
        event = Event(name=event_name, data=data)
        self._queue.put(event)

    # ==================== 订阅 ====================

    def subscribe(
        self,
        event_name: str,
        handler: Callable,
        filter_func: Callable = None,
    ) -> str:
        """订阅事件。

        Args:
            event_name: 事件名（支持 Events 常量）
            handler: 回调函数，接收 **data 关键参数
            filter_func: 可选过滤函数，接收 Event 对象，返回 True 才执行 handler

        Returns:
            订阅 ID（用于取消订阅）
        """
        sub_id = f"{event_name}:{id(handler)}"
        with self._lock:
            if event_name not in self._subscribers:
                self._subscribers[event_name] = []
            self._subscribers[event_name].append((handler, filter_func, sub_id))
        return sub_id

    def unsubscribe(self, subscription_id: str):
        """取消订阅。"""
        with self._lock:
            for event_name, handlers in self._subscribers.items():
                self._subscribers[event_name] = [
                    (h, f, sid) for h, f, sid in handlers if sid != subscription_id
                ]

    def clear(self):
        """清空所有订阅（测试用）。"""
        with self._lock:
            self._subscribers.clear()
            if self._history is not None:
                self._history.clear()

    # ==================== 分发 ====================

    def _dispatch_loop(self):
        """工作线程：从队列取事件，分发给订阅者。"""
        while self._running:
            try:
                event = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # 记录历史
            if self._history is not None:
                self._history.append(event)
                if len(self._history) > self._history_max:
                    self._history.pop(0)

            # 分发
            with self._lock:
                handlers = list(self._subscribers.get(event.name, []))
            for handler, filter_func, _ in handlers:
                try:
                    if filter_func is None or filter_func(event):
                        handler(**event.data)
                except Exception:
                    traceback.print_exc()

    # ==================== 生命周期 ====================

    def shutdown(self):
        """关闭事件总线（程序退出时调用）。"""
        self._running = False
        if self._dispatch_thread.is_alive():
            self._dispatch_thread.join(timeout=2)

    # ==================== 调试 ====================

    def get_history(self, event_name: str = None, limit: int = 50) -> list[Event]:
        """获取事件历史（需 enable_history=True）。"""
        if self._history is None:
            return []
        if event_name:
            return [e for e in self._history[-limit:] if e.name == event_name]
        return self._history[-limit:]

    def get_subscriber_count(self, event_name: str = None) -> int:
        """获取订阅者数量。"""
        with self._lock:
            if event_name:
                return len(self._subscribers.get(event_name, []))
            return sum(len(h) for h in self._subscribers.values())


# ==================== 全局单例 ====================

event_bus = EventBus(enable_history=True)
