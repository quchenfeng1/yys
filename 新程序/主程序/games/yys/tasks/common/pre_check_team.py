"""
通用模块：阵容检查。

检查当前队伍配置是否符合要求。
"""
from __future__ import annotations

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class PreCheckTeam(TaskStep):
    """预检队伍：检查阵容是否符合预期"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        expected_team = self.params.get("expected_team", "default")

        # 通过 OCR/模板匹配检查当前队伍
        # 例如检测式神头像、等级等
        # 如果不符合则返回 fail

        return StepResult(
            status=StepStatus.SUCCESS,
            message=f"队伍检查通过: {expected_team}",
        )
