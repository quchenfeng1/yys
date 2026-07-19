"""
返回庭院（通用模块）

任务收尾步骤：反复点返回/主页键，直到识别到庭院标志。
全项目所有任务复用。
"""

display_name = "返回庭院"
description = "反复点返回/主页键直到识别到庭院标志，任务收尾用"

import time

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class ReturnHall(TaskStep):
    """返回庭院。点返回直到识别到庭院主界面。"""
    name = "return_hall"
    is_generic = True
    timeout = 30

    def execute(self, context: TaskContext) -> StepResult:
        executor = context.executor
        max_attempts = 10

        for i in range(max_attempts):
            # 检测是否已在庭院
            if executor.recognizer.exists("scenes/courtyard/main", threshold=0.7):
                return StepResult.success("已回到庭院", attempts=i + 1)

            # 尝试点返回
            executor.click_if_exists("common/ui/back_btn")
            time.sleep(1)
            executor.click_if_exists("common/ui/home_btn")
            time.sleep(1)

        return StepResult.fail("无法回到庭院")
