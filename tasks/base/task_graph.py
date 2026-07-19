"""
TaskGraph 任务步骤图引擎（04-任务模块）

用有向图描述步骤间关系，支持顺序、条件分支、循环、跳转。
从入口步骤开始，按 StepResult 的 next_step 或默认边遍历。

对应解耦文档：模块说明/04-任务模块.md
"""

from typing import Callable, Optional

from core.event_bus import event_bus, Events
from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class TaskGraph:
    """任务步骤图。用有向图描述步骤间关系。"""

    def __init__(self, task_name: str = ""):
        self.task_name = task_name
        self._steps: dict[str, TaskStep] = {}           # 步骤名 → 步骤实例
        self._edges: dict[str, list[tuple[str, Optional[Callable]]]] = {}  # 步骤名 → [(目标步骤, 条件)]
        self._entry: str = ""                           # 入口步骤名
        self._error_branch: Optional[str] = None         # 全局错误分支

    # ==================== 构建 ====================

    def add_step(self, name: str, step: TaskStep):
        """添加步骤。"""
        self._steps[name] = step

    def add_edge(self, from_step: str, to_step: str, condition: Callable = None):
        """添加边。

        Args:
            from_step: 源步骤名
            to_step: 目标步骤名
            condition: 可选条件函数，接收 StepResult 返回 bool。
                       为 None 时作为默认边。
        """
        if from_step not in self._edges:
            self._edges[from_step] = []
        self._edges[from_step].append((to_step, condition))

    def set_entry(self, name: str):
        """设置入口步骤。"""
        self._entry = name

    def set_error_branch(self, name: str):
        """设置全局错误分支（所有步骤失败时跳转到此）。"""
        self._error_branch = name

    # ==================== 执行 ====================

    def run(self, context: TaskContext) -> bool:
        """执行步骤图。

        从入口步骤开始，按 StepResult.next_step 或默认边遍历。
        任意步骤失败：若有 error 分支则跳转，否则立即终止。

        Returns:
            True 表示全部步骤成功完成（或通过 error 分支优雅退出）。
        """
        current = self._entry
        max_steps = 100  # 防止死循环
        step_count = 0

        while current and step_count < max_steps:
            step_count += 1
            step = self._steps.get(current)
            if not step:
                break

            # 执行步骤
            try:
                result = step.execute(context)
            except Exception as e:
                result = StepResult.fail(message=str(e))

            # 发布步骤完成事件
            event_bus.publish(
                Events.STEP_DONE,
                task_name=self.task_name,
                step_name=current,
                status=result.status,
                message=result.message,
            )

            # 决定下一步
            if result.status == "fail":
                current = self._resolve_error(current)
                if current is None:
                    return False
            elif result.next_step:
                current = result.next_step
            else:
                current = self._get_default_next(current)

        return step_count < max_steps

    # ==================== 内部 ====================

    def _get_default_next(self, from_step: str) -> Optional[str]:
        """获取默认下一条边（无条件或条件为 None）。"""
        edges = self._edges.get(from_step, [])
        for to_step, condition in edges:
            if condition is None:
                return to_step
        # 无条件边时取第一条
        return edges[0][0] if edges else None

    def _resolve_error(self, from_step: str) -> Optional[str]:
        """解析错误分支。"""
        # 先查步骤专属 error 边
        edges = self._edges.get(from_step, [])
        for to_step, condition in edges:
            if to_step == self._error_branch:
                return to_step
        # 再查全局 error 分支
        if self._error_branch:
            return self._error_branch
        return None

    # ==================== 查询 ====================

    def get_step(self, name: str) -> Optional[TaskStep]:
        return self._steps.get(name)

    def list_steps(self) -> list[str]:
        return list(self._steps.keys())

    def validate(self) -> list[str]:
        """校验步骤图完整性。"""
        errors = []
        if not self._entry:
            errors.append("未设置入口步骤 set_entry()")
        if self._entry and self._entry not in self._steps:
            errors.append(f"入口步骤 '{self._entry}' 未定义")
        # 检查可达性（简单检测：除末节点外都应有出边）
        for name in self._steps:
            if name not in self._edges and name != self._error_branch:
                # 没有出边的步骤可能是终节点，不报错
                pass
        return errors
