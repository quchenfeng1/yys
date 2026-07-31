"""
战斗测试任务（纯模拟战斗，无需真实素材/游戏环境）。

用途：验证 战斗链路 / 进度持久化 / 断点续跑。
- 每场战斗打印进度并立即持久化（context.progress_saver）
- 异常关闭后重跑，从已完成场次继续（断点续跑）
- 从 task_config 读取 loop_count（战斗场数）与 floor（副本层数）

执行流程（SETUP → LOOP → TEARDOWN）：
    进入副本(第floor层) → 模拟战斗(loop_count 场) → 返回庭院
"""
display_name = "战斗测试"
description = "模拟 N 场战斗并持久化进度，验证战斗循环与断点续跑"
task_type = "battle"
uses_battle = True
uses_team = True
uses_stamina = True
loop_count = 5
timeout = 600

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


class EnterBattle(TaskStep):
    """模拟：进入副本（读取 floor）"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        cfg = getattr(context, 'task_config', None) or {}
        floor = cfg.get("floor")
        if floor:
            _log(f"模拟进入副本 第{floor}层...", task=_task_id(context), step=self.step_id)
        else:
            _log("模拟进入副本（默认层）...", task=_task_id(context), step=self.step_id)
        time.sleep(0.3)
        return StepResult.success(f"已进入副本第{floor}层" if floor else "已进入副本")


class MockBattleLoop(TaskStep):
    """模拟：N 场战斗循环（断点续跑 + 进度持久化）"""
    is_generic = False
    timeout = 600

    def execute(self, context=None):
        task_id = _task_id(context)
        state = getattr(context, 'state', None)
        saver = getattr(context, 'progress_saver', None)
        cfg = getattr(context, 'task_config', None) or {}
        total = int(cfg.get("loop_count") or 1)

        # 断点恢复：从 context.state 读取已完成场次
        completed = 0
        if state is not None and isinstance(state, dict) and task_id:
            entry = state.get(task_id)
            if isinstance(entry, dict):
                try:
                    completed = int(entry.get("completed", 0) or 0)
                except (TypeError, ValueError):
                    completed = 0

        _log(f"战斗测试开始：已完成 {completed}/{total} 场（断点续跑）",
             task=task_id, step=self.step_id)

        for i in range(completed, total):
            if self.check_interrupt(context):
                return StepResult.skip("被中断")
            time.sleep(0.3)  # 模拟一场战斗耗时
            completed = i + 1

            # 写回 context.state + 立即持久化（异常关闭最多丢 1 场）
            if state is not None and isinstance(state, dict) and task_id:
                state[task_id] = {
                    "completed": int(completed),
                    "total": int(total),
                    "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            if saver is not None:
                try:
                    saver(task_id, int(completed), int(total))
                except Exception:
                    pass

            _log(f"  战斗 [{completed}/{total}] 完成",
                 task=task_id, step=self.step_id)

        return StepResult.success(f"战斗测试完成，共 {completed} 场")


class ReturnHome(TaskStep):
    """模拟：返回庭院"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        _log("模拟返回庭院...", task=_task_id(context), step=self.step_id)
        time.sleep(0.3)
        return StepResult.success("已返回庭院")


# ── 组装 TaskGraph（SETUP → LOOP → TEARDOWN） ───────────────

def build_graph(context):
    from tasks.base.task_graph import EdgeType
    g = TaskGraph()
    g.add_step("enter", EnterBattle())
    g.add_step("battle", MockBattleLoop())
    g.add_step("home", ReturnHome())

    g.set_entry("enter")
    g.add_edge("enter", "battle")
    g.add_edge("battle", "home")
    # 失败 → 返回庭院恢复
    g.add_edge("enter", "home", EdgeType.ERROR)
    g.add_edge("battle", "home", EdgeType.ERROR)
    return g


class CombatTestTask(BaseTask):
    """战斗测试任务入口（task_id 必须与 tasks.yaml 的 name 一致）"""
    task_id = "combat_test"
    category = "special"

    def _build_graph(self):
        return build_graph(self._context)
