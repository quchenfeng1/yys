"""
单次测试任务（纯模拟，repeat=once 单次执行）。

用途：验证单次任务执行一次后不再调度（once 规则）、
单次执行的 调度→入队→执行→mark_done 完整链路。

执行流程：
    打开面板 → 确认操作 → 完成返回
"""
display_name = "单次测试"
description = "模拟单次任务：打开面板→确认操作→完成返回，验证 once 规则"
task_type = "event_task"
timeout = 120

import time

from core.event_bus import get_global_bus
from core.events import Events
from tasks.base.base_task import BaseTask
from tasks.base.task_graph import TaskGraph
from tasks.base.task_step import StepResult, TaskStep


def _log(message: str, level: str = "info", task: str = "", step: str = "") -> None:
    """输出到 UI 日志面板（LOG_RECORD 事件）；无总线时兜底 print"""
    try:
        get_global_bus().publish(Events.LOG_RECORD, source="tasks",
                                 level=level, message=message, task=task, step=step)
    except Exception:
        print(f"[{level}] {message}")


def _task_id(context) -> str:
    return (getattr(context, 'task_id', '') or getattr(context, 'task_name', ''))


class OpenPanel(TaskStep):
    """模拟：打开面板"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        _log("模拟打开面板...", task=_task_id(context), step=self.step_id)
        time.sleep(0.3)
        return StepResult.success("面板已打开")


class ConfirmAction(TaskStep):
    """模拟：确认操作"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        _log("模拟点击确认...", task=_task_id(context), step=self.step_id)
        time.sleep(0.3)
        return StepResult.success("确认完成")


class FinishTask(TaskStep):
    """模拟：完成并返回"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        _log("模拟完成并返回...", task=_task_id(context), step=self.step_id)
        time.sleep(0.3)
        return StepResult.success("单次任务完成")


def build_graph(context):
    from tasks.base.task_graph import EdgeType
    g = TaskGraph()
    g.add_step("open", OpenPanel())
    g.add_step("confirm", ConfirmAction())
    g.add_step("finish", FinishTask())

    g.set_entry("open")
    g.add_edge("open", "confirm")
    g.add_edge("confirm", "finish")
    # 失败 → 跳到完成（模拟恢复）
    g.add_edge("open", "finish", EdgeType.ERROR)
    g.add_edge("confirm", "finish", EdgeType.ERROR)
    return g


class OnceTestTask(BaseTask):
    """单次测试任务入口（task_id 必须与 tasks.yaml 的 name 一致）"""
    task_id = "once_test"
    category = "special"

    def _build_graph(self):
        return build_graph(self._context)
