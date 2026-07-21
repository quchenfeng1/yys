"""
通用模块 — CoopJoin（组队成员）

职责：
  小号接收邀请 → 加入队伍 → 准备就绪

使用场景：
  需要组队的战斗副本（小号侧），如御魂组队、觉醒组队

执行流程：
  ① 等待邀请 → ② 接受邀请 → ③ 加入队伍 → ④ 准备
"""

from __future__ import annotations
from typing import Optional
from tasks.base.task_step import TaskStep, StepResult, TaskContext


class CoopJoin(TaskStep):
    """组队成员：接收邀请、加入队伍、准备就绪"""

    def __init__(self, timeout: int = 30):
        super().__init__()
        self._timeout = timeout

    def execute(self, ctx: TaskContext) -> StepResult:
        ctx.log("开始组队（成员）")

        # 1. 等待邀请弹窗
        invite = ctx.executor.wait_any(
            ["common/team/invite_popup", "common/team/team_invite"],
            timeout=self._timeout
        )
        if not invite:
            return StepResult.fail("未收到组队邀请")

        # 2. 接受邀请
        if not ctx.executor.click_image("common/team/accept_invite"):
            return StepResult.fail("无法接受邀请")

        # 3. 等待加入队伍
        if not ctx.executor.ensure_scene("team/waiting", timeout=10):
            return StepResult.fail("加入队伍失败")

        # 4. 点击准备
        ctx.executor.click_image("common/team/ready_btn")
        return StepResult.success("已加入队伍")
