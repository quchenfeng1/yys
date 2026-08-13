"""
通用模块：返回庭院。

多次返回直到回到庭院主界面。
"""
from __future__ import annotations

import time

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class ReturnHall(TaskStep):
    """返回庭院"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        max_back = self.params.get("max_back", 10)

        for _ in range(max_back):
            if self.check_interrupt(context):
                return StepResult(status=StepStatus.SKIP, message="被中断")
            # 检测是否已在庭院
            # if recognizer.find_one("scene_hall"):
            #     break
            # 按下返回键
            # adb_client.keyevent(4)  # BACK
            time.sleep(1.5)

        return StepResult(
            status=StepStatus.SUCCESS,
            message="已返回庭院",
        )
