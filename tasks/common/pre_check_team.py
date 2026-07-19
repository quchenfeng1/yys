"""
阵容检查（通用模块）

首次进入战斗前的强制阵容检查。
"""

display_name = "阵容预检"
description = "首次进入战斗前验证阵容是否匹配目标预设"

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class PreCheckTeam(TaskStep):
    """阵容检查：验证当前阵容是否匹配目标预设。"""
    name = "pre_check_team"
    is_generic = True
    timeout = 30

    def execute(self, context: TaskContext) -> StepResult:
        team_id = context.task_config.get("team_id")
        if not team_id:
            return StepResult.success("无需阵容检查")

        tm = context.team_manager
        if tm and tm.ensure_team(team_id):
            return StepResult.success(f"阵容 {team_id} 已就绪")
        return StepResult.fail(f"阵容 {team_id} 调整失败")
