"""
通用模块：领取奖励。

检测奖励界面并自动领取。
"""
from __future__ import annotations

import time

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class ClaimReward(TaskStep):
    """领取奖励"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        # 检测奖励界面
        # 点击 "领取" / "确定" 等按钮
        # 实际需要图像识别定位按钮

        click_delay = self.params.get("click_delay", 1.0)
        max_clicks = self.params.get("max_clicks", 5)

        for _ in range(max_clicks):
            if self.check_interrupt(context):
                return StepResult(status=StepStatus.SKIP, message="被中断")
            # 查找并点击领取按钮
            # match = recognizer.find_one("btn_claim")
            # if not match: break
            # executor.click_position(match.center_x, match.center_y)
            time.sleep(click_delay)

        return StepResult(
            status=StepStatus.SUCCESS,
            message="奖励领取完成",
        )
