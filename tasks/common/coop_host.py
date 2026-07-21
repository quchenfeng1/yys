"""
通用模块 — CoopHost（组队主机）

职责：
  主号创建队伍 → 邀请小号 → 等待全员就绪 → 开始战斗

使用场景：
  需要组队的战斗副本（主号侧），如御魂组队、觉醒组队

执行流程：
  ① 打开组队界面 → ② 创建队伍 → ③ 等待邀请被接受
  → ④ 全员就绪 → ⑤ 开始战斗
"""

from __future__ import annotations
from typing import Optional
from tasks.base.task_step import TaskStep, StepResult, TaskContext


class CoopHost(TaskStep):
    """组队主机：创建队伍、邀请小号、等待就绪"""

    def __init__(self, timeout: int = 30):
        super().__init__()
        self._timeout = timeout

    def execute(self, ctx: TaskContext) -> StepResult:
        ctx.log("开始组队（主机）")

        # 1. 打开组队界面
        if not ctx.executor.ensure_scene("team/create", timeout=10):
            if not ctx.executor.click_image("common/team/create_btn"):
                return StepResult.fail("无法打开组队界面")

        # 2. 创建队伍
        if not ctx.executor.click_image("common/team/confirm_create"):
            return StepResult.fail("无法创建队伍")

        # 3. 等待邀请完成（09 负责切换小号加入）
        ctx.log("等待小号加入队伍...")
        if not ctx.executor.wait("common/team/member_joined", timeout=self._timeout):
            return StepResult.fail("小号加入超时")

        # 4. 确认全员就绪
        ctx.executor.click_image("common/team/start_battle")
        return StepResult.success("组队完成，战斗开始")
