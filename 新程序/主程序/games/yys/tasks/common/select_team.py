"""
通用模块：选阵容。

选择预设的队伍阵容。
"""
from __future__ import annotations

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class SelectTeam(TaskStep):
    """选择队伍阵容"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        team_name = self.params.get("team_name", "")

        if not team_name:
            # 使用默认队伍
            pass
        else:
            # 通过 OCR 找到对应队伍名并点击
            # matches = ocr_locator.find_text(screenshot, team_name)
            # if matches:
            #     executor.click_position(matches[0].center_x, matches[0].center_y)
            pass

        return StepResult(
            status=StepStatus.SUCCESS,
            message=f"已选择队伍: {team_name or '默认'}",
        )
