"""
08-事件通信总线

EventBus — 异步分发模式（队列+分发线程）。
对应设计书 §3/§4/§5。

支持:
- 异步队列分发（maxsize=1000，永不丢事件）
- 订阅/取消订阅，支持 filter 条件过滤
- 去重合并（200ms 窗口，自动取 str(data)[:64] 为去重键）
- 事件历史记录（deque maxlen=2000，可选启用）
- 异常隔离（单个 handler 异常不影响其他）
- handler 软超时（5s 记录警告但不中断）
- Handler 签名：`handler(**event.data)` — 事件数据解包为 kwargs
- Filter 签名：`filter(**event.data) -> bool` — 同上
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

logger = logging.getLogger("yys.event_bus")

SubscriberFn = Callable[..., None]
InterceptorFn = Callable[[str, tuple, dict], bool]
FilterFn = Callable[..., bool]


@dataclass
class Event:
    """事件数据（§5.2）"""
    name: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    dedup_key: str = ""


@dataclass
class Subscription:
    """订阅记录（§5.2 Subscriber）"""
    event: str
    callback: SubscriberFn        # handler(**event.data) -> None
    filter_fn: FilterFn | None = None  # filter(**event.data) -> bool
    priority: int = 0
    once: bool = False
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class EventRecord:
    """事件历史记录（§4.3）"""
    event: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    thread_name: str = field(default_factory=lambda: threading.current_thread().name)


class EventBus:
    """
    异步事件总线（§5.3 方法定义）。

    用法:
        bus = EventBus()
        bus.subscribe("task.started", lambda task_id, **kw: print(task_id))
        bus.publish("task.started", task_id="123")

    Handler 签名: handler(**event.data)  — 事件数据解包为关键字参数
    Filter 签名:  filter(**event.data) -> bool
    publish 立即返回，handler 在分发线程中异步执行。
    """

    def __init__(
        self,
        max_queue: int = 1000,
        max_history: int = 2000,
        dedup_window: float = 0.2,
        handler_timeout: float = 5.0,
        enable_history: bool = True,
        monitor: Any = None,
    ):
        self._lock = threading.Lock()
        self._dedup_lock = threading.Lock()
        self._subscribers: dict[str, list[Subscription]] = {}
        self._interceptors: list[InterceptorFn] = []
        self._monitor = monitor  # §2.1 可选

        # 异步队列（§3.3 队列背压：永不丢事件）
        self._queue: queue.Queue[Event] = queue.Queue(maxsize=max_queue)
        self._stop_event = threading.Event()
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="eventbus_dispatch"
        )
        self._dispatch_thread.start()

        # §4.3 事件历史（环形缓冲）
        self._enable_history = enable_history
        self._history: deque[EventRecord] = deque(maxlen=max_history)

        # §3.3 去重
        self._dedup_window = dedup_window
        self._dedup_cache_ttl: float = 2.0  # 去重缓存条目过期时间（§3.3 清理超过 2s 的旧条目）
        self._last_event_cache: dict[str, float] = {}
        self._publish_counter = 0

        # §3.3 handler 软超时
        self._handler_timeout = handler_timeout

    # ── §2.2 对外暴露属性 ────────────────────────────────────

    @property
    def history_enabled(self) -> bool:
        """是否开启事件历史记录（§2.2）"""
        return self._enable_history

    # ── 订阅管理 ──────────────────────────────────────────────

    def subscribe(
        self,
        event: str,
        callback: SubscriberFn,
        filter_fn: FilterFn | None = None,
        priority: int = 0,
        once: bool = False,
    ) -> str:
        """订阅事件，返回 UUID 订阅 ID。"""
        sub = Subscription(
            event=event,
            callback=callback,
            filter_fn=filter_fn,
            priority=priority,
            once=once,
        )
        with self._lock:
            self._subscribers.setdefault(event, []).append(sub)
            self._subscribers[event].sort(key=lambda s: s.priority, reverse=True)
        return sub.uid

    def unsubscribe(self, uid: str) -> bool:
        """通过 UUID 取消订阅。"""
        with self._lock:
            for subs in self._subscribers.values():
                for i, s in enumerate(subs):
                    if s.uid == uid:
                        subs.pop(i)
                        return True
        return False

    def unsubscribe_event(self, event: str, callback: SubscriberFn | None = None) -> int:
        """取消某事件的所有订阅。"""
        count = 0
        with self._lock:
            subs = self._subscribers.get(event, [])
            if callback is None:
                count = len(subs)
                self._subscribers[event] = []
            else:
                remaining = [s for s in subs if s.callback != callback]
                count = len(subs) - len(remaining)
                self._subscribers[event] = remaining
        return count

    def listen_once(self, event: str, callback: SubscriberFn, **kwargs) -> str:
        """一次性监听"""
        return self.subscribe(event, callback, once=True, **kwargs)

    # ── 发布 ──────────────────────────────────────────────────

    def publish(
        self,
        name: str,
        source: str = "",
        dedup_key: str | None = None,
        **data: Any,
    ) -> None:
        """
        发布事件（异步入队，§5.3）。

        Handler 签名: handler(**event.data) — 订阅者接收解包后的数据 key=value

        Args:
            name: 事件名
            source: 事件来源（模块名）
            dedup_key: 去重键（默认取 str(data)[:64]），200ms 内相同键跳过
            **data: 事件数据
        """
        # §3.3 去重键计算（默认取 data 摘要前 64 字符）
        effective_dedup_key = dedup_key or str(data)[:64]
        full_key = f"{name}:{effective_dedup_key}"

        with self._dedup_lock:
            now = time.time()
            last = self._last_event_cache.get(full_key, 0.0)
            if now - last < self._dedup_window:
                return
            self._last_event_cache[full_key] = now
            self._publish_counter += 1
            if self._publish_counter >= 100:
                self._clean_dedup_cache()

        event = Event(name=name, data=data, source=source, dedup_key=effective_dedup_key)

        # 拦截器
        for interceptor in self._interceptors:
            try:
                if not interceptor(event.name, (), event.data):
                    return
            except Exception:
                logger.error("Interceptor error: %s", traceback.format_exc())

        # §3.1 + §4.3 入队（永不丢事件，§3.3 队列背压）
        try:
            self._queue.put(event, block=True, timeout=None)
        except queue.Full:
            # queue.Queue(maxsize) 在 block=True, timeout=None 时不会触发 Full
            pass

    def _clean_dedup_cache(self) -> None:
        """清理过期去重缓存（超过 2s 的旧条目移除，§3.3）"""
        now = time.time()
        expired = [
            k for k, v in self._last_event_cache.items()
            if now - v > self._dedup_cache_ttl  # 2s
        ]
        for k in expired:
            self._last_event_cache.pop(k, None)
        self._publish_counter = 0

    def _dispatch_loop(self) -> None:
        """分发线程主循环（§5.4）"""
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            self._dispatch(event)

    def _dispatch(self, event: Event) -> None:
        """向所有匹配的订阅者分发事件（§5.4 + §3.1）"""
        with self._lock:
            subs = list(self._subscribers.get(event.name, []))
            # 通配符订阅
            for evt, evt_subs in self._subscribers.items():
                if evt != event.name and self._match_wildcard(evt, event.name):
                    subs.extend(evt_subs)

        to_remove: list[str] = []
        for sub in subs:
            # filter（解包 data 为 kwargs）
            if sub.filter_fn:
                try:
                    if not sub.filter_fn(**event.data):
                        continue
                except Exception:
                    continue

            # §3.3 执行 handler（软超时：记录警告但不中断）
            start_time = time.time()
            try:
                sub.callback(**event.data)
            except Exception:
                logger.error(
                    "EventBus handler error [%s]: %s",
                    event.name,
                    traceback.format_exc(),
                )

            # §3.3 handler 软超时检测
            elapsed = time.time() - start_time
            if elapsed > self._handler_timeout:
                logger.warning(
                    "Handler 执行超时(%.1fs > %.1fs) [%s]: %s",
                    elapsed, self._handler_timeout, event.name, sub.callback,
                )

            if sub.once:
                to_remove.append(sub.uid)

        # §4.3 事件历史记录（分发后记录，确保已执行的才进入历史）
        if self._enable_history:
            self._history.append(EventRecord(
                event=event.name, data=event.data,
                thread_name=threading.current_thread().name,
            ))

        # 清理一次性订阅
        for uid in to_remove:
            self.unsubscribe(uid)

    @staticmethod
    def _match_wildcard(pattern: str, name: str) -> bool:
        """通配符匹配（如 "task.*" 匹配 "task.started"）"""
        if pattern.endswith(".*"):
            return name.startswith(pattern[:-1])
        return False

    # ── 拦截器 ────────────────────────────────────────────────

    def add_interceptor(self, fn: InterceptorFn) -> None:
        """添加拦截器"""
        self._interceptors.append(fn)

    def remove_interceptor(self, fn: InterceptorFn) -> None:
        """移除拦截器"""
        self._interceptors[:] = [f for f in self._interceptors if f != fn]

    # ── 查询 ──────────────────────────────────────────────

    def subscriber_count(self, event: str | None = None) -> int:
        with self._lock:
            if event:
                return len(self._subscribers.get(event, []))
            return sum(len(s) for s in self._subscribers.values())

    def get_history(self, event: str | None = None, limit: int = 50) -> list[EventRecord]:
        history_list = list(self._history)
        if event:
            return [r for r in history_list[-limit:] if r.event == event]
        return history_list[-limit:]

    def clear_history(self) -> None:
        self._history.clear()

    def queue_size(self) -> int:
        return self._queue.qsize()

    # ── 生命周期 ──────────────────────────────────────────────

    def stop(self) -> None:
        """停止分发线程，清空队列"""
        self._stop_event.set()
        if self._dispatch_thread.is_alive():
            self._dispatch_thread.join(timeout=3)
        # 清空队列
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()
            self._interceptors.clear()
            self.clear_history()
            with self._dedup_lock:
                self._last_event_cache.clear()


# 全局默认实例
_global_bus: EventBus | None = None
_global_bus_lock = threading.Lock()


def get_global_bus() -> EventBus:
    global _global_bus
    if _global_bus is None:
        with _global_bus_lock:
            if _global_bus is None:
                _global_bus = EventBus()
    return _global_bus


def reset_global_bus() -> None:
    global _global_bus
    with _global_bus_lock:
        _global_bus = None

