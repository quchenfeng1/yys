"""
体力检查（通用模块）

体力不足时跳过任务。
"""

display_name = "体力检查"
description = "检查体力是否满足任务要求，不足则跳过当前任务"

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext


class CheckStamina(TaskStep):
    """检查体力是否充足。"""
    name = "check_stamina"
    is_generic = True
    timeout = 10

    def execute(self, context: TaskContext) -> StepResult:
        required = context.task_config.get("stamina_required", 0)
        if required <= 0:
            return StepResult.success("无需体力检查")

        # TODO: 通过 OCR 识图获取当前体力值
        # 暂时跳过检查
        return StepResult.success("体力检查通过（暂未实现 OCR）")
