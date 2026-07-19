"""
选阵容（通用模块）

对局内选阵容并锁定。
"""

display_name = "选择阵容"
description = "对局内选择指定阵容并锁定，支持自动确认"

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class SelectTeam(TaskStep):
    """对局内选择阵容并锁定。"""
    name = "select_team"
    is_generic = True
    timeout = 20

    def execute(self, context: TaskContext) -> StepResult:
        team_id = context.task_config.get("team_id")
        lock = context.task_config.get("lock_team_after_select", True)

        tm = context.team_manager
        if tm:
            tm.select_team_in_battle(team_id) if team_id else None
            if lock:
                tm.lock_team()

        return StepResult.success(f"阵容 {team_id or '默认'} 已选择", locked=lock)
