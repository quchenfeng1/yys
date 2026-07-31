"""
02-图像识别模块 — TriggerWatcher 触发监控子服务

对触发式任务（repeat.type=trigger）的识别列表（trigger_templates）持续监控：
截图 → match_any(识别列表) → 命中 → 发布 TRIGGER_DETECTED 事件。
05-时间调度模块 订阅后调 update_next_run(name, now) 使任务立即到期入队。

职责边界（设计书 §3.6）：
- 只负责"识别到 → 发布事件"，不直接修改任何调度状态（保持 02 无副作用原则）
- 不持有 Scheduler 引用；触发模板列表由 09-运行控制中心 在 start() 时传入
- 线程安全：截图/识别全部走 Recognizer 的 _cache_lock/_screenshot_ttl 机制，
  与执行线程的截图缓存隔离

生命周期：由 09-运行控制中心 构造时内部创建，_on_start 时 start()，_on_stop 时 stop()。
"""
from __future__ import annotations

import threading
from typing import Any

from core.events import Events


class TriggerWatcher:
    """触发监控子服务（02 说明书 §3.6 + §5.3）"""

    def __init__(
        self,
        recognizer: Any = None,
        connection: Any = None,
        event_bus: Any = None,
        interval: float = 2.0,
    ):
        self._recognizer = recognizer
        self._connection = connection  # 保留备用（截图统一走 recognizer）
        self._bus = event_bus
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._tasks: dict[str, list[str]] = {}  # 任务名 → 触发模板列表

    # ── 生命周期（§5.3 start/stop）──────────────────────────

    def start(self, trigger_tasks: list[tuple[str, list[str]]] | None = None) -> None:
        """
        启动触发监控。

        Args:
            trigger_tasks: [(task_name, [触发模板名, ...]), ...]。由 09-运行控制中心
                从 Scheduler.get_all_tasks() 收集 repeat.type=trigger 的任务传入；
                None 则保持上次配置。
        """
        if trigger_tasks is not None:
            self._tasks = {name: [t for t in tmpls if t] for name, tmpls in trigger_tasks}
        if not self._tasks:
            return  # 无触发式任务 → 不启动线程
        if self._thread and self._thread.is_alive():
            return  # 已运行
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="trigger_watcher"
        )
        self._thread.start()

    def stop(self) -> None:
        """停止触发监控。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None

    def is_running(self) -> bool:
        """是否在运行。"""
        return bool(self._thread and self._thread.is_alive())

    # ── 监控循环（§3.6）─────────────────────────────────────

    def _monitor_loop(self) -> None:
        """常驻监控循环：扫描 → 可打断休眠。"""
        while not self._stop_event.is_set():
            try:
                self._scan_once()
            except Exception:
                pass
            # 可打断休眠（分段等待，快速响应停止）
            self._stop_event.wait(self._interval)

    def _scan_once(self) -> None:
        """
        单轮扫描：对每个触发式任务识别其模板列表，命中 → 发布事件。

        每次扫描每任务至多发布一次 trigger_detected（同一时刻只触发一次）；
        跨扫描周期按配置重复检测（用户约定：任务执行动作会使触发图片消失，
        天然避免反复触发）。
        """
        if not self._recognizer or not self._bus:
            return
        for task_name, templates in list(self._tasks.items()):
            if self._stop_event.is_set():
                return
            if not templates:
                continue
            try:
                hits = self._recognizer.match_any(templates)
            except Exception:
                continue
            if hits:
                self._bus.publish(
                    Events.TRIGGER_DETECTED,
                    source="trigger_watcher",
                    task_name=task_name,
                    templates=[h[0] for h in hits],
                )
