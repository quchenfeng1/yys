# -*- coding: utf-8 -*-
"""
验证：任务队列「📡 待触发」区 + 暂停展示（2026-08-16 信号体系）。

A. TaskQueuePanel：待触发列表 / 暂停标签（等待信号/超时唤醒/执行中）
B. TaskBridge.get_pending_trigger_tasks（调度器触发任务 → UI 数据）
C. RunBridge.get_paused_snapshot（运行控制中心暂停记录 → UI 数据）
D. Scheduler 检查器注入后：build_schedule 排除触发任务，待触发区只出到期未达上限
"""
import os
import sys
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL: {label}  {detail}"
    PASS += 1
    print(f"PASS {label}")


def main():
    # ═══ A. 队列面板：待触发区 + 暂停展示 ═══
    from ui.panels.task_queue_panel import TaskQueuePanel
    panel = TaskQueuePanel()
    panel.update_panel(
        current="t_run",
        pending=[{"name": "t1", "next_run": "08-16 12:00", "priority": 3}],
        upcoming=[{"name": "t2", "next_run": "08-17 06:00", "reason": ""}],
        invalid=[],
        trigger=[{"name": "t_trig", "next_run": "08-16 12:00", "priority": 1}],
        paused=[{"name": "t_p", "signal": "sig_x", "seconds": 60,
                 "ready": False, "active": False},
                {"name": "t_wake", "ready": True, "active": False}],
    )
    check("A1 待触发列表 1 项", panel.trigger_list.count() == 1,
          str(panel.trigger_list.count()))
    check("A2 待执行/未开始正常", panel.pending_list.count() == 1
          and panel.upcoming_list.count() == 1)
    txt = panel.paused_label.text()
    check("A3 暂停标签可见", not panel.paused_label.isHidden())
    check("A4 暂停标签含等待信号", "t_p" in txt and "sig_x" in txt, txt)
    check("A5 暂停标签含待唤醒", "t_wake" in txt and "待唤醒" in txt, txt)

    # 空暂停 → 隐藏
    panel.update_panel("t_run", [], [], [], [], [])
    check("A6 无暂停时标签隐藏", panel.paused_label.isHidden()
          and panel.trigger_list.count() == 0)

    # ═══ B. TaskBridge 待触发数据 ═══
    from types import SimpleNamespace
    from ui.param_bridge.task_bridge import TaskBridge
    info = SimpleNamespace(name="t_trig",
                           next_run=__import__("datetime").datetime(2026, 8, 16, 12, 0),
                           priority=1)
    fake_sched = SimpleNamespace(get_pending_trigger_tasks=lambda: [info])
    tb = TaskBridge(scheduler=fake_sched)
    rows = tb.get_pending_trigger_tasks()
    check("B1 TaskBridge 待触发列表", len(rows) == 1
          and rows[0]["name"] == "t_trig" and rows[0]["priority"] == 1,
          str(rows))

    # ═══ C. RunBridge 暂停快照 ═══
    from ui.param_bridge.run_bridge import RunBridge
    fake_ctrl = SimpleNamespace(
        paused_snapshot=lambda: [{"name": "t_p", "signal": "sig_x"}])
    rb = RunBridge()
    rb.set_controller(fake_ctrl)
    paused = rb.get_paused_snapshot()
    check("C1 RunBridge 暂停快照", len(paused) == 1
          and paused[0]["name"] == "t_p", str(paused))

    # ═══ D. 调度器：检查器注入 → 排除触发任务 + 待触发区数据 ═══
    from datetime import datetime, timedelta
    from core.scheduler import Scheduler, RepeatConfig, TaskConfig, ScheduleStatus

    class FakeStore:
        def __init__(self):
            self.data = {}

        def load(self):
            pass

        def save(self, data):
            self.data = data

        def get(self, name):
            return self.data.get(name)

        def get_or_create(self, name):
            return self.data.setdefault(name, {})

        def update(self, name, **kw):
            self.data.setdefault(name, {}).update(kw)

    s = Scheduler(event_bus=None, store=FakeStore())
    s._tasks["t_trig"] = TaskConfig(
        name="t_trig", category="special", priority=1, max_daily=3,
        repeat=RepeatConfig(type="daily"))
    s._tasks["t_normal"] = TaskConfig(
        name="t_normal", category="daily", priority=5,
        repeat=RepeatConfig(type="daily"))
    s.set_trigger_checker(lambda n: n == "t_trig")
    s.set_anomaly_checker(lambda n: False)
    s.load_state()
    # 两个任务都到期
    now = datetime.now(s._timezone)
    s._next_run["t_trig"] = now - timedelta(minutes=1)
    s._next_run["t_normal"] = now - timedelta(minutes=1)
    s._today_count["t_trig"] = 0
    s._today_count["t_normal"] = 0
    sched = [t.name for t in s.build_schedule(publish=False)]
    check("D1 build_schedule 排除触发任务",
          "t_trig" not in sched and "t_normal" in sched, str(sched))
    trig = [t.name for t in s.get_pending_trigger_tasks()]
    check("D2 待触发区含到期触发任务", trig == ["t_trig"], str(trig))
    # 达上限 → 不再进待触发区
    s._today_count["t_trig"] = 3
    check("D3 达上限不列待触发", s.get_pending_trigger_tasks() == [])

    print(f"\n🎉 待触发区 + 暂停展示验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
