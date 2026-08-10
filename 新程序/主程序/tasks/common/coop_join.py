"""
通用模块：CoopJoin 组队成员（接受邀请→准备）。

在"当前设备"上执行（由 CoopHost 切换到小号模拟器后调用）：
- 接受组队邀请（识别 accept_btn 素材 → 点击）
- 准备就绪（识别 ready_btn 素材 → 点击）

素材名可配置（params），默认约定名 btn_accept_invite / btn_ready。
"""
from __future__ import annotations

import time
from typing import Any

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class CoopJoin(TaskStep):
    """组队成员：接受邀请并准备（当前设备）"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        ex = getattr(context, 'executor', None)
        if ex is None:
            return StepResult.fail("缺少 executor")

        if self.check_interrupt(context):
            return StepResult(status=StepStatus.SKIP, message="被中断")

        accept_btn = self.params.get("accept_btn", "btn_accept_invite")
        ready_btn = self.params.get("ready_btn", "btn_ready")

        # 1. 接受邀请
        ok_accept = ex.click_if_exists(accept_btn, threshold=0.8)
        time.sleep(1.0)
        # 2. 准备
        ok_ready = ex.click_if_exists(ready_btn, threshold=0.8)

        if not ok_accept and not ok_ready:
            return StepResult.fail("未找到接受邀请/准备按钮")

        return StepResult.success("加入队伍并准备完成")
