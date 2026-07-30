"""
04-任务执行引擎

TaskResult / StepResult 返回值定义（§5.2）。
设计书要求独立文件 tasks/base/task_result.py。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """任务状态枚举（§5.2 TaskResult.status）"""
    SUCCESS = "success"
    FAIL = "fail"
    TIMEOUT = "timeout"
    ABORTED = "aborted"


class StepStatus(str, Enum):
    """步骤状态枚举（§5.2 StepResult.status）"""
    SUCCESS = "success"
    FAIL = "fail"
    SKIP = "skip"
    RETRY = "retry"


@dataclass
class TaskResult:
    """任务执行结果（§5.2，字段名与设计书一致：reason 而非 message）"""
    task_id: str
    status: TaskStatus = TaskStatus.SUCCESS
    reason: str = ""                    # 设计书字段名
    duration: float = 0.0
    retries: int = 0
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """向后兼容：success=True 等价于 status==SUCCESS"""
        return self.status == TaskStatus.SUCCESS

    @property
    def message(self) -> str:
        """向后兼容：旧代码用 .message 访问"""
        return self.reason


@dataclass
class StepResult:
    """步骤执行结果（§5.2）"""
    step_id: str = ""
    status: StepStatus = StepStatus.SUCCESS
    message: str = ""
    duration: float = 0.0
    retries: int = 0
    next_step: str | None = None  # 显式指定下一步（条件跳转时用）
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """向后兼容：success=True 等价于 status==SUCCESS"""
        return self.status == StepStatus.SUCCESS
