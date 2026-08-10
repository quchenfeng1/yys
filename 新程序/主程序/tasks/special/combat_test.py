"""
战斗测试任务（模拟战斗，验证 战斗链路 / 御魂配置 / 战前准备 / 循环进度 / 断点续跑）。

战斗配置（本任务特有，直接记录在本任务中，不与核心模块耦合）：
  SOUL_SETUP   御魂套装 {组名, 队伍名, 位置[分组序号,队伍序号]} → 供「御魂配置」通用模块
  LOCK_TEAM    是否锁定队伍 → 供「战前准备」通用模块（选是则无法更换）
  CHANGE_TEAM  是否更换队伍 → 供「战前准备」通用模块

执行流程（五阶段日志）：
  1. 任务开始
  2. 御魂配置（SoulConfigure 通用模块：式神录→队伍配置→按位置更换御魂→返回主界面）
  3. 战前准备（PreBattlePrep 通用模块：锁定/解锁队伍处理；不参与循环，计入任务循环次数）
  4. 开始循环（模拟战斗 loop_count 场，每 5 秒输出"已执行 n 次"；断点续跑）
  5. 任务结束
"""
display_name = "战斗测试"
description = "五阶段：任务开始→御魂配置→战前准备→循环战斗(每5s进度)→任务结束"
task_type = "battle"
uses_battle = True
uses_team = True
uses_stamina = True
loop_count = 5
timeout = 600

# ── 战斗配置（本任务特有；御魂配置/战前准备通用模块读取） ──────
SOUL_SETUP = {"group": "御魂副本", "team": "御魂十层", "position": [4, 1]}
LOCK_TEAM = True      # 战前准备：是否锁定队伍（选是则无法更换）
CHANGE_TEAM = True    # 战前准备：是否更换队伍

import time
from pathlib import Path
from typing import Any

import yaml

from core.event_bus import get_global_bus
from core.events import Events
from tasks.base.base_task import BaseTask
from tasks.base.task_graph import TaskGraph
from tasks.base.task_step import StepResult, TaskStep
from tasks.common.soul_configure import SoulConfigure
from tasks.common.pre_battle_prep import PreBattlePrep


def _load_battle_config(context: Any = None) -> dict:
    """读取本任务的战斗配置（UI「战斗配置」Tab 保存）。

    优先从 context.task_config 读取（run_controller 注入 scheduler 透传的
    soul_setup/lock_team/change_team）；缺失时回退文件内常量
    （SOUL_SETUP/LOCK_TEAM/CHANGE_TEAM）。
    """
    # ① task_config（架构内透传：UI → tasks.yaml → scheduler → run_controller）
    if context is not None:
        cfg = getattr(context, 'task_config', None) or {}
        soul = cfg.get("soul_setup")
        lock_team = cfg.get("lock_team")
        change_team = cfg.get("change_team")
        if soul or lock_team is not None or change_team is not None:
            return {
                "soul_setup": soul or SOUL_SETUP,
                "lock_team": bool(lock_team) if lock_team is not None else LOCK_TEAM,
                "change_team": bool(change_team) if change_team is not None else CHANGE_TEAM,
            }
    # ② 直接读 tasks.yaml（兼容旧保存；task_config 缺失时兜底）
    try:
        yaml_path = Path(__file__).resolve().parents[2] / "config" / "tasks.yaml"
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for t in data.get("tasks", []) or []:
                if (t.get("name") or t.get("id")) == "combat_test":
                    return {
                        "soul_setup": t.get("soul_setup") or SOUL_SETUP,
                        "lock_team": bool(t.get("lock_team", LOCK_TEAM)),
                        "change_team": bool(t.get("change_team", CHANGE_TEAM)),
                    }
    except Exception:
        pass
    return {"soul_setup": SOUL_SETUP, "lock_team": LOCK_TEAM, "change_team": CHANGE_TEAM}


def _log(message: str, level: str = "info", task: str = "", step: str = "") -> None:
    """输出到 UI 日志面板（LOG_RECORD 事件）；无总线时兜底 print"""
    try:
        get_global_bus().publish(Events.LOG_RECORD, source="tasks",
                                 level=level, message=message, task=task, step=step)
    except Exception:
        print(f"[{level}] {message}")


def _task_id(context) -> str:
    return (getattr(context, 'task_id', '') or getattr(context, 'task_name', ''))


# ── 阶段1：任务开始 ──────────────────────────────────────────

class TaskStart(TaskStep):
    """阶段1：任务开始（进入副本）"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        tid = _task_id(context)
        cfg = getattr(context, 'task_config', None) or {}
        floor = cfg.get("floor")
        bc = _load_battle_config(context)
        _log(f"▶ [战斗测试] 1/5 任务开始：进入副本 第{floor}层" if floor
             else "▶ [战斗测试] 1/5 任务开始：进入副本（默认层）",
             task=tid, step=self.step_id)
        _log(f"    战斗配置：御魂={bc.get('soul_setup')} · 锁定队伍={bc.get('lock_team')} · 更换队伍={bc.get('change_team')}",
             task=tid, step=self.step_id)
        time.sleep(0.3)
        return StepResult.success("任务开始")


# ── 阶段4：开始循环（每 5s 输出已执行 n 次） ─────────────────

class CombatLoop(TaskStep):
    """阶段4：战斗循环（每 5 秒输出"已执行 n 次"；断点续跑 + 锁定/更换队伍时机）"""
    is_generic = False
    timeout = 600

    def execute(self, context=None):
        task_id = _task_id(context)
        state = getattr(context, 'state', None)
        saver = getattr(context, 'progress_saver', None)
        cfg = getattr(context, 'task_config', None) or {}
        total = int(cfg.get("loop_count") or 1)
        lock_team = bool(self.params.get("lock_team", False))
        change_team = bool(self.params.get("change_team", False))

        # 断点恢复：从 context.state 读取已完成场次
        completed = 0
        if state is not None and isinstance(state, dict) and task_id:
            entry = state.get(task_id)
            if isinstance(entry, dict):
                try:
                    completed = int(entry.get("completed", 0) or 0)
                except (TypeError, ValueError):
                    completed = 0

        _log(f"▶ [战斗测试] 4/5 开始循环：目标 {total} 次，已完成 {completed} 次（断点续跑）",
             task=task_id, step=self.step_id)

        for i in range(completed, total):
            if self.check_interrupt(context):
                return StepResult.skip("被中断")

            # 第 1 次进入战斗：按御魂配置更换队伍（战前准备已解锁）
            if i == 0 and change_team:
                _log(f"    第 {i + 1} 次进入战斗：按御魂配置更换队伍（战前已取消锁定）",
                     task=task_id, step=self.step_id)
            # 第 2 次进入战斗前：锁定队伍（防止再次更换）
            if i == 1 and (lock_team or change_team):
                _log(f"    第 {i + 1} 次进入战斗前：锁定队伍（选择锁定后无法更换）",
                     task=task_id, step=self.step_id)

            time.sleep(5)  # 模拟一场战斗耗时（每 5 秒输出一次进度）
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

            _log(f"    已执行 {completed}/{total} 次",
                 task=task_id, step=self.step_id)

        return StepResult.success(f"战斗循环完成，共 {completed} 次")


# ── 阶段5：任务结束 ──────────────────────────────────────────

class TaskEnd(TaskStep):
    """阶段5：任务结束"""
    is_generic = False
    timeout = 15

    def execute(self, context=None):
        tid = _task_id(context)
        _log("▶ [战斗测试] 5/5 任务结束：五阶段完成（收尾 mark_done 由 09/05 自动处理）",
             task=tid, step=self.step_id)
        time.sleep(0.3)
        return StepResult.success("任务结束")


# ── 组装 TaskGraph（五阶段串行） ─────────────────────────────

def build_graph(context):
    from tasks.base.task_graph import EdgeType
    bc = _load_battle_config(context)  # 从 task_config 读取（UI 保存），失败回退文件常量
    soul = bc.get("soul_setup") or {}
    lock_team = bool(bc.get("lock_team", LOCK_TEAM))
    change_team = bool(bc.get("change_team", CHANGE_TEAM))

    g = TaskGraph()
    g.add_step("start", TaskStart())
    # 关联通用模块：御魂配置（传入组名/队伍名/位置）
    g.add_step("soul", SoulConfigure(
        group=soul.get("group", ""),
        team=soul.get("team", ""),
        position=soul.get("position", [1, 1]),
    ))
    # 关联通用模块：战前准备（传入锁定/更换开关）
    g.add_step("prep", PreBattlePrep(lock_team=lock_team, change_team=change_team))
    g.add_step("battle", CombatLoop(lock_team=lock_team, change_team=change_team))
    g.add_step("end", TaskEnd())

    g.set_entry("start")
    g.add_edge("start", "soul")
    g.add_edge("soul", "prep")
    g.add_edge("prep", "battle")
    g.add_edge("battle", "end")
    # 失败 → 跳到结束任务（模拟环境素材缺失不影响链路走通）
    g.add_edge("start", "end", EdgeType.ERROR)
    g.add_edge("soul", "end", EdgeType.ERROR)
    g.add_edge("prep", "end", EdgeType.ERROR)
    g.add_edge("battle", "end", EdgeType.ERROR)
    return g


class CombatTestTask(BaseTask):
    """战斗测试任务入口（task_id 必须与 tasks.yaml 的 name 一致）"""
    task_id = "combat_test"
    category = "special"

    def _build_graph(self):
        return build_graph(self._context)
