"""
02-图像识别模块 — TriggerWatcher 触发监控子服务

触发式任务（repeat.type=trigger）监控（2026-08-16 重构为多对多索引）：

- 触发素材 = 带 signal 的场景素材（SceneStore 场景，信号即触发键）；
  任务通过 trigger_templates 绑定多个信号（多对多）。
- RunController 收集时构建反向索引 {模板路径: [任务,...]}（信号先展开为
  多特征块模板），并把全部模板**去重**成一份列表。
- 监控循环：每轮只截一次图、只调一次 match_any(全局去重模板)，
  命中哪些模板 → 索引反查 → 每个关联任务发布一次 TRIGGER_DETECTED。
  O(去重模板数) 而非 O(任务数×模板数)。

职责边界（设计书 §3.6）：
- 只负责"识别到 → 发布事件"，不直接修改任何调度状态
- 不持有 Scheduler 引用；索引与模板列表由 09-运行控制中心 在 start() 时传入
- 线程安全：截图/识别全部走 Recognizer 的 _cache_lock/_screenshot_ttl 机制

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
        # 多对多索引：{模板路径: [任务名, ...]}；模板 = 信号展开后的特征块
        # （或旧素材路径原样）
        self._tpl_tasks: dict[str, list[str]] = {}
        self._templates: list[str] = []   # 去重后的全局模板列表

    # ── 生命周期（§5.3 start/stop）──────────────────────────

    def start(self, template_tasks: dict[str, list[str]] | None = None,
              templates: list[str] | None = None) -> None:
        """
        启动触发监控（多对多索引，2026-08-16）。

        Args:
            template_tasks: {模板路径: [关联任务名,...]}（信号已展开为特征块模板）。
                None 则保持上次配置。
            templates: 去重后的全局模板列表（None → 取 template_tasks 的键）。
        """
        if template_tasks is not None:
            self._tpl_tasks = {
                t: [n for n in names if n] for t, names in template_tasks.items()
                if names}
            self._templates = list(templates) if templates is not None \
                else sorted(self._tpl_tasks.keys())
        if not self._templates:
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
        单轮扫描：一次 match_any(全局去重模板) → 命中模板反查索引 →
        每个关联任务发布一次 TRIGGER_DETECTED。

        每次扫描每任务至多发布一次 trigger_detected（同一时刻只触发一次）；
        跨扫描周期按配置重复检测（用户约定：任务执行动作会使触发图片消失，
        天然避免反复触发）。
        """
        if not self._recognizer or not self._bus or not self._templates:
            return
        try:
            hits = self._recognizer.match_any(self._templates)
        except Exception:
            return
        if not hits:
            return
        # 命中模板 → 关联任务集合（一个任务绑多信号时只发一次）
        fired: dict[str, list[str]] = {}
        for name, _match in hits:
            for task_name in self._tpl_tasks.get(name, []) or []:
                fired.setdefault(task_name, []).append(name)
        for task_name, tpls in fired.items():
            self._bus.publish(
                Events.TRIGGER_DETECTED,
                source="trigger_watcher",
                task_name=task_name,
                templates=tpls,
            )
