"""
04-任务执行引擎

BaseTask 任务基类（所有任务入口）。
设计书要求位置：tasks/base/base_task.py
"""
from __future__ import annotations

import time
import traceback
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from core.event_bus import get_global_bus
from core.events import Events
from core.exceptions import TaskError, TaskInterrupted, TaskSkip, TaskTimeout
from tasks.base.task_result import TaskResult, TaskStatus

if TYPE_CHECKING:
    from tasks.base.task_graph import TaskGraph


class BaseTask(ABC):
    """所有任务的基类（§5.3 方法定义）"""

    # 子类应重写
    task_id: str = ""
    category: str = "common"

    def __init__(self, task_id: str, **kwargs: Any):
        self.task_id = task_id
        self.params = kwargs
        self._event_bus = get_global_bus()
        self._bus = self._event_bus  # 兼容别名
        self._start_time: float = 0.0
        self._interrupted = False
        self._context: Any = None  # TaskContext，由 run() 注入

    # ── 子类覆写点 ───────────────────────────────────────────

    @abstractmethod
    def _build_graph(self) -> TaskGraph:
        """
        子类重写，声明步骤图（§5.3）。
        返回 TaskGraph 实例，包含步骤和边定义。
        """
        ...

    # ── 任务元信息 ───────────────────────────────────────────

    @property
    def name(self) -> str:
        """任务标识名（§5.3 name()）"""
        return getattr(self.__class__, 'task_id', '') or self.__class__.__name__

    @property
    def display_name(self) -> str:
        """显示名（§5.3 display_name()），子类可重写"""
        return self.name

    # ── 生命周期 ─────────────────────────────────────────────

    def execute(self, context: Any = None) -> TaskResult:
        """
        执行整个任务（§5.3 默认实现）。
        内部调用 _build_graph().run(context)。
        子类可重写此方法以使用自定义执行逻辑。
        """
        graph = self._build_graph()
        return graph.run(context)

    def run(self, context: Any = None) -> TaskResult:
        """
        运行任务（封装了事件发布和异常处理）。

        Args:
            context: TaskContext 对象，包含 executor/recognizer/stop_event 等
        """
        self._context = context
        self._start_time = time.time()
        self._interrupted = False

        self._bus.publish(
            Events.TASK_STARTED,
            source="base_task",
            task_id=self.task_id,
            task_name=self.__class__.__name__,
        )

        try:
            result = self.execute(context)
            result.task_id = self.task_id
            result.duration = time.time() - self._start_time

            if result.success:
                self._bus.publish(
                    Events.TASK_COMPLETED,
                    source="base_task",
                    task_id=self.task_id,
                    duration=result.duration,
                )
            else:
                self._bus.publish(
                    Events.TASK_FAILED,
                    source="base_task",
                    task_id=self.task_id,
                    error=result.reason,
                )

            return result

        except TaskSkip as e:
            duration = time.time() - self._start_time
            self._bus.publish(
                Events.TASK_SKIPPED,
                source="base_task",
                task_id=self.task_id,
                reason=str(e),
            )
            return TaskResult(
                task_id=self.task_id,
                status=TaskStatus.SUCCESS,
                reason=f"跳过: {e}",
                duration=duration,
            )

        except TaskTimeout as e:
            duration = time.time() - self._start_time
            self._bus.publish(
                Events.TASK_TIMEOUT,
                source="base_task",
                task_id=self.task_id,
                error=str(e),
            )
            return TaskResult(
                task_id=self.task_id,
                status=TaskStatus.TIMEOUT,
                reason=f"超时: {e}",
                duration=duration,
            )

        except TaskInterrupted as e:
            duration = time.time() - self._start_time
            self._bus.publish(
                Events.TASK_INTERRUPTED,
                source="base_task",
                task_id=self.task_id,
            )
            return TaskResult(
                task_id=self.task_id,
                status=TaskStatus.ABORTED,
                reason=f"中断: {e}",
                duration=duration,
            )

        except Exception as e:
            duration = time.time() - self._start_time
            self._bus.publish(
                Events.TASK_FAILED,
                source="base_task",
                task_id=self.task_id,
                error=str(e),
            )
            return TaskResult(
                task_id=self.task_id,
                status=TaskStatus.FAIL,
                reason=str(e),
                duration=duration,
                data={"traceback": traceback.format_exc()},
            )

    # ── 工具 ──────────────────────────────────────────────────

    def log_progress(self, progress: float, message: str = "") -> None:
        """发布进度事件"""
        self._bus.publish(
            Events.TASK_PROGRESS,
            task_id=self.task_id,
            progress=progress,
            message=message,
        )

    def interrupt(self) -> None:
        """请求中断任务"""
        self._interrupted = True

    def check_interrupted(self) -> None:
        """检查是否被中断（在耗时操作中调用）"""
        if self._interrupted:
            raise TaskInterrupted("任务被中断")

    @property
    def elapsed(self) -> float:
        """已运行时间"""
        if self._start_time:
            return time.time() - self._start_time
        return 0.0

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(id={self.task_id})"
