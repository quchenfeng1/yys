"""
战斗循环（通用模块）

等待战斗结束 → 检测胜利/失败 → 结算。
支持循环 N 次，全项目所有战斗副本复用。
"""

display_name = "战斗循环"
description = "等待战斗结束→检测胜利/失败→结算，支持循环N次，全副本复用"

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class BattleLoop(TaskStep):
    """通用战斗循环。可循环 N 次。"""
    name = "battle_loop"
    is_generic = True
    timeout = 300  # 单轮最长 5 分钟

    def __init__(self, times: int = 1):
        super().__init__()
        self.times = times

    def execute(self, context: TaskContext) -> StepResult:
        executor = context.executor

        for i in range(self.times):
            # 等待战斗结束（胜利/失败结算界面出现）
            result = executor.recognizer.wait_any(
                ["common/battle/victory", "common/battle/defeat"],
                timeout=180,  # 单轮战斗最多等 3 分钟
            )
            if result is None:
                return StepResult.fail(f"第{i+1}轮战斗超时")

            scene_name, _ = result

            # 点击结算
            executor.click_if_exists("common/battle/confirm_btn")
            executor.random_sleep(1, 2)

        return StepResult.success(f"完成 {self.times} 轮战斗", rounds=self.times)
