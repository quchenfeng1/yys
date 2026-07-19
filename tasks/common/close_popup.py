"""
关弹窗（通用模块）

检测并关闭通用弹窗（公告/提示/奖励领取）。
全项目所有任务复用，常在步骤间插入调用。
"""

display_name = "关闭弹窗"
description = "检测并关闭公告/提示/奖励弹窗，步骤间插入调用"

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class ClosePopup(TaskStep):
    """关闭所有弹窗。"""
    name = "close_popup"
    is_generic = True
    timeout = 15

    # 常见关闭按钮素材名
    CLOSE_IMAGES = [
        "common/ui/close_btn",
        "common/ui/confirm_btn",
        "common/ui/cancel_btn",
    ]

    def execute(self, context: TaskContext) -> StepResult:
        executor = context.executor
        closed = 0
        for img in self.CLOSE_IMAGES:
            if executor.click_if_exists(img, threshold=0.75):
                closed += 1
                executor.random_sleep(0.3, 0.8)
        return StepResult.success(f"关闭 {closed} 个弹窗", closed_count=closed)
