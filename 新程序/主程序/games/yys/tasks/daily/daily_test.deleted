"""
日常测试任务（模块链路验证版，纯模拟，无需真实素材/设备）。

用途：验证 调度循环 / 任务队列 / 日志输出 / 五步链路 是否走通。
每个步骤真实调用对应模块接口并打印日志，便于核对"每一步触发了哪些模块"。

五步流程（→ 触发的模块）：
    1. 识别主界面 → 02-图像识别模块（executor.detect_scene → recognizer）
    2. 点击按钮   → 14-执行器模块（click_image，内部 02识图→03防封偏移/延迟→01设备点击）
    3. 确认界面   → 02-图像识别模块（recognizer.wait 等待机制）
    4. 返回主界面 → 14-执行器模块（click_image 返回 + ensure_scene 场景确认）
    5. 结束任务   → 04 任务引擎返回 TaskResult → 09 mark_done → 05 推进 next_run_time
"""
display_name = "日常测试"
description = "五步链路验证：识别主界面→点击按钮→确认界面→返回主界面→结束任务"
task_type = "event_task"
loop_count = 1
timeout = 300

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


def _mod_result(tag: str, ok, detail: str = "") -> str:
    """格式化模块调用结果：
    - True / 非空非异常对象（场景名/MatchResult）→ 成功
    - False / None → 未命中（模拟环境无素材/设备，调用链已走通）
    - 以"异常:"开头 → 调用抛异常（链路仍走通）
    """
    if ok is True:
        return f"✅ {tag} 成功 {detail}".strip()
    if ok is False or ok is None:
        return f"⚠️  {tag} 未命中（模拟环境无素材/设备，调用链已走通）"
    if isinstance(ok, str) and ok.startswith("异常:"):
        return f"⚠️  {tag} 异常: {ok[len('异常:'):].strip()}（调用链已走通）"
    # 非布尔返回值：识别成功返回的场景名 / MatchResult 等对象
    return f"✅ {tag} 成功: {ok}"


# ── 五步链路 ────────────────────────────────────────────────

class DetectHome(TaskStep):
    """步骤1 识别主界面 → 02-图像识别模块"""
    is_generic = False
    timeout = 20
    scene_probe = ["common/scene/home"]  # 场景感知：步骤前静默确认主界面位置

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤1/5 识别主界面：触发 [02-图像识别模块] executor.detect_scene()",
             task=tid, step=self.step_id)
        ex = getattr(context, 'executor', None)
        scene = None
        if ex and hasattr(ex, 'detect_scene'):
            try:
                scene = ex.detect_scene(["common/scene/home"], timeout=3)
            except Exception as e:
                scene = f"异常:{e}"
        _log("    " + _mod_result("[02-图像识别] 主界面识别", scene),
             task=tid, step=self.step_id)
        return StepResult.success("识别主界面完成")


class ClickButton(TaskStep):
    """步骤2 点击按钮 → 14-执行器(→02→03→01)"""
    is_generic = False
    timeout = 20
    scene_probe = ["common/scene/home"]  # 场景感知：步骤前确认仍在主界面

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤2/5 点击按钮：触发 [14-执行器模块] click_image()（内部 02识图→03防封偏移/延迟→01设备点击）",
             task=tid, step=self.step_id)
        ex = getattr(context, 'executor', None)
        ok = False
        if ex and hasattr(ex, 'click_image'):
            try:
                ok = ex.click_image("common/ui/test_button", timeout=5,
                                    stop_event=getattr(context, 'stop_event', None))
            except Exception as e:
                ok = f"异常:{e}"
        _log("    " + _mod_result("[14→02→03→01] 按钮点击", ok),
             task=tid, step=self.step_id)
        return StepResult.success("点击按钮完成")


class ConfirmScene(TaskStep):
    """步骤3 确认界面 → 02-图像识别模块 wait 等待机制"""
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤3/5 确认界面：触发 [02-图像识别模块] recognizer.wait() 等待目标出现（含停止信号打断）",
             task=tid, step=self.step_id)
        rec = getattr(context, 'recognizer', None)
        found = None
        if rec and hasattr(rec, 'wait'):
            try:
                found = rec.wait("common/scene/confirm", timeout=3,
                                 stop_event=getattr(context, 'stop_event', None))
            except Exception as e:
                found = f"异常:{e}"
        _log("    " + _mod_result("[02-图像识别] 界面确认等待", found),
             task=tid, step=self.step_id)
        return StepResult.success("确认界面完成")


class BackHome(TaskStep):
    """步骤4 返回主界面 → 14-执行器 click_image + ensure_scene（02 场景确认）"""
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤4/5 返回主界面：触发 [14-执行器模块] click_image() + ensure_scene()（02 场景确认）",
             task=tid, step=self.step_id)
        ex = getattr(context, 'executor', None)
        ok = False
        if ex and hasattr(ex, 'click_image'):
            try:
                ok = ex.click_image("common/ui/back_btn", timeout=5,
                                    stop_event=getattr(context, 'stop_event', None))
            except Exception as e:
                ok = f"异常:{e}"
        _log("    " + _mod_result("[14→02→03→01] 返回按钮点击", ok),
             task=tid, step=self.step_id)
        confirmed = False
        if ex and hasattr(ex, 'ensure_scene'):
            try:
                confirmed = ex.ensure_scene("common/scene/home", timeout=3)
            except Exception as e:
                confirmed = f"异常:{e}"
        _log("    " + _mod_result("[02-图像识别] 主界面场景确认", confirmed),
             task=tid, step=self.step_id)
        return StepResult.success("返回主界面完成")


class FinishTask(TaskStep):
    """步骤5 结束任务 → 04 返回 TaskResult → 09 mark_done → 05 推进"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤5/5 结束任务：返回 success → [04] 任务引擎返回 TaskResult → [09] mark_done() → [05] 推进 next_run_time",
             task=tid, step=self.step_id)
        _log("    ✅ 五步链路全部执行完毕，任务结束（收尾由 09/05 自动完成）",
             task=tid, step=self.step_id)
        return StepResult.success("任务完成")


# ── 组装 TaskGraph（五步串行） ───────────────────────────────

def build_graph(context):
    from tasks.base.task_graph import EdgeType
    g = TaskGraph()
    g.add_step("detect_home", DetectHome())
    g.add_step("click_btn", ClickButton())
    g.add_step("confirm_scene", ConfirmScene())
    g.add_step("back_home", BackHome())
    g.add_step("finish", FinishTask())

    g.set_entry("detect_home")
    g.add_edge("detect_home", "click_btn")
    g.add_edge("click_btn", "confirm_scene")
    g.add_edge("confirm_scene", "back_home")
    g.add_edge("back_home", "finish")
    # 失败 → 跳到结束任务（模拟环境素材缺失不影响链路走通）
    g.add_edge("detect_home", "finish", EdgeType.ERROR)
    g.add_edge("click_btn", "finish", EdgeType.ERROR)
    g.add_edge("confirm_scene", "finish", EdgeType.ERROR)
    g.add_edge("back_home", "finish", EdgeType.ERROR)
    return g


class DailyTestTask(BaseTask):
    """日常测试任务入口（task_id 必须与 tasks.yaml 的 name 一致）"""
    task_id = "daily_test"
    category = "daily"

    def _build_graph(self):
        return build_graph(self._context)
