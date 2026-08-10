"""调查：执行模式（execution_mode: daily/per_slot）在各重复规则下是否真正影响任务执行。

方法：monkeypatch datetime.now 固定时刻，对比 daily vs per_slot 的 mark_done 推进。

场景：
  A. 单时段 time_slots（1 个时段）→ 预期 daily/per_slot 推进相同
  B. 多时段 time_slots（2+ 时段、无间隔）→ 预期不同（per_slot=下一时段；daily=次日）
     ——但 UI 已强制多时段=per_slot（用户无法选 daily）
  C. 无 time_slots（time_start/time_end 形式）→ 走 RepeatRule，execution_mode 不读
  D. 多时段 + interval_hours 间隔 → interval 优先，execution_mode 不读
  E. on_enter / once / trigger → execution_mode 不读（且 UI 已隐藏）
"""
import os, sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL: {label}  {detail}"
    PASS += 1
    print(f"PASS {label}")


def build_raw(name, rtype="daily", mode="daily", slots=None, interval=None):
    """slots: time_slots 列表；interval: 重复类型值（interval_hours）"""
    repeat = {"type": rtype, "value": interval or 1, "loop_count": 1}
    return SimpleNamespace(
        name=name, display_name=name, category="daily", enabled=True,
        priority=10, time_start=slots[0][0] if slots else "06:00",
        time_end=slots[0][1] if slots else "23:59",
        max_daily=None, active_range=None, total_count=None,
        execution_mode=mode, loop_count=1,
        time_slots=slots, max_fail_streak=10, repeat=repeat,
    )


def run_scenario(bus, task_raw, now_dt):
    """构造 scheduler + 固定 now，执行 mark_done，返回 next_run"""
    import core.scheduler as sch
    fake_cfg = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[task_raw]))
    sched = sch.Scheduler(event_bus=bus, config=fake_cfg, state_manager=None, store=None)
    sched.load_tasks_from_config()
    sched._today_count[task_raw.name] = 0
    fixed = {"dt": now_dt}
    def _fake_now(cls, tz=None):
        return fixed["dt"].replace(tzinfo=tz or fixed["dt"].tzinfo)
    orig = sch.datetime
    sch.datetime = type("FD", (sch.datetime,), {"now": classmethod(_fake_now)})
    try:
        sched._next_run[task_raw.name] = now_dt
        sched.mark_done(task_raw.name, True)
        nrt = sched._next_run.get(task_raw.name)
        return sched, (nrt.strftime("%m-%d %H:%M") if nrt else None)
    finally:
        sch.datetime = orig


def main():
    from core.event_bus import EventBus
    from core.scheduler import TZ_UTC8

    bus = EventBus()
    now12 = datetime(2026, 8, 10, 12, 0, tzinfo=TZ_UTC8)   # 12:00（时段内）
    now1130 = datetime(2026, 8, 10, 11, 30, tzinfo=TZ_UTC8)  # 11:30（单时段内）

    print("═" * 60)
    print("A. 单时段 time_slots [10:00-12:00]，11:30 执行完成")
    print("═" * 60)
    _, n_daily = run_scenario(bus, build_raw("a_d", slots=[["10:00", "12:00"]]), now1130)
    _, n_per = run_scenario(bus, build_raw("a_p", mode="per_slot",
                                           slots=[["10:00", "12:00"]]), now1130)
    print(f"  daily  → {n_daily}")
    print(f"  per_slot → {n_per}")
    check("A. 单时段 daily/per_slot 推进相同", n_daily == n_per, f"{n_daily} vs {n_per}")

    print()
    print("═" * 60)
    print("B. 多时段 [10:00-12:00,14:00-16:00]，12:00 执行完成")
    print("═" * 60)
    sched_b, n_daily = run_scenario(bus, build_raw("b_d",
                                                   slots=[["10:00", "12:00"], ["14:00", "16:00"]]), now12)
    _, n_per = run_scenario(bus, build_raw("b_p", mode="per_slot",
                                           slots=[["10:00", "12:00"], ["14:00", "16:00"]]), now12)
    print(f"  daily  → {n_daily}（次日首时段）")
    print(f"  per_slot → {n_per}（下一时段）")
    check("B. 多时段 daily/per_slot 不同", n_daily != n_per, f"{n_daily} vs {n_per}")
    print("  ⚠ 但 UI 已强制多时段=per_slot 并禁用切换 → 用户实际无法选 daily")

    print()
    print("═" * 60)
    print("C. 无 time_slots（time_start/end 单时段），11:30 执行完成")
    print("═" * 60)
    _, n_daily = run_scenario(bus, build_raw("c_d"), now1130)
    _, n_per = run_scenario(bus, build_raw("c_p", mode="per_slot"), now1130)
    print(f"  daily  → {n_daily}")
    print(f"  per_slot → {n_per}")
    check("C. 无 time_slots 推进相同（走 RepeatRule，不读 execution_mode）",
          n_daily == n_per, f"{n_daily} vs {n_per}")

    print()
    print("═" * 60)
    print("D. 多时段 + interval_hours 间隔，12:00 执行完成")
    print("═" * 60)
    _, n_daily = run_scenario(bus, build_raw("d_d", rtype="interval_hours", interval=1,
                                             slots=[["10:00", "12:00"], ["14:00", "16:00"]]), now12)
    _, n_per = run_scenario(bus, build_raw("d_p", rtype="interval_hours", mode="per_slot",
                                           interval=1, slots=[["10:00", "12:00"], ["14:00", "16:00"]]), now12)
    print(f"  daily  → {n_daily}")
    print(f"  per_slot → {n_per}")
    check("D. 配间隔后 daily/per_slot 相同（interval 优先，不读 execution_mode）",
          n_daily == n_per, f"{n_daily} vs {n_per}")

    print()
    print("═" * 60)
    print("E. on_enter / once / trigger（无时间调度）")
    print("═" * 60)
    for rtype in ("on_enter", "once", "trigger"):
        _, n_daily = run_scenario(bus, build_raw(f"e_{rtype}", rtype=rtype), now12)
        _, n_per = run_scenario(bus, build_raw(f"e_{rtype}_p", rtype=rtype, mode="per_slot"), now12)
        same = n_daily == n_per
        print(f"  {rtype}: daily={n_daily} per_slot={n_per} → {'相同' if same else '不同'}")
        check(f"E. {rtype} 不读 execution_mode", same, f"{n_daily} vs {n_per}")

    print(f"\n🎉 执行模式影响调查 {PASS} 项通过")


if __name__ == "__main__":
    main()
