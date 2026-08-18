"""验证：三种任务类型改造（周期断点续跑 / 单次两模式 / 触发周期上限）。

阶段1 周期任务：
  ① _on_task_progress 记录 cycle_date
  ② _update_task_progress 保留周期进度（不清 0）→ 同周期续跑
  ③ _reset_cycle_if_new_day：cycle_date != 今天 → completed=0（跨日重置）
  ④ reset_task_cycle：改配置 → completed=0（下次从第 1 次开始）
阶段2 单次任务：
  ⑤ REPEAT_TYPES 含 on_enter（每次启动执行）/ once（只执行一次）
阶段3 触发任务周期上限：
  ⑥ RepeatConfig.trigger_max_count 从配置加载
  ⑦ 触发达上限 → update_next_run 拦截、标记失效
  ⑧ _invalid_reason 返回"已达上限"、UI 不显示触发按钮
  ⑨ 触发执行后 today_count+1（计数）
"""
import os, sys, time, tempfile
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


def build_raw(name, rtype="daily", loop=100, trigger_max=None):
    repeat = {"type": rtype, "value": 1, "loop_count": loop}
    if rtype == "trigger":
        repeat["trigger_templates"] = ["sig_a"]
        if trigger_max is not None:
            repeat["trigger_max_count"] = trigger_max
    return SimpleNamespace(
        name=name, display_name=name, category="daily", enabled=True,
        priority=10, time_start="06:00", time_end="23:59", max_daily=None,
        active_range=None, total_count=None, execution_mode="daily",
        loop_count=loop, time_slots=None, max_fail_streak=10,
        repeat=repeat,
    )


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from core.event_bus import EventBus
    from core.scheduler import Scheduler, ScheduleStatus
    from core.state_manager import StateManager
    from core.run_controller import RunController
    from core.task_state import TaskStateStore

    bus = EventBus()
    sm = StateManager(event_bus=bus)
    tmpdir = Path(tempfile.mkdtemp(prefix="cycle_tasks_"))

    # ═══ 阶段1：周期任务断点续跑 ═══
    fake_cfg = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[build_raw("daily_x")]))
    store = TaskStateStore(tmpdir / "s.json")
    sched = Scheduler(event_bus=bus, config=fake_cfg, state_manager=sm, store=store)
    sched.load_tasks_from_config()

    ctrl = RunController(
        scheduler=sched, connection=None, config=None, state_mgr=sm,
        registry=None, executor=None, recognizer=None,
        event_bus=bus, monitor=None, account_mgr=None,
        runtime_progress_path=tmpdir / "progress.json",
    )

    # ① _on_task_progress 已退役（2026-08-16）：BattleLoop 随老任务删除，
    #    进度改由 ProgressTracker + VISUAL_PROGRESS 缩略图体系承担，
    #    保留空壳仅兼容旧代码引用（调用无效果）
    progress = sm.get_state("task_runtime_progress", {})
    progress["daily_x"] = {"completed": 20, "total": 100,
                           "cycle_date": datetime.now().strftime("%Y-%m-%d")}
    sm.set_state("task_runtime_progress", progress)
    ctrl._on_task_progress("daily_x", 30, 100)   # 退役空操作
    entry = sm.get_state("task_runtime_progress", {}).get("daily_x", {})
    check("① _on_task_progress 退役空操作（不写进度）",
          entry.get("completed") == 20, str(entry))

    # ② _update_task_progress 保留周期进度（不清 0）
    ctrl._update_task_progress("daily_x", True)
    entry = sm.get_state("task_runtime_progress", {}).get("daily_x", {})
    check("② 任务完成后进度保留(20)", entry.get("completed") == 20, str(entry))

    # ③ 跨日重置
    progress = sm.get_state("task_runtime_progress", {})
    progress["daily_x"]["cycle_date"] = "2000-01-01"  # 模拟昨天
    sm.set_state("task_runtime_progress", progress)
    ctrl._reset_cycle_if_new_day()
    entry = sm.get_state("task_runtime_progress", {}).get("daily_x", {})
    check("③ 跨日重置 completed=0", entry.get("completed") == 0
          and entry.get("cycle_date") == datetime.now().strftime("%Y-%m-%d"),
          str(entry))

    # ④ 改配置重置
    progress = sm.get_state("task_runtime_progress", {})
    progress["daily_x"] = {"completed": 50, "total": 100,
                           "cycle_date": datetime.now().strftime("%Y-%m-%d")}
    sm.set_state("task_runtime_progress", progress)
    ctrl.reset_task_cycle("daily_x")
    entry = sm.get_state("task_runtime_progress", {}).get("daily_x", {})
    check("④ 改配置重置 completed=0", entry.get("completed") == 0, str(entry))

    # ═══ 阶段2：单次任务两模式 ═══
    from ui.panels.game_task_panel import REPEAT_TYPES
    types = [t for t, _ in REPEAT_TYPES]
    check("⑤ 含 on_enter(每次启动执行)", "on_enter" in types, str(types))
    check("⑤ 含 once(只执行一次)", "once" in types, str(types))

    # ═══ 阶段3：触发任务周期上限 ═══
    fake_cfg3 = SimpleNamespace(tasks_config=SimpleNamespace(
        tasks=[build_raw("trig_x", rtype="trigger", trigger_max=3)]))
    store3 = TaskStateStore(tmpdir / "s3.json")
    sched3 = Scheduler(event_bus=bus, config=fake_cfg3, state_manager=sm, store=store3)
    sched3.load_tasks_from_config()

    # ⑥ trigger_max_count 加载
    cfg3 = sched3._tasks["trig_x"]
    check("⑥ trigger_max_count 加载", cfg3.repeat.trigger_max_count == 3,
          str(cfg3.repeat.trigger_max_count))

    now = datetime.now(sched3._timezone)

    # ⑦ 触发未达上限 → 正常设置 next_run
    sched3.update_next_run("trig_x", now)
    check("⑦ 未达上限可触发", "trig_x" in sched3._next_run, str(sched3._next_run))

    # 模拟触发执行 3 次（mark_done 成功 → today_count+1）
    for _ in range(3):
        sched3.mark_done("trig_x", True)
    check("⑦ 触发 3 次后 today_count=3", sched3._today_count.get("trig_x") == 3,
          str(sched3._today_count))

    # 第 4 次触发 → 拦截
    sched3._next_run.pop("trig_x", None)
    sched3.task_status["trig_x"] = ScheduleStatus.WAITING
    sched3.update_next_run("trig_x", now)
    check("⑦ 达上限触发被拦截", "trig_x" not in sched3._next_run,
          str(sched3._next_run))
    check("⑦ 达上限标记失效(COMPLETED)",
          sched3.task_status.get("trig_x") == ScheduleStatus.COMPLETED,
          str(sched3.task_status.get("trig_x")))
    check("⑦ 达上限标注", "已达周期上限" in (sched3._defer_reasons.get("trig_x") or ""),
          str(sched3._defer_reasons.get("trig_x")))

    # ⑧ _invalid_reason 返回"已达上限"
    reason = sched3._invalid_reason(cfg3, now, now.strftime("%Y-%m-%d"))
    check("⑧ 失效状态=已达上限", reason == "已达上限", str(reason))

    # UI：已达上限不显示触发按钮
    from ui.panels.task_queue_panel import TaskQueuePanel
    from PyQt5.QtWidgets import QPushButton
    invalid = sched3.get_invalid_tasks()
    panel = TaskQueuePanel()
    panel.update_panel(None, [], [], invalid)
    btn_texts = []
    for i in range(panel.invalid_list.count()):
        it = panel.invalid_list.item(i)
        w = panel.invalid_list.itemWidget(it)
        if w is not None:
            for b in w.findChildren(QPushButton):
                btn_texts.append(b.text())
    check("⑧ 已达上限无⚡触发按钮", "⚡触发" not in btn_texts,
          f"buttons={btn_texts}")
    # 未达上限的 trigger 任务仍有触发按钮
    fake_cfg4 = SimpleNamespace(tasks_config=SimpleNamespace(
        tasks=[build_raw("trig_y", rtype="trigger", trigger_max=None)]))
    sched4 = Scheduler(event_bus=bus, config=fake_cfg4, state_manager=sm, store=None)
    sched4.load_tasks_from_config()
    invalid4 = sched4.get_invalid_tasks()
    panel4 = TaskQueuePanel()
    panel4.update_panel(None, [], [], invalid4)
    btn4 = []
    for i in range(panel4.invalid_list.count()):
        it = panel4.invalid_list.item(i)
        w = panel4.invalid_list.itemWidget(it)
        if w is not None:
            for b in w.findChildren(QPushButton):
                btn4.append(b.text())
    check("⑧ 未达上限 trigger 有⚡触发按钮", "⚡触发" in btn4, f"buttons={btn4}")

    print(f"\n🎉 三类型任务改造验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
