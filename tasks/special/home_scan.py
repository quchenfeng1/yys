"""
主界面识别-测试 — 特殊任务任务

测试主界面识别模块：调用 OpenBottomMenu，展开底部菜单栏。
"""

display_name = "主界面识别-测试"
description = "调用主界面识别模块，展开底部菜单栏 — 事件任务"
task_type = "event_task"

from tasks.base.task_step import TaskStep, StepResult
from tasks.base.task_context import TaskContext
from tasks.common.open_bottom_menu import OpenBottomMenu


class HomeScanTask(TaskStep):
    """主界面识别-测试：调用 OpenBottomMenu 展开底部菜单。"""
    name = "home_scan"
    display_name = "主界面识别-测试"
    description = "调用主界面识别模块，展开底部菜单栏"
    is_generic = False
    timeout = 20

    def execute(self, context: TaskContext) -> StepResult:
        step = OpenBottomMenu()
        return step.execute(context)
