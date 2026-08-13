"""验证：活动有效期 active_range（UI 收集 + 调度语义）+ 表单收集分支。

覆盖（子代理审计缺口 #1/#9/#10）：
  A. UI 收集：起止日期 → active_range=[s,e]；留空 → None；trigger 类型强制 None
  B. 调度语义：活动期内 is_due=True；开始前 is_due=False；结束后失效进失效区
  C. 表单收集分支：enabled / priority / 1时段→time_start-end / 2时段→time_slots /
     max_daily=0→None / 间隔值→repeat.value
"""
import os, sys
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

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


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from core.scheduler import Scheduler, TaskConfig, RepeatConfig, ScheduleStatus, TZ_UTC8
    from ui.panels.game_task_panel import GameTaskPanel

    # ═══ A. UI 收集：active_range ═══
    print("\n[A] 活动有效期 UI 收集")

    class FakeBridge:
        def __init__(self, rtype="daily"):
            self.task = SimpleNamespace(
                get_task_detail=lambda n: {
                    "name": n, "display_name": n, "task_type": "daily",
                    "uses_battle": False, "uses_team": False, "uses_soul": False,
                    "uses_stamina": False, "enabled": True,
                    "repeat": {"type": rtype, "value": 1, "loop_count": 1},
                    "time_start": "06:00", "time_end": "23:59", "time_slots": None,
                    "active_range": None, "max_daily": 0, "total_count": None,
                    "priority": 10, "next_run_time": "",
                },
                get_next_run_time=lambda n: None,
                get_cycle_progress=lambda n: (0, None),
            )

    panel = GameTaskPanel(param_bridge=FakeBridge("daily"))
    panel.load_tasks([{"name": "t", "display_name": "t", "task_type": "daily",
                       "uses_battle": False}])
    panel.task_list.setCurrentRow(0)
    w = panel._form_widgets

    # 填起止日期 → 收集 active_range
    w["active_range_start"].setText("2026-07-20")
    w["active_range_end"].setText("2026-08-20")
    cfg = panel._collect_config()
    check("A1 填起止日期 → active_range=[s,e]",
          cfg.get("active_range") == ["2026-07-20", "2026-08-20"], str(cfg.get("active_range")))

    # 留空 → 不写字段
    w["active_range_start"].setText("")
    w["active_range_end"].setText("")
    cfg2 = panel._collect_config()
    check("A2 留空 → active_range=None", cfg2.get("active_range") is None,
          str(cfg2.get("active_range")))

    # 只填开始日期 → [s, None]
    w["active_range_start"].setText("2026-07-20")
    w["active_range_end"].setText("")
    cfg3 = panel._collect_config()
    check("A3 只填开始 → [s, None]", cfg3.get("active_range") == ["2026-07-20", None],
          str(cfg3.get("active_range")))

    # trigger 类型强制 None
    panel2 = GameTaskPanel(param_bridge=FakeBridge("trigger"))
    panel2.load_tasks([{"name": "t2", "display_name": "t2", "task_type": "daily",
                        "uses_battle": False}])
    panel2.task_list.setCurrentRow(0)
    w2 = panel2._form_widgets
    w2["active_range_start"].setText("2026-07-20")
    w2["active_range_end"].setText("2026-08-20")
    cfg4 = panel2._collect_config()
    check("A4 trigger 类型 → active_range 强制 None",
          cfg4.get("active_range") is None, str(cfg4.get("active_range")))

    # ═══ B. 调度语义：active_range ═══
    print("\n[B] 活动有效期调度语义")
    sched = Scheduler(config=None, store=None)
    now = datetime(2026, 8, 10, 10, 0, tzinfo=TZ_UTC8)

    # 期内 (07-20 ~ 08-20)：is_due True
    cfg_in = TaskConfig(name="t_in", repeat=RepeatConfig(type="daily", value=1),
                        active_range=["2026-07-20", "2026-08-20"], time_start="06:00")
    sched._tasks["t_in"] = cfg_in
    sched._next_run["t_in"] = datetime(2026, 8, 10, 9, 0, tzinfo=TZ_UTC8)
    check("B1 活动期内 → is_due=True", sched.is_due("t_in", now), "")

    # 开始前 (09-01 起)：is_due False
    cfg_before = TaskConfig(name="t_before", repeat=RepeatConfig(type="daily", value=1),
                            active_range=["2026-09-01", "2026-09-10"], time_start="06:00")
    sched._tasks["t_before"] = cfg_before
    sched._next_run["t_before"] = datetime(2026, 8, 10, 9, 0, tzinfo=TZ_UTC8)
    check("B2 活动期开始前 → is_due=False", not sched.is_due("t_before", now), "")

    # 结束后 (01-01 ~ 01-10)：is_due False + 失效区
    cfg_after = TaskConfig(name="t_after", repeat=RepeatConfig(type="daily", value=1),
                           active_range=["2026-01-01", "2026-01-10"], time_start="06:00")
    sched._tasks["t_after"] = cfg_after
    sched._next_run["t_after"] = datetime(2026, 8, 10, 9, 0, tzinfo=TZ_UTC8)
    check("B3 活动期结束后 → is_due=False", not sched.is_due("t_after", now), "")
    reason = sched._invalid_reason(cfg_after, now, "2026-08-10")
    check("B4 活动期结束后 → _invalid_reason 已过期", reason == "已过期", str(reason))
    invalid = sched.get_invalid_tasks()
    check("B5 结束的任务进入失效区",
          any(t["name"] == "t_after" for t in invalid),
          str([t["name"] for t in invalid]))

    # 结束后 build_schedule → 不 DUE
    due = sched.build_schedule(publish=False)
    check("B6 结束的任务不进待执行", "t_after" not in [t.name for t in due],
          str([t.name for t in due]))

    # ═══ C. 表单收集分支 ═══
    print("\n[C] 表单收集分支")
    panel._render_form({
        "name": "t", "display_name": "t", "task_type": "daily",
        "uses_battle": False, "uses_team": False, "uses_soul": False,
        "uses_stamina": False, "enabled": True,
        "repeat": {"type": "daily", "value": 1, "loop_count": 1},
        "time_start": "06:00", "time_end": "12:00", "time_slots": None,
        "active_range": None, "max_daily": 0, "total_count": None,
        "priority": 10, "next_run_time": "",
    })
    wc = panel._form_widgets
    # enabled
    wc["enabled"].setChecked(False)
    c1 = panel._collect_config()
    check("C1 enabled=False 收集", c1.get("enabled") is False, str(c1.get("enabled")))
    wc["enabled"].setChecked(True)
    c2 = panel._collect_config()
    check("C2 enabled=True 收集", c2.get("enabled") is True, str(c2.get("enabled")))
    # priority
    wc["priority"].setValue(42)
    check("C3 priority=42 收集", panel._collect_config().get("priority") == 42,
          str(panel._collect_config().get("priority")))
    # max_daily=0 → None（不限）
    wc["max_daily"].setValue(0)
    check("C4 max_daily=0 → None", panel._collect_config().get("max_daily") is None,
          str(panel._collect_config().get("max_daily")))
    wc["max_daily"].setValue(5)
    check("C5 max_daily=5 → 5", panel._collect_config().get("max_daily") == 5,
          str(panel._collect_config().get("max_daily")))
    # 1 时段 → time_start/time_end
    c6 = panel._collect_config()
    check("C6 单时段 → time_start/end", c6.get("time_start") == "06:00"
          and c6.get("time_end") == "12:00" and c6.get("time_slots") is None,
          str({k: c6.get(k) for k in ("time_start", "time_end", "time_slots")}))
    # 2 时段 → time_slots
    panel._add_slot_row("14:00", "16:00")
    c7 = panel._collect_config()
    check("C7 双时段 → time_slots=[[..],[..]]",
          c7.get("time_slots") == [["06:00", "12:00"], ["14:00", "16:00"]]
          and c7.get("time_start") is None,
          str(c7.get("time_slots")))
    # interval_days → repeat.value
    panel._render_form({
        "name": "t", "display_name": "t", "task_type": "daily",
        "uses_battle": False, "uses_team": False, "uses_soul": False,
        "uses_stamina": False, "enabled": True,
        "repeat": {"type": "interval_days", "value": 3, "loop_count": 1},
        "time_start": "06:00", "time_end": "23:59", "time_slots": None,
        "active_range": None, "max_daily": 0, "total_count": None,
        "priority": 10, "next_run_time": "",
    })
    wd = panel._form_widgets
    wd["interval"].setValue(7)
    c8 = panel._collect_config()
    check("C8 interval_days=7 → repeat.value=7", c8["repeat"].get("value") == 7,
          str(c8["repeat"]))

    print(f"\n🎉 活动有效期 + 表单收集分支验证 {PASS} 项通过"
          + ("" if FAIL == 0 else f"，失败 {FAIL} 项"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
