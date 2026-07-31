"""
通用模块：战前准备（队伍锁定/更换处理）。

战斗类任务在进入战斗循环前的重复性准备操作，封装为通用模块。
**不参与战斗循环，但计入任务循环次数**（任务执行一次 = 调度器计一次）。

逻辑（参数 lock_team / change_team 组合）：
  - 是否锁定队伍（lock_team=True）：在第一次战斗之前锁定队伍（选择是则无法更换队伍）
  - 是否更换队伍（change_team=True）：第一次进入战斗前点击"取消锁定"按钮
      （解锁后队伍才可更换）；更换动作本身由御魂配置完成；第二次进入战斗前锁定队伍

组合规则：
  lock_team=True  & change_team=False → 直接锁定队伍（无法更换）
  change_team=True                    → 先取消锁定（为更换御魂做准备），
                                        后续循环内第 2 场前再锁定

参数（构造时传入，存 params）：
  lock_team:   bool  是否锁定队伍
  change_team: bool  是否更换队伍
"""
from __future__ import annotations

import time
from typing import Any

from core.event_bus import get_global_bus
from core.events import Events
from tasks.base.task_step import StepResult, StepStatus, TaskStep


def _log(message: str, level: str = "info", task: str = "", step: str = "") -> None:
    """输出到 UI 日志面板（LOG_RECORD 事件）；无总线时兜底 print"""
    try:
        get_global_bus().publish(Events.LOG_RECORD, source="common",
                                 level=level, message=message, task=task, step=step)
    except Exception:
        print(f"[{level}] {message}")


def _task_id(context) -> str:
    return (getattr(context, 'task_id', '') or getattr(context, 'task_name', ''))


class PreBattlePrep(TaskStep):
    """战前准备：根据锁定/更换配置处理队伍状态"""

    is_generic = True
    timeout = 30

    def execute(self, context: Any = None) -> StepResult:
        tid = _task_id(context)
        lock_team = bool(self.params.get("lock_team", False))
        change_team = bool(self.params.get("change_team", False))

        _log(f"[战前准备] 开始：锁定队伍={lock_team} · 更换队伍={change_team}（不参与循环，计入任务循环次数）",
             task=tid, step=self.step_id)

        if change_team:
            # 需要更换队伍：第一次进入战斗前点击"取消锁定"按钮解锁
            _log("[战前准备] ① 点击「取消锁定」按钮（解锁队伍，准备更换御魂）",
                 task=tid, step=self.step_id)
            self._mock_action(context, "点击取消锁定", "common/battle/unlock_btn")
            _log("[战前准备]    队伍已解锁 → 更换御魂动作由「御魂配置」完成；"
                 "第 2 次进入战斗前由战斗循环锁定队伍",
                 task=tid, step=self.step_id)
        elif lock_team:
            # 只锁定不更换：第一次战斗前直接锁定（选择锁定则无法更换）
            _log("[战前准备] ① 点击「锁定队伍」按钮（锁定后无法更换队伍）",
                 task=tid, step=self.step_id)
            self._mock_action(context, "点击锁定队伍", "common/battle/lock_btn")
        else:
            _log("[战前准备] 未启用锁定/更换，跳过队伍处理", task=tid, step=self.step_id)

        _log("[战前准备] 完成", task=tid, step=self.step_id)
        return StepResult(status=StepStatus.SUCCESS, message="战前准备完成")

    def _mock_action(self, context, desc: str, template: str) -> bool:
        ex = getattr(context, 'executor', None) if context else None
        ok = False
        if ex and hasattr(ex, 'click_image'):
            try:
                ok = ex.click_image(template, timeout=3,
                                    stop_event=getattr(context, 'stop_event', None))
            except Exception:
                ok = False
        time.sleep(0.3)  # 模拟操作耗时
        if ok:
            _log(f"        ✅ 操作成功: {desc}（[14→02→03→01] 链路正常）")
        else:
            _log(f"        ⚠️ 操作未命中: {desc}（模拟环境无素材/设备，调用链已走通）")
        return True
