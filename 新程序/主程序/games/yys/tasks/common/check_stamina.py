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
        # 体力门槛：params.min_stamina 优先，其次 task_config.stamina_required
        # （UI「战斗配置→体力门槛」保存，经 scheduler→task_config 透传；0=不检查）
        min_stamina = self.params.get("min_stamina", None)
        if min_stamina is None and context is not None:
            tc = getattr(context, 'task_config', None) or {}
            min_stamina = tc.get("stamina_required")
        if min_stamina is None:
            min_stamina = 30
        min_stamina = int(min_stamina or 0)
        if min_stamina <= 0:
            return StepResult(status=StepStatus.SUCCESS, message="体力门槛未设置，不检查")

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
