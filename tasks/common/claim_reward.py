"""
领取奖励（通用模块）
"""

display_name = "领取奖励"
description = "战斗结算后点击确认→关闭弹窗→领取奖励"

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class ClaimReward(TaskStep):
    """领取奖励：点击结算 → 确认 → 关弹窗。"""
    name = "claim_reward"
    is_generic = True
    timeout = 20

    def execute(self, context: TaskContext) -> StepResult:
        executor = context.executor
        executor.click_if_exists("common/battle/confirm_btn")
        executor.random_sleep(1, 1.5)
        executor.click_if_exists("common/ui/close_btn")
        return StepResult.success("奖励已领取")
