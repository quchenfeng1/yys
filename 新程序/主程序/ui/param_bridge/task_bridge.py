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

    def get_task_metas(self) -> list[dict[str, Any]]:
        """获取任务文件元数据列表（含 uses_* 声明，设计书 §4.3，供 UI 动态表单）"""
        metas: list[dict[str, Any]] = []
        if self._file_mgr and hasattr(self._file_mgr, 'get_all_tasks'):
            for m in self._file_mgr.get_all_tasks():
                metas.append({
                    "name": m.name,
                    "display_name": m.display_name,
                    "description": m.description,
                    "category": m.category,
                    "task_type": getattr(m, 'task_type', 'event_task'),
                    "uses_battle": getattr(m, 'uses_battle', False),
                    "uses_team": getattr(m, 'uses_team', False),
                    "uses_soul": getattr(m, 'uses_soul', False),
                    "uses_stamina": getattr(m, 'uses_stamina', False),
                    "loop_count": getattr(m, 'loop_count', 1),
                    "timeout": getattr(m, 'timeout', 300),
                })
        return metas

    def get_generic_modules(self) -> list[dict[str, Any]]:
        """获取通用模块元数据列表（category=common，供 UI「通用任务」菜单展示/微调）。

        通用模块不单独执行，被其他游戏任务引用为其一部分。
        """
        metas: list[dict[str, Any]] = []
        if self._file_mgr and hasattr(self._file_mgr, 'get_generic_modules'):
            for m in self._file_mgr.get_generic_modules():
                metas.append({
                    "name": m.name,
                    "display_name": m.display_name,
                    "description": m.description,
                    "category": m.category,
                    "task_type": getattr(m, 'task_type', 'event_task'),
                    "uses_battle": getattr(m, 'uses_battle', False),
                    "uses_team": getattr(m, 'uses_team', False),
                    "uses_soul": getattr(m, 'uses_soul', False),
                    "uses_stamina": getattr(m, 'uses_stamina', False),
                    "loop_count": getattr(m, 'loop_count', 1),
                    "timeout": getattr(m, 'timeout', 300),
                    "is_generic": True,
                })
        return metas

    def get_task_detail(self, name: str) -> dict[str, Any]:
        """
        获取单个任务详情（§5.3 + 设计书 §4.3）。

        合并：模块声明（uses_*，来自 TaskManager） + tasks.yaml 配置（调度字段）。
        """
        detail: dict[str, Any] = {"name": name}

        # ① 模块声明（TaskManager 解析的 TaskMeta）
        if self._file_mgr and hasattr(self._file_mgr, 'get_meta'):
            meta = self._file_mgr.get_meta(name)
            if meta:
                detail.update({
                    "display_name": meta.display_name,
                    "description": meta.description,
                    "category": meta.category,
                    "task_type": getattr(meta, 'task_type', 'event_task'),
                    "uses_battle": getattr(meta, 'uses_battle', False),
                    "uses_team": getattr(meta, 'uses_team', False),
                    "uses_soul": getattr(meta, 'uses_soul', False),
                    "uses_stamina": getattr(meta, 'uses_stamina', False),
                    "loop_count": getattr(meta, 'loop_count', 1),
                    "timeout": getattr(meta, 'timeout', 300),
                })

        # ② tasks.yaml 配置（调度字段，设计书 §5.1）
        if self._config and hasattr(self._config, 'get_task_config'):
            cfg = self._config.get_task_config(name)
            if cfg:
                detail.update({k: v for k, v in cfg.items() if k not in ("name", "id")})

        # ③ 调度器运行时状态（下次执行时间，设计书 §5.3）
        if self._scheduler and hasattr(self._scheduler, 'get_next_run_time'):
            nrt = self._scheduler.get_next_run_time(name)
            if nrt:
                detail["next_run_time"] = nrt.strftime("%Y-%m-%d %H:%M")

        if "display_name" not in detail:
            detail["display_name"] = name
        return detail

    def save_task_config(self, name: str, config: dict[str, Any]) -> None:
        """保存任务完整配置到 tasks.yaml（§5.3 + 设计书 §5.1，表单保存）"""
        if not self._config:
            return
        if hasattr(self._config, 'update_task'):
            self._config.update_task(name, **config)
        else:
            # 回退：逐 key 写入
            for k, v in config.items():
                self._config.set(f"tasks.{name}.{k}", v, source="TaskBridge.save")

    # ── §5.2 任务图片配置（逻辑名 → 素材路径）──────────────

    def get_task_asset_refs(self, name: str) -> list[dict[str, Any]]:
        """
        获取任务图片引用清单（代码扫描 + tasks.yaml images 映射合并）。

        返回 [{ref, mapped}]：ref=任务代码引用的素材名（逻辑名），
        mapped=images 配置中映射的素材路径（未配置为 None）。
        """
        refs: list[str] = []
        if self._file_mgr and hasattr(self._file_mgr, 'get_task_asset_refs'):
            try:
                refs = self._file_mgr.get_task_asset_refs(name)
            except Exception:
                refs = []
        images: dict = {}
        if self._config and hasattr(self._config, 'get_task_config'):
            try:
                cfg = self._config.get_task_config(name)
                if cfg:
                    images = cfg.get("images") or {}
            except Exception:
                images = {}
        out = []
        for ref in refs:
            out.append({"ref": ref, "mapped": images.get(ref)})
        return out

    def save_task_images(self, name: str, images: dict[str, Any]) -> None:
        """保存任务图片映射到 tasks.yaml 的 images 字段（§5.2）"""
        if not self._config:
            return
        if hasattr(self._config, 'update_task'):
            self._config.update_task(name, images=images)
        elif self._config:
            self._config.set(f"tasks.{name}.images", images, source="TaskBridge")

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
        if self._config and hasattr(self._config, 'update_task'):
            self._config.update_task(name, priority=value)
        elif self._config:
            self._config.set(f"tasks.{name}.priority", value, source="TaskBridge")

    def update_repeat(self, name: str, rule: dict[str, Any]) -> None:
        """修改任务执行规则（§5.3）"""
        if self._config and hasattr(self._config, 'update_task'):
            self._config.update_task(name, repeat=rule)
        elif self._config:
            self._config.set(f"tasks.{name}.repeat", rule, source="TaskBridge")

    def update_next_run(self, name: str, next_time: Any) -> None:
        """手动设置 next_run_time（§5.3）"""
        if self._scheduler and hasattr(self._scheduler, 'update_next_run'):
            self._scheduler.update_next_run(name, next_time)

    def get_next_run_time(self, name: str) -> str | None:
        """查询任务下次执行时间（格式化字符串，供 UI 显示）"""
        if self._scheduler and hasattr(self._scheduler, 'get_next_run_time'):
            nrt = self._scheduler.get_next_run_time(name)
            if nrt:
                return nrt.strftime("%Y-%m-%d %H:%M")
        return None

    def get_cycle_progress(self, name: str) -> tuple[int, int | None]:
        """查询任务活动循环进度：(已累计循环次数, 活动循环次数上限)。

        供 UI「活动循环次数」旁显示「已循环 x/y 轮」。
        """
        if self._scheduler and hasattr(self._scheduler, 'get_cycle_progress'):
            try:
                return self._scheduler.get_cycle_progress(name)
            except Exception:
                pass
        return 0, None

    def reload_scheduler(self, task_name: str | None = None) -> None:
        """热重载任务配置（保存后立即生效）

        Args:
            task_name: 本次被保存/修改的任务名。传入后仅对该任务执行
                提前评估（窗口内且今日未执行 → 提前到当前时刻）。
        """
        if self._scheduler and hasattr(self._scheduler, 'reload_from_config'):
            self._scheduler.reload_from_config(changed_task=task_name)

    def get_upcoming(self) -> list[dict[str, Any]]:
        """未开始任务列表（供 UI 队列面板「未开始」区域）"""
        if self._scheduler and hasattr(self._scheduler, 'get_upcoming'):
            return self._scheduler.get_upcoming()
        return []

    def get_due_tasks(self) -> list[dict[str, Any]]:
        """待执行任务列表（due，供 UI 队列面板「待执行」区域）"""
        if self._scheduler and hasattr(self._scheduler, 'get_due_tasks'):
            return self._scheduler.get_due_tasks()
        return []

    def get_invalid_tasks(self) -> list[dict[str, Any]]:
        """
        已失效任务列表（供 UI 队列面板「已失效」区域）。

        构成：
          - 已过期：Scheduler 判定的永久完成/活动期结束/次数用尽/到期
          - 待配置：任务库（tasks/ 下 .py）存在但未在 tasks.yaml 配置，
                    或配置了但被禁用（enabled=False）
        """
        result: list[dict[str, Any]] = []

        # ① 已过期（Scheduler 判定）
        if self._scheduler and hasattr(self._scheduler, 'get_invalid_tasks'):
            result.extend(self._scheduler.get_invalid_tasks())

        # ② 待配置：任务库有但未配置 / 配置了但禁用
        configured: set[str] = set()
        if self._scheduler and hasattr(self._scheduler, 'get_all_tasks'):
            configured = {c.name for c in self._scheduler.get_all_tasks()}

        disabled: set[str] = set()
        if self._config and hasattr(self._config, 'tasks_config'):
            try:
                tc = self._config.tasks_config
                tasks_list = getattr(tc, 'tasks', []) if hasattr(tc, 'tasks') else (tc or [])
                for t in tasks_list:
                    en = getattr(t, 'enabled', True)
                    nm = getattr(t, 'name', '') or getattr(t, 'id', '')
                    if nm and not en:
                        disabled.add(nm)
            except Exception:
                pass

        lib_names: set[str] = set()
        if self._mgr and hasattr(self._mgr, 'get_all_tasks'):
            lib_names = {getattr(m, 'name', '') for m in self._mgr.get_all_tasks()}
        elif self._file_mgr and hasattr(self._file_mgr, 'get_all_tasks'):
            lib_names = {getattr(m, 'name', '') for m in self._file_mgr.get_all_tasks()}

        already = {d.get("name") for d in result}
        pending = (lib_names - configured) | disabled
        for nm in sorted(pending):
            if nm in already:
                continue
            if nm in disabled:
                result.append({"name": nm, "status": "待配置", "detail": "任务已停用"})
            else:
                result.append({"name": nm, "status": "待配置", "detail": "尚未配置执行规则"})
        return result

    def batch_update(self, names: list[str], key: str, value: Any) -> list[str]:
        """
        批量修改多个任务的同一参数（§4.4 + §5.3）。

        逐条执行，失败记录跳过继续，返回失败列表。
        """
        failed: list[str] = []
        for name in names:
            try:
                if self._config and hasattr(self._config, 'update_task'):
                    self._config.update_task(name, **{key: value})
                elif self._config:
                    config_path = f"tasks.{name}.{key}"
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

    def new_task(self, category: str, name: str, display: str = "",
                 task_type: str = "event_task") -> str:
        """新建任务骨架文件（§5.3）。task_type: event_task/battle/generic/trigger"""
        if self._file_mgr and hasattr(self._file_mgr, 'new_task'):
            return self._file_mgr.new_task(category, name, display, task_type=task_type)
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
        if self._config and hasattr(self._config, 'update_task'):
            self._config.update_task(task_id, enabled=enabled)
            return True
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
