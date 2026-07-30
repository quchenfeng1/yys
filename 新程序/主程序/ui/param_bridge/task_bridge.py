"""
10-参数桥接模块

任务参数传参（§5.3 TaskBridge）。
桥接 TaskRegistry / Scheduler / TaskManager 与 UI。
"""
from __future__ import annotations

from typing import Any, Optional

from core.event_bus import EventBus, get_global_bus
from core.events import Events


class TaskBridge:
    """任务参数桥接（§5.3）"""

    def __init__(
        self,
        registry: Any = None,
        scheduler: Any = None,
        task_manager: Any = None,
        config: Any = None,
        file_manager: Any = None,
        event_bus: EventBus | None = None,
    ):
        self._registry = registry       # TaskRegistry
        self._scheduler = scheduler     # Scheduler
        self._mgr = task_manager        # TaskManager（兼容旧构造）
        self._config = config           # ConfigManager
        self._file_mgr = file_manager   # 13-任务文件管理
        self._bus = event_bus or get_global_bus()

    # ── §5.3 任务查询 ─────────────────────────────────────

    def get_task_list(self) -> list[str]:
        """获取所有已注册任务名列表（§5.3）"""
        names: list[str] = []
        if self._registry and hasattr(self._registry, 'get_all'):
            tasks = self._registry.get_all()
            names = [
                getattr(t, 'task_id', '') or getattr(t, 'name', str(t))
                for t in tasks
            ]
        elif self._mgr and hasattr(self._mgr, 'list_tasks'):
            names = [t.name for t in self._mgr.list_tasks()]
        return names

    def get_task_detail(self, name: str) -> dict[str, Any]:
        """获取单个任务详情（§5.3）"""
        if self._registry:
            try:
                task = self._registry.get(name)
                return {
                    "name": task.task_id,
                    "class": task.__class__.__name__,
                    "params": getattr(task, 'params', {}),
                }
            except Exception:
                pass
        if self._config:
            config = self._config.get_task_config(name)
            if config:
                return config
        return {"name": name, "error": "未找到"}

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """获取任务依赖图（§5.3）"""
        if self._registry and hasattr(self._registry, 'get_dependency_graph'):
            return self._registry.get_dependency_graph()
        return {}

    def list_by_category(self, cat: str) -> list[dict[str, Any]]:
        """按分类获取任务列表（§5.3）"""
        if self._registry and hasattr(self._registry, 'list_by_category'):
            tasks = self._registry.list_by_category(cat)
            return [
                {
                    "name": getattr(t, 'task_id', '') or getattr(t, 'name', str(t)),
                }
                for t in tasks
            ]
        return []

    # ── §5.3 任务修改 ─────────────────────────────────────

    def update_priority(self, name: str, value: int) -> None:
        """修改任务优先级（§5.3）"""
        if self._config:
            self._config.set(f"tasks.{name}.priority", value, source="TaskBridge")

    def update_repeat(self, name: str, rule: dict[str, Any]) -> None:
        """修改任务执行规则（§5.3）"""
        if self._config:
            self._config.set(f"tasks.{name}.repeat", rule, source="TaskBridge")

    def update_next_run(self, name: str, next_time: Any) -> None:
        """手动设置 next_run_time（§5.3）"""
        if self._scheduler and hasattr(self._scheduler, 'update_next_run'):
            self._scheduler.update_next_run(name, next_time)

    def batch_update(self, names: list[str], key: str, value: Any) -> list[str]:
        """
        批量修改多个任务的同一参数（§4.4 + §5.3）。

        逐条执行，失败记录跳过继续，返回失败列表。
        """
        failed: list[str] = []
        for name in names:
            try:
                config_path = f"tasks.{name}.{key}"
                if self._config:
                    self._config.set(config_path, value, source="TaskBridge.batch")
            except Exception:
                failed.append(name)
        return failed

    def import_calendar(self, events: list[dict]) -> tuple[int, int]:
        """导入活动日历（§5.3）"""
        if self._scheduler and hasattr(self._scheduler, 'import_calendar'):
            return self._scheduler.import_calendar(events)
        return (0, 0)

    def reset_fail_streak(self, name: str) -> None:
        """重置失败计数（§5.3）"""
        if self._scheduler and hasattr(self._scheduler, 'reset_fail_streak'):
            self._scheduler.reset_fail_streak(name)

    # ── §5.3 任务文件管理 ─────────────────────────────────

    def new_task(self, category: str, name: str, display: str = "") -> str:
        """新建任务骨架文件（§5.3）"""
        if self._file_mgr and hasattr(self._file_mgr, 'new_task'):
            return self._file_mgr.new_task(category, name, display)
        return ""

    def delete_task(self, task_name: str) -> None:
        """安全删除任务（§5.3）"""
        if self._file_mgr and hasattr(self._file_mgr, 'delete_task'):
            self._file_mgr.delete_task(task_name)

    def open_file(self, task_name: str) -> None:
        """用默认编辑器打开任务文件（§5.3）"""
        if self._file_mgr and hasattr(self._file_mgr, 'open_file'):
            self._file_mgr.open_file(task_name)

    # ── 兼容旧方法 ───────────────────────────────────────

    def get_task_params(self, task_id: str) -> dict[str, Any]:
        if self._mgr and hasattr(self._mgr, 'get_task'):
            task = self._mgr.get_task(task_id)
            return {
                "task_id": task.id,
                "priority": task.priority,
                "max_retries": task.max_retries,
                "timeout": task.timeout,
                "interval": task.interval,
                "params": task.params,
            }
        detail = self.get_task_detail(task_id)
        return detail

    def enable_task(self, task_id: str, enabled: bool) -> bool:
        if self._config:
            self._config.set(f"tasks.{task_id}.enabled", enabled, source="TaskBridge")
            return True
        return False

    def get_active_activities(self) -> list[dict[str, Any]]:
        if self._mgr and hasattr(self._mgr, 'get_active_activities'):
            return [
                {"id": a.activity_id, "name": a.name, "tasks": a.tasks}
                for a in self._mgr.get_active_activities()
            ]
        return []
