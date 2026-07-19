"""
错误恢复（通用模块）

任意步骤失败时的恢复路径：返回大厅 → 标记任务跳过。
全项目所有任务复用。
"""

display_name = "错误恢复"
description = "步骤失败时的恢复路径：反复返回直到庭院→标记任务跳过"

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class ErrorReturn(TaskStep):
    """错误恢复：返回大厅，标记任务跳过。"""
    name = "error_return"
    is_generic = True
    timeout = 30

    def execute(self, context: TaskContext) -> StepResult:
        executor = context.executor
        # 点返回直到回到庭院
        for _ in range(8):
            if executor.recognizer.exists("scenes/courtyard/main", threshold=0.7):
                break
            executor.click_if_exists("common/ui/back_btn")
            executor.random_sleep(0.5, 1.0)

        return StepResult.skip(f"任务 {context.task_name} 因错误跳过")
