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

    def set_controller(self, controller: Any) -> None:
        """注入 RunController 实例（供 UI 查询当前任务/队列）"""
        self._ctrl = controller

    def get_current_task(self) -> str | None:
        """当前正在执行的任务名"""
        if self._ctrl:
            return getattr(self._ctrl, 'current_task', None)
        return None

    def get_queue_snapshot(self) -> list[str]:
        """待执行队列内容"""
        if self._ctrl and hasattr(self._ctrl, 'queue_snapshot'):
            try:
                return list(self._ctrl.queue_snapshot)
            except Exception:
                pass
        return []

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

    # ── §3.7 沙盒模式 / 自检 ──────────────────────────────

    def set_dry_mode(self, enabled: bool) -> None:
        """切换沙盒模式（干运行：只走流程不实际点击）。

        优先直接调 RunController.set_dry_mode()（§3.7），
        无 controller 时回退发布 RUN_STARTED 事件（兼容旧路径）。
        """
        if self._ctrl and hasattr(self._ctrl, 'set_dry_mode'):
            try:
                self._ctrl.set_dry_mode(bool(enabled))
                return
            except Exception:
                pass
        self._bus.publish(Events.RUN_STARTED, source="RunBridge",
                          dry_run=bool(enabled))

    def run_self_check(self) -> dict[str, Any]:
        """运行环境自检（ADB/素材/配置/依赖，§3.7 自检按钮）。

        通过 RunController 的 connection / config / registry 快速检查，
        返回 {检查项: 结果} 字典。无 controller 时返回空。
        """
        result: dict[str, Any] = {
            "config_valid": True,
            "adb_connectivity": False,
            "assets_complete": True,
            "dependencies_complete": True,
        }
        ctrl = self._ctrl
        if ctrl is None:
            return result

        # 配置
        cfg = getattr(ctrl, 'config', None)
        if cfg is not None and hasattr(cfg, 'validate'):
            try:
                errors = cfg.validate()
                if errors:
                    result["config_valid"] = False
                    result["config_errors"] = errors
            except Exception:
                result["config_valid"] = False

        # ADB 连通性
        conn = getattr(ctrl, 'connection', None)
        if conn is not None and hasattr(conn, 'is_connected'):
            try:
                result["adb_connectivity"] = conn.is_connected()
            except Exception:
                pass

        # 素材完整性
        reg = getattr(ctrl, 'registry', None)
        if reg is not None and hasattr(reg, 'get_all'):
            try:
                tasks = reg.get_all()
                missing = [
                    getattr(t, 'task_id', '') or getattr(t, 'name', '')
                    for t in tasks
                    if not getattr(t, 'has_assets', True)
                ]
                if missing:
                    result["assets_complete"] = False
                    result["missing_assets"] = missing
            except Exception:
                pass

        # 依赖
        required = ["scheduler", "executor", "recognizer", "connection"]
        missing = [n for n in required if getattr(ctrl, n, None) is None]
        if missing:
            result["dependencies_complete"] = False
            result["missing_dependencies"] = missing

        return result
