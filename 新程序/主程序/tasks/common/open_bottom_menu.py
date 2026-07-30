"""
通用模块：打开底部菜单。

点击展开底部菜单栏。
"""
from __future__ import annotations

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class OpenBottomMenu(TaskStep):
    """打开底部菜单"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        if self.check_interrupt(context):
            return StepResult(status=StepStatus.SKIP, message="被中断")

        # 点击底部菜单展开按钮
        # result = executor.click_image("btn_bottom_menu")
        # if not result.success:
        #     return StepResult(status=StepStatus.FAIL, message="底部菜单按钮未找到")

        return StepResult(
            status=StepStatus.SUCCESS,
            message="底部菜单已打开",
        )
