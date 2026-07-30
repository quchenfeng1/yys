"""
04-任务执行引擎

TaskStep 步骤基类。
步骤是任务的基本执行单元。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from tasks.base.task_result import StepResult, StepStatus


class TaskStep(ABC):
    """步骤基类（§5.3 方法定义）"""

    def __init__(
        self,
        step_id: str,
        is_generic: bool = False,
        retry_count: int = 0,
        timeout: float = 120.0,
        **kwargs: Any,
    ):
        self.step_id = step_id
        self.is_generic = is_generic  # §2.3 是否通用模块
        self.retry_count = retry_count  # §2.3 失败重试次数
        self.timeout = timeout  # §2.3 单步超时秒数
        self.params = kwargs
        self._start_time: float = 0.0

    @abstractmethod
    def execute(self, context: Any = None) -> StepResult:
        """执行步骤（子类实现）"""
        ...

    def cleanup(self, context: Any = None) -> None:
        """步骤失败时的清理回调（可选重写）"""
        pass

    def run(self, context: Any = None) -> StepResult:
        """运行步骤（封装计时）"""
        self._start_time = time.time()
        try:
            result = self.execute(context)
            result.step_id = self.step_id
            result.duration = time.time() - self._start_time
            return result
        except Exception as e:
            return StepResult(
                step_id=self.step_id,
                status=StepStatus.FAIL,
                message=str(e),
                duration=time.time() - self._start_time,
            )

    def check_interrupt(self, context: Any) -> bool:
        """步骤内部检查停止信号（长循环步骤使用，§5.3）"""
        if context and hasattr(context, 'stop_event') and context.stop_event:
            if context.stop_event.is_set():
                return True
        return False

    @property
    def elapsed(self) -> float:
        if self._start_time:
            return time.time() - self._start_time
        return 0.0

    def __str__(self) -> str:
        return f"Step({self.step_id})"
