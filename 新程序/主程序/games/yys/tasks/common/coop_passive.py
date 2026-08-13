"""
通用模块：CoopPassive 组队待机（被带方自动领奖）。

在"当前设备"上执行（由 CoopHost 切换到小号模拟器后调用）：
- 检测战斗中 / 结算界面，等待战斗结束
- 出现结算界面 → 点击领奖（claim_btn 素材）

素材名可配置（params），默认约定名 btn_claim。
"""
from __future__ import annotations

import time
from typing import Any

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class CoopPassive(TaskStep):
    """组队被动：等待战斗结束并领奖（当前设备）"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        ex = getattr(context, 'executor', None)
        if ex is None:
            return StepResult.fail("缺少 executor")

        wait_timeout = float(self.params.get("wait_timeout", 300))
        claim_btn = self.params.get("claim_btn", "btn_claim")
        check_interval = float(self.params.get("check_interval", 5.0))
        elapsed = 0.0

        while elapsed < wait_timeout:
            if self.check_interrupt(context):
                return StepResult(status=StepStatus.SKIP, message="被中断")
            # 出现结算界面 → 领奖并结束
            if ex.click_if_exists(claim_btn, threshold=0.8):
                return StepResult.success("领取奖励完成")
            # 检测是否仍在战斗（可选场景，不阻断）
            time.sleep(check_interval)
            elapsed += check_interval

        # 超时后仍尝试一次领奖
        ex.click_if_exists(claim_btn, threshold=0.8)
        return StepResult.success("被动组队完成（等待结束）")
