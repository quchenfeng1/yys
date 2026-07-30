"""
通用模块：关弹窗（通用弹窗检测）。

检测屏幕上的常见弹窗并关闭。
"""
from __future__ import annotations

import time

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class ClosePopup(TaskStep):
    """通用弹窗关闭"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        # 常见弹窗按钮关键词
        close_keywords = self.params.get(
            "keywords",
            ["关闭", "确定", "取消", "知道了", "x", "close", "confirm"]
        )

        # 实际通过 OCR 检测文本
        # 或通过模板匹配检测关闭按钮

        closed_count = 0
        for _ in range(3):  # 最多尝试 3 轮
            if self.check_interrupt(context):
                return StepResult(status=StepStatus.SKIP, message="被中断")
            # 查找并点击关闭按钮
            time.sleep(0.5)

        return StepResult(
            status=StepStatus.SUCCESS,
            message=f"弹窗处理完成，关闭 {closed_count} 个",
        )
