"""
通用模块：CoopHost 组队主机（创建队伍→邀请→开战）。
"""
from __future__ import annotations

import time

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class CoopHost(TaskStep):
    """组队队长：创建队伍并开战"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        team_type = self.params.get("team_type", "auto")
        wait_timeout = self.params.get("wait_timeout", 120)

        if self.check_interrupt(context):
            return StepResult(status=StepStatus.SKIP, message="被中断")

        # 1. 创建队伍
        # recognizer.find_one("btn_create_team")
        # executor.click_image("btn_create_team")

        # 2. 等待队员
        time.sleep(min(wait_timeout, 10))  # 占位

        # 3. 开始战斗
        # executor.click_image("btn_start_battle")

        return StepResult(
            status=StepStatus.SUCCESS,
            message=f"组队完成 (模式={team_type})",
        )
