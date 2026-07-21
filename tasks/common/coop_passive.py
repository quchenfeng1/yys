"""
通用模块 — CoopPassive（组队待机）

职责：
  加入队伍后不操作，等待战斗结束自动领奖

使用场景：
  模式B（小号开车/带人）：主号作为被带的一方，只需接受邀请进入队伍
  然后等待战斗自动完成，领奖即可

执行流程：
  ① 接受邀请 → ② 加入队伍 → ③ 等待战斗结束 → ④ 领奖
"""

from __future__ import annotations
from tasks.base.task_step import TaskStep, StepResult, TaskContext


class CoopPassive(TaskStep):
    """组队待机：加入队伍后等待战斗结束自动领奖"""

    def __init__(self, timeout: int = 120):
        super().__init__()
        self._timeout = timeout

    def execute(self, ctx: TaskContext) -> StepResult:
        ctx.log("组队待机模式：等待战斗结束")

        # 1. 等待组队邀请
        invite = ctx.executor.wait_any(
            ["common/team/invite_popup", "common/team/team_invite"],
            timeout=30
        )
        if not invite:
            return StepResult.fail("未收到组队邀请")

        # 2. 接受邀请
        if not ctx.executor.click_image("common/team/accept_invite"):
            return StepResult.fail("无法接受邀请")

        # 3. 等待在队伍中（不点准备，由队长控制）
        if not ctx.executor.ensure_scene("team/waiting", timeout=10):
            return StepResult.fail("加入队伍失败")

        # 4. 等待战斗自动结束（队长控制开始/循环）
        if not ctx.executor.wait("common/battle/result_victory", timeout=self._timeout):
            return StepResult.fail("战斗等待超时")

        # 5. 领奖
        ctx.executor.click_image("common/reward/confirm")
        return StepResult.success("组队待机完成")
