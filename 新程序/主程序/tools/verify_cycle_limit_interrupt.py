"""验证：活动循环次数达上限 → 立即中断任务收尾（BattleLoop 不再超额循环）。

链路：
  BattleLoop 每场循环结束 → progress_saver → RunController._on_task_progress
  → scheduler.record_cycle +1 → 达上限返回 True → RunController set cycle_limit_event
  → BattleLoop 下一轮循环开头检查 → 返回 SUCCESS（成功收尾）→ 不再多跑

验证点：
  1. BattleLoop 达上限 → 返回 SUCCESS 且只完成上限场数（不超额）
  2. RunController 联动：record_cycle → set event → BattleLoop 中断 → 调度器失效
  3. 未达上限时 BattleLoop 正常跑满 max_battles（回归保障）
"""
import os, sys, threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from core.event_bus import EventBus
from core.scheduler import Scheduler, TaskConfig, RepeatConfig, ScheduleStatus
from games.yys.tasks.common.battle_loop import BattleLoop
from tasks.base.task_step import StepStatus

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


class FakeStateMgr:
    """最小 state_mgr（_on_task_progress 写入 task_runtime_progress 用）"""
    def __init__(self):
        self._data = {"task_runtime_progress": {}}

    def get_state(self, key, default=None):
        return self._data.get(key, default)

    def set_state(self, key, value):
        self._data[key] = value


def make_scheduler(total_count=None, max_daily=None):
    sched = Scheduler(event_bus=EventBus(), config=None, state_manager=None, store=None)
    sched._tasks["t"] = TaskConfig(
        name="t", repeat=RepeatConfig(type="daily", value=1),
        total_count=total_count, max_daily=max_daily)
    sched._next_run["t"] = datetime.now()  # 初始调度时间（达上限时会被清空）
    return sched


def run_battle(rc, sched, total_count, max_battles):
    """构造带真实回调链路的 BattleLoop 执行，返回 (result, holder)。"""
    evt = rc._cycle_limit_events.setdefault("t", threading.Event())
    holder = {"completed": 0}
    def saver(task_id, completed, total):
        holder["completed"] = completed
        rc._on_task_progress(task_id, completed, total)  # 真实回调：写盘 + record_cycle
    ctx = SimpleNamespace(
        task_id="t", task_name="t",
        stop_event=threading.Event(),
        cycle_limit_event=evt,
        state={},
        progress_saver=saver,
    )
    loop = BattleLoop(params={"max_battles": max_battles, "wait_time": 0})
    return loop.execute(ctx), holder


def main():
    print("活动循环次数达上限 → 立即中断任务收尾")
    from core.run_controller import RunController

    # ═══ 测试 1：BattleLoop 纯单元——达上限立即中断 ═══
    print("\n[1/3] BattleLoop 达上限立即中断（纯单元）")
    evt = threading.Event()
    holder = {"completed": 0}
    def saver1(task_id, completed, total):
        holder["completed"] = completed
        if completed >= 5:
            evt.set()  # 模拟第 5 场后 record_cycle 达上限 → set event
    ctx1 = SimpleNamespace(
        task_id="t", task_name="t",
        stop_event=threading.Event(),
        cycle_limit_event=evt,
        state={}, progress_saver=saver1,
    )
    r1 = BattleLoop(params={"max_battles": 10, "wait_time": 0}).execute(ctx1)
    check("达上限 → 返回 SUCCESS（成功收尾）",
          r1.status == StepStatus.SUCCESS,
          f"status={r1.status} msg={r1.message}")
    check("达上限 → 只完成 5 场（不超额）",
          holder["completed"] == 5, f"completed={holder['completed']}")

    # ═══ 测试 2：RunController 全链路联动 ═══
    print("\n[2/3] RunController 全链路（record_cycle → set event → BattleLoop 中断）")
    sched2 = make_scheduler(total_count=3)
    rc2 = RunController(scheduler=sched2, state_mgr=FakeStateMgr(), event_bus=EventBus())
    r2, h2 = run_battle(rc2, sched2, total_count=3, max_battles=10)
    check("活动循环上限=3 → 只完成 3 场即中断",
          h2["completed"] == 3, f"completed={h2['completed']}")
    check("中断返回 SUCCESS（收尾，不算失败）",
          r2.status == StepStatus.SUCCESS, f"status={r2.status} msg={r2.message}")
    check("调度器已标记永久完成（失效区）",
          sched2.task_status.get("t") == ScheduleStatus.COMPLETED
          and "t" not in sched2._next_run,
          f"status={sched2.task_status.get('t')} next={sched2._next_run.get('t')}")

    # ═══ 测试 3：回归保障——未达上限正常跑满 ═══
    print("\n[3/3] 未达上限时正常跑满 max_battles（回归保障）")
    sched3 = make_scheduler(total_count=None)  # 不限循环次数
    rc3 = RunController(scheduler=sched3, state_mgr=FakeStateMgr(), event_bus=EventBus())
    r3, h3 = run_battle(rc3, sched3, total_count=None, max_battles=4)
    check("无上限 → 跑满 4 场",
          h3["completed"] == 4 and r3.status == StepStatus.SUCCESS,
          f"completed={h3['completed']} status={r3.status}")
    check("无上限 → 调度器仍正常调度",
          sched3.task_status.get("t") != ScheduleStatus.COMPLETED
          or "t" in sched3._next_run,
          f"status={sched3.task_status.get('t')} next={sched3._next_run.get('t')}")

    # ═══ 测试 4：上限 > max_battles 时按 max_battles 跑（上限未触达） ═══
    print("\n[4/4] 上限大于单次循环数 → 按 max_battles 跑（上限未触达不中断）")
    sched4 = make_scheduler(total_count=100)
    rc4 = RunController(scheduler=sched4, state_mgr=FakeStateMgr(), event_bus=EventBus())
    r4, h4 = run_battle(rc4, sched4, total_count=100, max_battles=6)
    check("上限100 > 单次6场 → 跑满 6 场（不中断）",
          h4["completed"] == 6 and r4.status == StepStatus.SUCCESS,
          f"completed={h4['completed']} status={r4.status}")
    check("未达上限 → 任务保持可调度",
          sched4._next_run.get("t") is not None,
          f"next={sched4._next_run.get('t')}")

    print(f"\n🎉 活动循环次数达上限立即中断收尾验证 {PASS} 项通过"
          + ("" if FAIL == 0 else f"，失败 {FAIL} 项"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
