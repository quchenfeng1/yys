"""
通用模块：体力检查。

通过 OCR 识别当前体力值，判断是否达到执行阈值。
"""
from __future__ import annotations

from tasks.base.task_step import TaskStep, StepResult, StepStatus


class CheckStamina(TaskStep):
    """体力检查：检测当前体力是否充足"""

    is_generic = True

    def execute(self, context: Any = None) -> StepResult:
        min_stamina = self.params.get("min_stamina", 30)
        # 实际通过 OCR 识别体力值
        # current = ocr_locator.find_text(screenshot, "体力")
        # stamina = parse_stamina(current)

        # 占位逻辑
        stamina = self.params.get("current_stamina", 999)

        if stamina < min_stamina:
            return StepResult(
                status=StepStatus.SKIP,
                message=f"体力不足: {stamina}/{min_stamina}",
            )

        return StepResult(
            status=StepStatus.SUCCESS,
            message=f"体力充足: {stamina}",
        )
