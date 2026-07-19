"""
TaskStep 任务步骤基类（04-任务模块）

所有任务步骤（特化模块和通用模块）都继承此类。
实现 execute(context) → StepResult，TaskGraph 据此决定下一步。

对应解耦文档：模块说明/04-任务模块.md
"""

from dataclasses import dataclass, field
from typing import Optional

from tasks.base.task_context import TaskContext


@dataclass
class StepResult:
    """步骤执行结果。TaskGraph 据此决定下一步。"""

    status: str                              # "success" / "fail" / "skip" / "retry"
    next_step: Optional[str] = None          # 显式指定下一步（用于条件分支）
    data: dict = field(default_factory=dict) # 输出数据（传给后续步骤）
    message: str = ""                        # 日志消息

    @classmethod
    def success(cls, message: str = "", **data) -> "StepResult":
        return cls(status="success", message=message, data=data)

    @classmethod
    def fail(cls, message: str = "", **data) -> "StepResult":
        return cls(status="fail", message=message, data=data)

    @classmethod
    def skip(cls, message: str = "", **data) -> "StepResult":
        return cls(status="skip", message=message, data=data)

    @classmethod
    def retry(cls, message: str = "", **data) -> "StepResult":
        return cls(status="retry", message=message, data=data)


class TaskStep:
    """任务步骤基类。

    特化模块（副本独有操作）和通用模块（全项目复用）都继承此类。

    类属性：
        name: str         — 步骤名（调试用）
        is_generic: bool  — 是否通用模块（True=可复用）
        timeout: float    — 超时秒数，0 表示无限制
    """

    name: str = ""
    is_generic: bool = False
    timeout: float = 60  # 默认 60 秒超时

    def execute(self, context: TaskContext) -> StepResult:
        """执行步骤。子类实现此方法。

        Args:
            context: 步骤间共享上下文

        Returns:
            StepResult，TaskGraph 据此决定下一步。
        """
        raise NotImplementedError(f"{self.__class__.__name__} 必须实现 execute()")

    def __repr__(self):
        t = "通用" if self.is_generic else "特化"
        return f"{self.__class__.__name__}({t}, timeout={self.timeout}s)"
