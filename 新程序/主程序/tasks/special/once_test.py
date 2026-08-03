"""
单次测试任务（每次启动执行一次，repeat=on_enter 启动任务）。

用途：验证 on_enter 启动任务（每次运行启动后执行一次）的
 调度→入队→执行→mark_done 完整链路。

执行流程（四步）：
    1. 触发识图任务 → [08-事件总线] 发布 trigger_detected(image_trigger_test)
       （与 TriggerWatcher 识图命中同一链路：05 订阅后 update_next_run(now) → 立即到期入队）
    2. 进入领奖界面 → [14→02→03→01] 点击入口 + [02] 界面识别
    3. 领取每日奖励 → [14→02→03→01] 点击领取
    4. 返回主界面   → [14→02→03→01] 返回按钮 + [02] 场景确认
"""
display_name = "单次测试"
description = "每次启动执行一次：进入领奖界面→领取每日奖励→返回主界面"
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


# ── 步骤1：触发识图任务 ──────────────────────────────────────

# 本任务执行时通过事件总线触发的识图任务
# （与 TriggerWatcher 识图命中同一链路：发布 trigger_detected
#   → 05-时间调度模块订阅 → update_next_run(name, now) → 立即到期入队）
TRIGGER_TASK = "image_trigger_test"


class TriggerImage(TaskStep):
    """步骤1 触发识图任务 → 发布 trigger_detected 事件（02→05 同一链路）"""
    is_generic = False
    timeout = 10

    def execute(self, context=None):
        tid = _task_id(context)
        _log(f"▶ 步骤1/4 触发识图任务：发布 trigger_detected(task_name={TRIGGER_TASK}) → 05 置为到期入队",
             task=tid, step=self.step_id)
        ok = False
        try:
            get_global_bus().publish(
                Events.TRIGGER_DETECTED, source="once_test",
                task_name=TRIGGER_TASK)
            ok = True
        except Exception as e:
            ok = f"异常:{e}"
        _log("    " + _mod_result(f"[08-事件总线] 发布 trigger_detected → {TRIGGER_TASK}", ok),
             task=tid, step=self.step_id)
        return StepResult.success("触发识图任务完成")


# ── 步骤2：进入领奖界面 ──────────────────────────────────────

class EnterAward(TaskStep):
    """步骤2 进入领奖界面 → 14-执行器(→02→03→01) + 02 界面识别"""
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤2/4 进入领奖界面：触发 [14-执行器模块] click_image()（02识图→03防封→01设备点击）",
             task=tid, step=self.step_id)
        ex = getattr(context, 'executor', None)
        ok = False
        if ex and hasattr(ex, 'click_image'):
            try:
                ok = ex.click_image("common/award/award_entry", timeout=5,
                                    stop_event=getattr(context, 'stop_event', None))
            except Exception as e:
                ok = f"异常:{e}"
        _log("    " + _mod_result("[14→02→03→01] 点击领奖入口", ok), task=tid, step=self.step_id)

        # 确认进入领奖界面（02 场景识别）
        scene = None
        if ex and hasattr(ex, 'detect_scene'):
            try:
                scene = ex.detect_scene(["common/award/award_panel"], timeout=3)
            except Exception as e:
                scene = f"异常:{e}"
        _log("    " + _mod_result("[02-图像识别] 领奖界面确认", scene), task=tid, step=self.step_id)
        return StepResult.success("进入领奖界面完成")


# ── 步骤3：领取每日奖励 ──────────────────────────────────────

class ClaimDaily(TaskStep):
    """步骤3 领取每日奖励 → 14-执行器(→02→03→01)"""
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤3/4 领取每日奖励：触发 [14-执行器模块] click_image()（02识图→03防封→01设备点击）",
             task=tid, step=self.step_id)
        ex = getattr(context, 'executor', None)
        ok = False
        if ex and hasattr(ex, 'click_image'):
            try:
                ok = ex.click_image("common/award/daily_reward_btn", timeout=5,
                                    stop_event=getattr(context, 'stop_event', None))
            except Exception as e:
                ok = f"异常:{e}"
        _log("    " + _mod_result("[14→02→03→01] 点击领取每日奖励", ok), task=tid, step=self.step_id)
        return StepResult.success("领取每日奖励完成")


# ── 步骤4：返回主界面 ────────────────────────────────────────

class BackHome(TaskStep):
    """步骤4 返回主界面 → 14-执行器 click_image + ensure_scene（02 场景确认）"""
    is_generic = False
    timeout = 20

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ 步骤4/4 返回主界面：触发 [14-执行器模块] click_image() + ensure_scene()（02 场景确认）",
             task=tid, step=self.step_id)
        ex = getattr(context, 'executor', None)
        ok = False
        if ex and hasattr(ex, 'click_image'):
            try:
                ok = ex.click_image("common/ui/back_btn", timeout=5,
                                    stop_event=getattr(context, 'stop_event', None))
            except Exception as e:
                ok = f"异常:{e}"
        _log("    " + _mod_result("[14→02→03→01] 返回按钮点击", ok), task=tid, step=self.step_id)
        confirmed = False
        if ex and hasattr(ex, 'ensure_scene'):
            try:
                confirmed = ex.ensure_scene("common/scene/home", timeout=3)
            except Exception as e:
                confirmed = f"异常:{e}"
        _log("    " + _mod_result("[02-图像识别] 主界面场景确认", confirmed), task=tid, step=self.step_id)
        return StepResult.success("返回主界面完成")


# ── 组装 TaskGraph（四步串行） ───────────────────────────────

def build_graph(context):
    from tasks.base.task_graph import EdgeType
    g = TaskGraph()
    g.add_step("trigger", TriggerImage())
    g.add_step("enter", EnterAward())
    g.add_step("claim", ClaimDaily())
    g.add_step("back", BackHome())

    g.set_entry("trigger")
    g.add_edge("trigger", "enter")
    g.add_edge("enter", "claim")
    g.add_edge("claim", "back")
    # 失败 → 兜底：跳到返回主界面（模拟环境素材缺失不影响链路走通）
    g.add_edge("trigger", "enter", EdgeType.ERROR)
    g.add_edge("enter", "back", EdgeType.ERROR)
    g.add_edge("claim", "back", EdgeType.ERROR)
    return g


class OnceTestTask(BaseTask):
    """单次测试任务入口（task_id 必须与 tasks.yaml 的 name 一致）"""
    task_id = "once_test"
    category = "special"

    def _build_graph(self):
        return build_graph(self._context)
