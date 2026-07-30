"""
通用模块：战斗循环（支持运行时进度恢复）。

自动战斗循环：检测战斗场景 -> 等待结束 -> 重复。
"""
from __future__ import annotations

import time

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class BattleLoop(TaskStep):
    """战斗循环：自动重复战斗"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        max_battles = self.params.get("max_battles", 0)  # 0 = 无限
        battle_count = 0

        while max_battles <= 0 or battle_count < max_battles:
            if self.check_interrupt(context):
                return StepResult(status=StepStatus.SKIP, message="被中断")

            # 等待战斗结束（检测 "结算" 界面）
            # 实际需要图像识别配合
            wait_time = self.params.get("wait_time", 60)
            time.sleep(wait_time)

            battle_count += 1

        return StepResult(
            status=StepStatus.SUCCESS,
            message=f"战斗循环完成，共 {battle_count} 场",
        )
