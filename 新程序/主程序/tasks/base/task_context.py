"""
04-任务执行引擎

TaskContext 上下文（§5.2）。
在任务执行过程中传递状态和数据，由运行控制中心构造注入。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TaskContext:
    """任务执行上下文（§5.2 字段定义）"""

    task_id: str = ""
    task_name: str = ""
    task_config: dict[str, Any] = field(default_factory=dict)  # §5.2 任务完整配置
    params: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    parent_context: TaskContext | None = None
    children: list[TaskContext] = field(default_factory=list)

    # 依赖注入（由运行控制中心注入）
    executor: Any = None  # §5.2 14-执行器模块（含安全注入）
    recognizer: Any = None  # §5.2 02-图像识别模块
    stop_event: threading.Event | None = None  # §5.2 停止信号
    cycle_limit_event: threading.Event | None = None  # 活动循环次数达上限信号（per-task：达上限立即中断收尾）
    account_manager: Any = None  # §3.10 15-账号管理模块（组队协调：切换小号/查询组队伙伴）
    # 说明书 04 §BattleLoop：每场战斗结束的进度持久化回调
    # 签名 on_progress(task_id, completed, total)，由 09-运行控制中心 注入
    progress_saver: Any = None

    # 运行时元数据
    attempt: int = 1
    max_retries: int = 3
    timeout: float = 300.0
    dry_run: bool = False

    # 用户自定义数据
    data: dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        """设置上下文数据"""
        self.state[key] = value

    def resolve_asset(self, name: str) -> str:
        """素材别名解析（逻辑名 → 素材路径，§5.2 任务图片配置）。

        任务代码引用逻辑名（如 click_image(逻辑名)），
        若任务配置 images 中配置了 {逻辑名: 素材路径}，返回素材路径；
        否则原样返回（逻辑名即素材名，向后兼容硬编码引用）。
        """
        if not name:
            return name
        try:
            images = (self.task_config or {}).get("images") or {}
            if isinstance(images, dict) and name in images:
                mapped = images[name]
                if mapped:
                    return str(mapped)
        except Exception:
            pass
        return name

    def get(self, key: str, default: Any = None) -> Any:
        """获取上下文数据"""
        if key in self.state:
            return self.state[key]
        if self.parent_context:
            return self.parent_context.get(key, default)
        return default

    def create_child(self, task_id: str) -> TaskContext:
        """创建子上下文"""
        child = TaskContext(
            task_id=task_id,
            parent_context=self,
            max_retries=self.max_retries,
            timeout=self.timeout,
            dry_run=self.dry_run,
        )
        self.children.append(child)
        return child

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "params": self.params,
            "state": self.state,
            "attempt": self.attempt,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
        }
