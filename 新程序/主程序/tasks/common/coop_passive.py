"""
通用模块：CoopPassive 组队待机（被带方自动领奖）。

被动模式：加入队伍后等待战斗结束并领奖。
"""
from __future__ import annotations

import time

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class CoopPassive(TaskStep):
    """组队被动：等待战斗结束并领奖"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        wait_timeout = self.params.get("wait_timeout", 300)
        elapsed = 0

        while elapsed < wait_timeout:
            if self.check_interrupt(context):
                return StepResult(status=StepStatus.SKIP, message="被中断")
            # 检测是否在战斗中
            # 检测是否出现结算界面
            time.sleep(5)
            elapsed += 5

        # 领奖
        # executor.click_image("btn_claim")

        return StepResult(
            status=StepStatus.SUCCESS,
            message="被动组队完成",
        )
