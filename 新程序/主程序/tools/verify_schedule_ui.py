"""验证：重复规则单选按钮组联动显隐 + 时段/间隔/周期最大触发次数调度推进。

UI：
  ① 单选按钮组存在、各类型可选、切换联动
  ② weekly → 每周几显示；daily → 隐藏
  ③ interval_days → 间隔值显示 + label"间隔值(天):"
  ④ interval_hours → label"间隔值(小时):"
  ⑤ daily → 时段显示；trigger → 时段隐藏、触发信号显示
  ⑥ 周期最大触发次数（max_daily）所有类型显示（含 trigger）
调度：
  ⑦ _dt_in_any_slot 时段判定
  ⑧ 时段+间隔推进：12:00-14:00,16:00-20:00 + 间隔1h → 12:00→13:00→14:00→16:00→17:00
  ⑨ 无间隔 per_slot + max_daily=2：10:00→12:00，12:00 后达上限 → 次日、COMPLETED
  ⑩ trigger 拦截读 max_daily
"""
import os, sys, time
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


def build_raw(name, rtype="daily", loop=1, max_daily=None, slots=None,
              interval=None, trigger_max=None):
    repeat = {"type": rtype, "value": interval or 1, "loop_count": loop}
    if rtype == "trigger":
        repeat["trigger_templates"] = ["sig_a"]
        if trigger_max is not None:
            repeat["trigger_max_count"] = trigger_max
    return SimpleNamespace(
        name=name, display_name=name, category="daily", enabled=True,
        priority=10, time_start=slots[0][0] if slots else "06:00",
        time_end=slots[0][1] if slots else "23:59",
        max_daily=max_daily, active_range=None, total_count=None,
        execution_mode="per_slot", loop_count=loop, time_slots=slots,
        max_fail_streak=10, repeat=repeat,
    )


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from core.event_bus import EventBus
    from core.scheduler import Scheduler, ScheduleStatus, TZ_UTC8

    bus = EventBus()

    # ═══ UI：单选按钮组联动 ═══
    from ui.panels.game_task_panel import GameTaskPanel, REPEAT_TYPES

    class FakeBridge:
        def __init__(self, rtype="daily"):
            self.task = SimpleNamespace(
                get_task_detail=lambda n: {
                    "name": n, "display_name": n, "task_type": "daily",
                    "uses_battle": False, "uses_team": False, "uses_soul": False,
                    "uses_stamina": False, "enabled": True,
                    "repeat": {"type": rtype, "value": 1, "loop_count": 1},
                    "time_start": "06:00", "time_end": "23:59", "time_slots": None,
                    "active_range": None, "max_daily": 3, "total_count": None,
                    "execution_mode": "daily", "loop_count": 1, "priority": 10,
                    "next_run_time": "",
                },
                get_next_run_time=lambda n: None,
            )

    panel = GameTaskPanel(param_bridge=FakeBridge("daily"))
    panel.load_tasks([{"name": "t", "display_name": "t", "task_type": "daily",
                       "uses_battle": False}])
    panel.task_list.setCurrentRow(0)

    radios = panel._form_widgets["repeat_type"]
    w = panel._form_widgets
    combo = panel._form_widgets["repeat_type"]
    types = [combo.itemData(i) for i in range(combo.count())]
    check("① 下拉含全部类型", all(t in types for t in
        ["daily", "weekly", "interval_days", "interval_hours", "on_enter",
         "once", "trigger"]), str(types))
    check("① 默认选中 daily", panel._current_repeat_type() == "daily")

    def _pick(t):
        combo.setCurrentIndex(combo.findData(t))

    # ② weekly → 每周几显示
    _pick("weekly")
    check("② weekly 每周几显示", not w["weekday"].isHidden()
          and not w["weekday_label"].isHidden())
    check("② weekly 间隔值隐藏", w["interval"].isHidden())

    # ③ interval_days → 间隔值显示 + label
    _pick("interval_days")
    check("③ interval_days 间隔值显示", not w["interval"].isHidden()
          and "天" in w["interval_label"].text(), w["interval_label"].text())

    # ④ interval_hours → label 小时
    _pick("interval_hours")
    check("④ interval_hours label 小时", "小时" in w["interval_label"].text(),
          w["interval_label"].text())

    # ⑤ daily → 时段显示；trigger → 时段隐藏 + 触发信号显示
    _pick("daily")
    check("⑤ daily 时段显示", not w["slot_label"].isHidden())
    _pick("trigger")
    check("⑤ trigger 时段隐藏", w["slot_label"].isHidden())
    check("⑤ trigger 触发信号显示", not w["trigger_templates"].isHidden())

    # ⑥ 周期最大触发次数所有类型显示（含 trigger）
    check("⑥ trigger 周期最大次数显示", not w["max_daily"].isHidden())
    _pick("on_enter")
    check("⑥ on_enter 周期最大次数显示", not w["max_daily"].isHidden())

    # ═══ 调度：时段 + 间隔 + 周期次数 ═══
    import core.scheduler as sch

    # ⑦ _dt_in_any_slot
    fake_cfg7 = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[
        build_raw("t7", slots=[["12:00", "14:00"], ["16:00", "20:00"]])]))
    sched7 = Scheduler(event_bus=bus, config=fake_cfg7, state_manager=None, store=None)
    sched7.load_tasks_from_config()
    cfg7 = sched7._tasks["t7"]
    check("⑦ 12:30 在时段内", sched7._dt_in_any_slot(
        cfg7, datetime(2026, 8, 10, 12, 30, tzinfo=TZ_UTC8)))
    check("⑦ 15:00 不在时段内", not sched7._dt_in_any_slot(
        cfg7, datetime(2026, 8, 10, 15, 0, tzinfo=TZ_UTC8)))

    # ⑧ 时段+间隔推进（interval_hours=1）
    fixed = {"dt": datetime(2026, 8, 10, 12, 0, tzinfo=TZ_UTC8)}
    def _fake_now(cls, tz=None):
        return fixed["dt"].replace(tzinfo=tz or fixed["dt"].tzinfo)
    orig_now = sch.datetime
    sch.datetime = type("FD", (sch.datetime,), {"now": classmethod(_fake_now)})
    try:
        fake_cfg8 = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[
            build_raw("t8", rtype="interval_hours", interval=1,
                      slots=[["12:00", "14:00"], ["16:00", "20:00"]])]))
        sched8 = Scheduler(event_bus=bus, config=fake_cfg8, state_manager=None, store=None)
        sched8.load_tasks_from_config()
        sched8._today_count["t8"] = 0

        seq = []
        fixed["dt"] = datetime(2026, 8, 10, 12, 0, tzinfo=TZ_UTC8)  # 12:00
        sched8.mark_done("t8", True)
        n1 = sched8._next_run["t8"]
        seq.append(n1.strftime("%H:%M"))
        fixed["dt"] = n1
        sched8.mark_done("t8", True)
        n2 = sched8._next_run["t8"]
        seq.append(n2.strftime("%H:%M"))
        fixed["dt"] = n2
        sched8.mark_done("t8", True)
        n3 = sched8._next_run["t8"]
        seq.append(n3.strftime("%H:%M"))
        fixed["dt"] = n3
        sched8.mark_done("t8", True)
        n4 = sched8._next_run["t8"]
        seq.append(n4.strftime("%H:%M"))
        check("⑧ 时段内间隔推进 13:00→14:00→16:00→17:00",
              seq == ["13:00", "14:00", "16:00", "17:00"], str(seq))

        # ⑨ 无间隔 per_slot + max_daily=2（周期触发总量）：10:00→12:00，12:00 后达上限 → 永久完成
        fake_cfg9 = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[
            build_raw("t9", max_daily=2,
                      slots=[["10:00", "12:00"], ["12:00", "14:00"]])]))
        sched9 = Scheduler(event_bus=bus, config=fake_cfg9, state_manager=None, store=None)
        sched9.load_tasks_from_config()
        sched9._today_count["t9"] = 0
        fixed["dt"] = datetime(2026, 8, 10, 10, 0, tzinfo=TZ_UTC8)
        sched9.mark_done("t9", True)  # 触发累计=1
        p1 = sched9._next_run["t9"]
        check("⑨ 10:00 执行 → 下一时段 12:00", p1.strftime("%H:%M") == "12:00",
              p1.strftime("%H:%M"))
        fixed["dt"] = p1
        sched9.mark_done("t9", True)  # 触发累计=2 达上限（周期触发总量）
        st9 = sched9.task_status["t9"]
        check("⑨ 12:00 执行(满2次触发) → 永久完成(失效区)",
              st9 == ScheduleStatus.COMPLETED
              and "t9" not in sched9._next_run,
              f"status={st9} next={sched9._next_run.get('t9')}")

        # ⑩ trigger 拦截读 max_daily
        fake_cfg10 = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[
            build_raw("t10", rtype="trigger", max_daily=2)]))
        sched10 = Scheduler(event_bus=bus, config=fake_cfg10, state_manager=None, store=None)
        sched10.load_tasks_from_config()
        sched10._today_count["t10"] = 2  # 已触发 2 次
        sched10.update_next_run("t10", datetime.now(TZ_UTC8))
        check("⑩ trigger 达 max_daily 拦截", "t10" not in sched10._next_run
              and "已达周期上限" in (sched10._defer_reasons.get("t10") or ""),
              str(sched10._next_run))
    finally:
        sch.datetime = orig_now

    # ═══ ⑪-⑭ 执行模式冲突修复（UI） ═══
    from ui.panels.game_task_panel import GameTaskPanel as GTP
    panel2 = GTP(param_bridge=FakeBridge("daily"))
    panel2.load_tasks([{"name": "t", "display_name": "t", "task_type": "daily",
                        "uses_battle": False}])
    panel2.task_list.setCurrentRow(0)
    combo2 = panel2._form_widgets["repeat_type"]
    w2 = panel2._form_widgets

    def _detail(rtype="daily", slots=None):
        return {
            "name": "t", "display_name": "t", "task_type": "daily",
            "uses_battle": False, "uses_team": False, "uses_soul": False,
            "uses_stamina": False, "enabled": True,
            "repeat": {"type": rtype, "value": 1, "loop_count": 3},
            "time_start": slots[0][0] if slots else "06:00",
            "time_end": slots[0][1] if slots else "23:59",
            "time_slots": slots, "active_range": None,
            "max_daily": 3, "total_count": None,
            "execution_mode": "daily", "loop_count": 3, "priority": 10,
            "next_run_time": "",
        }

    # ⑪ 执行模式已移除：UI 无 execution_mode 控件
    panel2._render_form(_detail(rtype="daily", slots=[["10:00", "12:00"], ["12:00", "14:00"]]))
    check("⑪ UI 已移除执行模式", "execution_mode" not in panel2._form_widgets
          and "execution_mode_label" not in panel2._form_widgets,
          str(list(panel2._form_widgets.keys())[:30]))

    # ⑫ 循环次数控件存在（更名自「每轮循环/每次执行轮数」）
    check("⑫ 循环次数控件存在", panel2._form_widgets.get("loop_count") is not None)

    # ⑬ loop_count 单存（只 repeat 内）+ 不写 execution_mode
    panel2._render_form(_detail(rtype="daily", slots=[["06:00", "12:00"]]))
    cfg = panel2._collect_config()
    check("⑬ config 无顶层 loop_count", "loop_count" not in cfg, str(cfg))
    check("⑬ repeat 内有 loop_count", cfg["repeat"].get("loop_count") == 3,
          str(cfg["repeat"]))
    check("⑬ config 无 execution_mode", "execution_mode" not in cfg, str(cfg))

    # ⑭ 调度层：无 execution_mode 字段的多时段任务仍每时段一次（per_slot 行为）
    fake_cfg14 = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[
        build_raw("t14", slots=[["10:00", "12:00"], ["14:00", "16:00"]])]))
    sched14 = Scheduler(event_bus=bus, config=fake_cfg14, state_manager=None, store=None)
    sched14.load_tasks_from_config()
    sched14._today_count["t14"] = 0
    fixed14 = datetime(2026, 8, 10, 12, 0, tzinfo=TZ_UTC8)
    import core.scheduler as sch2
    orig2 = sch2.datetime
    def _fake2(cls, tz=None):
        return fixed14.replace(tzinfo=tz or fixed14.tzinfo)
    sch2.datetime = type("FD", (sch2.datetime,), {"now": classmethod(_fake2)})
    try:
        sched14.mark_done("t14", True)
        nrt = sched14._next_run["t14"]
        check("⑭ 多时段无执行模式仍每时段一次",
              nrt.strftime("%H:%M") == "14:00", nrt.strftime("%H:%M"))
    finally:
        sch2.datetime = orig2

    # ═══ ⑮⑯ 周期触发次数 / 活动循环次数（新语义） ═══
    # ⑮ 活动循环次数：record_cycle 每轮 +1，达上限 → 永久完成（失效区）
    from core.scheduler import TaskConfig as TC15, RepeatConfig as RC15
    fake_cfg15 = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[
        TC15(name="t15", repeat=RC15(type="daily", value=1), total_count=2)]))
    sched15 = Scheduler(event_bus=bus, config=fake_cfg15, state_manager=None, store=None)
    sched15.load_tasks_from_config()
    sched15._today_count["t15"] = 0
    check("⑮ 循环1次未达上限",
          sched15.record_cycle("t15", 1) is False
          and sched15._total_count.get("t15") == 1)
    check("⑮ 循环2次达上限 → 永久完成",
          sched15.record_cycle("t15", 1) is True
          and "t15" not in sched15._next_run
          and sched15.task_status.get("t15") == ScheduleStatus.COMPLETED,
          f"next={sched15._next_run.get('t15')} "
          f"status={sched15.task_status.get('t15')}")
    # 触发累计与循环累计互不干扰：mark_done 只加触发，record_cycle 只加循环
    sched15._today_count["t15"] = 0
    sched15._total_count["t15"] = 0
    sched15._next_run["t15"] = datetime(2026, 8, 10, 12, 0, tzinfo=TZ_UTC8)
    sched15.mark_done("t15", True)
    check("⑮ mark_done 只累计触发次数",
          sched15._today_count.get("t15") == 1 and sched15._total_count.get("t15") == 0)

    # ⑯ UI：周期触发次数/活动循环次数更名 + 死控件移除 + 累计显示
    panel2._render_form(_detail(rtype="daily", slots=[["06:00", "12:00"]]))
    w3 = panel2._form_widgets
    check("⑯ 死控件 trigger_max_count 已移除",
          "trigger_max_count" not in w3 and "trigger_max_label" not in w3,
          str([k for k in w3 if "trigger_max" in k]))
    check("⑯ 周期触发次数控件存在",
          w3.get("max_daily") is not None
          and w3.get("max_daily_label").text() == "周期触发次数:")
    check("⑯ 活动循环次数控件存在(含累计显示)",
          w3.get("total_count") is not None
          and w3.get("total_label").text() == "活动循环次数:"
          and w3.get("cycle_done_label") is not None)
    cfg16 = panel2._collect_config()
    check("⑯ total_count 所有类型保存(含 trigger)",
          "total_count" in cfg16,
          str(cfg16.get("total_count")))
    # trigger 类型也保存活动循环次数
    panel2._render_form(_detail(rtype="trigger", slots=None))
    w4 = panel2._form_widgets
    w4["total_count"].setValue(50)
    cfg16b = panel2._collect_config()
    check("⑯ trigger 类型 total_count 保存",
          cfg16b.get("total_count") == 50, str(cfg16b.get("total_count")))

    # ═══ ⑰⑱⑲ 重复规则选项清理验证 ═══
    # ⑰ special 已从下拉移除（与 daily 重复）
    cur_types = [combo2.itemData(i) for i in range(combo2.count())]
    check("⑰ special 已移除", "special" not in cur_types,
          str(cur_types))

    # ⑱ monthly_start：控件显示 + 保存 + 调度透传 monthly_day
    panel2._render_form(_detail(rtype="monthly_start", slots=[["06:00", "12:00"]]))
    wm = panel2._form_widgets
    check("⑱ monthly_start 每月几号控件可见",
          wm.get("monthly_day") is not None and not wm["monthly_day"].isHidden(),
          str(wm.get("monthly_day")))
    wm["monthly_day"].setValue(15)
    cfgm = panel2._collect_config()
    check("⑱ 保存 monthly_day=15", cfgm["repeat"].get("monthly_day") == 15,
          str(cfgm["repeat"]))
    # 调度透传：monthly_day=15 → 窗口前(02:00)初始 next_run 为本月 15 号 06:00
    import core.scheduler as sch18
    orig18 = sch18.datetime
    fixed18 = {"dt": datetime(2026, 8, 10, 2, 0, tzinfo=TZ_UTC8)}
    def _fake18(cls, tz=None):
        return fixed18["dt"].replace(tzinfo=tz or fixed18["dt"].tzinfo)
    sch18.datetime = type("FD", (sch18.datetime,), {"now": classmethod(_fake18)})
    try:
        fake_cfg18 = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[
            TC15(name="t18", repeat=RC15(type="monthly_start", value=1, monthly_day=15),
                 time_start="06:00")]))
        sched18 = Scheduler(event_bus=bus, config=fake_cfg18, state_manager=None, store=None)
        sched18.load_tasks_from_config()
        nrt18 = sched18._next_run["t18"]
        check("⑱ 调度透传 monthly_day=15 → 本月15号06:00",
              nrt18 is not None and nrt18.month == 8 and nrt18.day == 15
              and nrt18.strftime("%H:%M") == "06:00", str(nrt18))
    finally:
        sch18.datetime = orig18

    # ⑲ expire_at 已从下拉移除（用 active_range + interval_hours 替代；代码保留兼容旧配置）
    cur_types19 = [combo2.itemData(i) for i in range(combo2.count())]
    check("⑲ expire_at 已移除", "expire_at" not in cur_types19, str(cur_types19))

    print(f"\n🎉 重复规则下拉 + 调度推进 + 执行模式移除 + 计数语义 + 选项清理验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
