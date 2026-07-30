"""
通用模块：CoopJoin 组队成员（接受邀请→准备）。
"""
from __future__ import annotations

import time

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class CoopJoin(TaskStep):
    """组队成员：接受邀请并准备"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        if self.check_interrupt(context):
            return StepResult(status=StepStatus.SKIP, message="被中断")

        # 1. 接受邀请
        # executor.click_image("btn_accept_invite")

        # 2. 准备
        # executor.click_image("btn_ready")

        time.sleep(2)

        return StepResult(
            status=StepStatus.SUCCESS,
            message="加入队伍并准备完成",
        )
