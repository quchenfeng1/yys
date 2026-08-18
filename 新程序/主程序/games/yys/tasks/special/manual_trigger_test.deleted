"""
手动触发测试任务（trigger 类型：需要点击按钮去执行）。

触发方式（说明书 05 §3.1 trigger 例外 + 11 用户界面 §3.2）：
  UI 队列面板"⚡触发"按钮 → TaskBridge.update_next_run(name, now)
  → 任务立即到期 → 填充线程拾取入队 → 执行
  → 执行后 mark_done → completed + 清空 next_run
  → 已失效区标注"[等待下次触发] · 外部触发后重新激活"

本任务不配置 trigger_templates（无需识图触发），只由手动按钮触发。

执行流程：
    1. 任务开始（标注手动触发）
    2. 执行动作（点击测试按钮，14→02→03→01）
    3. 确认界面（02 图像识别等待）
    4. 任务结束
"""
display_name = "手动触发测试"
description = "trigger 手动触发：点击按钮执行一次，执行后等待下次触发"
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


def _mod_result(tag: str, ok) -> str:
    """格式化模块调用结果（与 daily_test 一致）"""
    if ok is True:
        return f"✅ {tag} 成功"
    if ok is False or ok is None:
        return f"⚠️  {tag} 未命中（模拟环境无素材/设备，调用链已走通）"
    if isinstance(ok, str) and ok.startswith("异常:"):
        return f"⚠️  {tag} 异常: {ok[len('异常:'):].strip()}（调用链已走通）"
    return f"✅ {tag} 成功: {ok}"


# ── 步骤1：任务开始 ──────────────────────────────────────────

class TaskStart(TaskStep):
    """步骤1 任务开始（标注手动触发）"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤1/4 任务开始：由 UI「⚡触发」按钮手动触发（trigger 手动触发）",
             task=tid, step=self.step_id)
        time.sleep(0.3)
        return StepResult.success("任务开始")


# ── 步骤2：执行动作 ──────────────────────────────────────────

class DoAction(TaskStep):
    """步骤2 执行动作 → 14-执行器(→02→03→01)"""
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤2/4 执行动作：触发 [14-执行器模块] click_image()（02识图→03防封→01设备点击）",
             task=tid, step=self.step_id)
        ex = getattr(context, 'executor', None)
        ok = False
        if ex and hasattr(ex, 'click_image'):
            try:
                ok = ex.click_image("common/ui/test_button", timeout=5,
                                    stop_event=getattr(context, 'stop_event', None))
            except Exception as e:
                ok = f"异常:{e}"
        _log("    " + _mod_result("[14→02→03→01] 点击测试按钮", ok), task=tid, step=self.step_id)
        return StepResult.success("执行动作完成")


# ── 步骤3：确认界面 ──────────────────────────────────────────

class ConfirmScene(TaskStep):
    """步骤3 确认界面 → 02-图像识别模块 wait 等待机制"""
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤3/4 确认界面：触发 [02-图像识别模块] recognizer.wait() 等待目标出现",
             task=tid, step=self.step_id)
        rec = getattr(context, 'recognizer', None)
        found = None
        if rec and hasattr(rec, 'wait'):
            try:
                found = rec.wait("common/scene/confirm", timeout=3,
                                 stop_event=getattr(context, 'stop_event', None))
            except Exception as e:
                found = f"异常:{e}"
        _log("    " + _mod_result("[02-图像识别] 界面确认等待", found), task=tid, step=self.step_id)
        return StepResult.success("确认界面完成")


# ── 步骤4：任务结束 ──────────────────────────────────────────

class TaskEnd(TaskStep):
    """步骤4 任务结束"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤4/4 任务结束：执行后进入已失效「[等待下次触发]·外部触发后重新激活」（mark_done 由 09/05 自动处理）",
             task=tid, step=self.step_id)
        time.sleep(0.3)
        return StepResult.success("任务结束")


# ── 组装 TaskGraph（四步串行） ───────────────────────────────

def build_graph(context):
    from tasks.base.task_graph import EdgeType
    g = TaskGraph()
    g.add_step("start", TaskStart())
    g.add_step("action", DoAction())
    g.add_step("confirm", ConfirmScene())
    g.add_step("end", TaskEnd())

    g.set_entry("start")
    g.add_edge("start", "action")
    g.add_edge("action", "confirm")
    g.add_edge("confirm", "end")
    # 失败 → 跳到结束任务（模拟环境素材缺失不影响链路走通）
    g.add_edge("start", "end", EdgeType.ERROR)
    g.add_edge("action", "end", EdgeType.ERROR)
    g.add_edge("confirm", "end", EdgeType.ERROR)
    return g


class ManualTriggerTestTask(BaseTask):
    """手动触发测试任务入口（task_id 必须与 tasks.yaml 的 name 一致）"""
    task_id = "manual_trigger_test"
    category = "special"

    def _build_graph(self):
        return build_graph(self._context)
