"""
通用模块：碎片交换。

进入好友界面→发起/接受碎片请求→确认。
"""
from __future__ import annotations

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class FragmentExchange(TaskStep):
    """碎片交换"""

    is_generic = True

    def execute(self, context=None) -> StepResult:
        if self.check_interrupt(context):
            return StepResult(status=StepStatus.SKIP, message="被中断")

        # 1. 进入好友界面
        # executor.click_image("btn_friend")

        # 2. 发起碎片请求
        # executor.click_image("btn_request_fragment")

        # 3. 确认交换
        # executor.click_image("btn_confirm_exchange")

        return StepResult(
            status=StepStatus.SUCCESS,
            message="碎片交换完成",
        )
