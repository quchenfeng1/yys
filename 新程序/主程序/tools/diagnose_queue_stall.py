"""诊断复现：运行中「未开始」任务到期后是否被自动推入待执行队列。

模拟真实链路：Scheduler 加载 tasks.yaml → build_schedule 判定 DUE → filler 入队。

场景：
  A. daily 任务 next_run=过去（已到期、窗口内）→ 应 DUE
  B. daily 任务 next_run=未来（未开始）→ WAITING；模拟"到期"（改到过去）→ 应 DUE
  C. on_enter 任务（once_test）初始 next_run 计算
  D. filler 线程实际拾取（RunController + fake scheduler 已测过，这里验证真实 Scheduler 的 get_next_task）
"""
import os, sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


def build_raw(name, rtype, **kw):
    base = dict(
        name=name, display_name=name, category="daily", enabled=True,
        priority=10, time_start="06:00", time_end="23:59", max_daily=None,
        active_range=None, total_count=None, execution_mode="daily",
        loop_count=1, time_slots=None,
        repeat={"type": rtype, "value": 1, "loop_count": 1},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def main():
    from core.event_bus import EventBus
    from core.scheduler import Scheduler, ScheduleStatus

    bus = EventBus()
    fake_cfg = SimpleNamespace(
        tasks_config=SimpleNamespace(tasks=[
            build_raw("daily_test", "daily"),
            build_raw("once_test", "on_enter"),
        ])
    )
    sched = Scheduler(event_bus=bus, config=fake_cfg, state_manager=None, store=None)
    sched.load_tasks_from_config()

    now = datetime.now(sched._timezone)

    # ── 初始 next_run 检查 ──
    print("初始 next_run:")
    for name in ("daily_test", "once_test"):
        nrt = sched._next_run.get(name)
        status = sched.task_status.get(name, ScheduleStatus.WAITING)
        print(f"  {name}: next_run={nrt}  status={status}")

    # ═══ A. daily 已到期（next_run 过去、窗口内）→ 应 DUE ═══
    sched._next_run["daily_test"] = now - timedelta(minutes=1)  # 1 分钟前到期
    due = sched.build_schedule(publish=False)
    names = [t.name for t in due]
    print(f"\nA. daily next_run=1分钟前 → due={names}  status={sched.task_status.get('daily_test')}")
    ok_a = "daily_test" in names

    # ═══ B. daily 未开始 → 到期 → 应 DUE ═══
    sched._next_run["daily_test"] = now + timedelta(hours=1)  # 未开始
    due = sched.build_schedule(publish=False)
    print(f"B1. daily next_run=1小时后 → due={[t.name for t in due]}  "
          f"status={sched.task_status.get('daily_test')}")
    sched._next_run["daily_test"] = now - timedelta(minutes=1)  # 模拟到期
    due = sched.build_schedule(publish=False)
    names = [t.name for t in due]
    print(f"B2. 改为1分钟前 → due={names}  status={sched.task_status.get('daily_test')}")
    ok_b = "daily_test" in names

    # ═══ C. on_enter 初始 next_run ═══
    nrt_once = sched._next_run.get("once_test")
    print(f"\nC. on_enter next_run={nrt_once}  status={sched.task_status.get('once_test')}")
    ok_c = nrt_once is not None

    # ═══ D. get_next_task（filler 实际调用） ═══
    sched._next_run["daily_test"] = now - timedelta(minutes=1)
    nt = sched.get_next_task()
    print(f"D. get_next_task → {nt}")
    ok_d = nt == "daily_test"

    print(f"\n结论: A={ok_a} B={ok_b} C={ok_c} D={ok_d}")
    if ok_a and ok_b and ok_d:
        print("→ Scheduler 判定逻辑正常：到期任务能被 build_schedule/get_next_task 拾取")
    else:
        print("→ Scheduler 判定存在异常，需进一步定位")


if __name__ == "__main__":
    main()
