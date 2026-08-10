"""最终复现：用户完整操作序列下的「未开始任务到期自动入队」行为。

序列：
  1. 启动 → daily 任务立即执行 → mark_done 推进 next_run=明天 → 「未开始」
  2. 停止程序（保存 task_state.json）
  3. 重新启动（新 Scheduler/RunController，从 task_state.json 恢复 next_run）
  4. 验证重启后任务在「未开始」（next_run=明天）
  5. 模拟跨天到期（next_run → 过去）
  6. 观察 filler 是否运行中自动入队执行（无需重启/手动触发）

结论将区分：
  - daily 链路正常 → 用户问题属于 trigger/on_enter 设计语义或 UI 显示
  - daily 链路断 → 定位真实 bug
"""
import os, sys, time, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from core.events import Events
from core.task_state import TaskStateStore


class FakeRegistry:
    def __init__(self):
        self.tasks = {}
    def get(self, name):
        return self.tasks.get(name)


class FakeTask:
    task_id = name = ""
    def __init__(self, name, bus=None):
        self.task_id = name
        self.name = name
        self.has_assets = True
        self._bus = bus
    def execute(self, context):
        from types import SimpleNamespace as NS
        if self._bus:
            self._bus.publish(Events.TASK_COMPLETED, source="fake",
                              task_id=self.task_id, duration=1.0)
        time.sleep(0.15)
        return NS(success=True, status="success", duration=1.0, message="", reason="")


class FakeExec:
    def set_asset_aliases(self, a): pass
    def set_signal_map(self, m): pass
    def set_dry_run(self, v): pass
    def click_if_exists(self, t): return False
    def detect_scene(self, n): return None


class FakeConn:
    def connect(self): return True
    def is_connected(self): return True


def build_raw(name, rtype="daily"):
    return SimpleNamespace(
        name=name, display_name=name, category="daily", enabled=True,
        priority=10, time_start="06:00", time_end="23:59", max_daily=None,
        active_range=None, total_count=None, execution_mode="daily",
        loop_count=1, time_slots=None,
        repeat={"type": rtype, "value": 1, "loop_count": 1},
    )


def make_scheduler(bus, fake_cfg, store, state_mgr):
    from core.scheduler import Scheduler
    s = Scheduler(event_bus=bus, config=fake_cfg, state_manager=state_mgr, store=store)
    s.load_tasks_from_config()
    s.load_state()
    return s


def make_ctrl(bus, sched, registry, sm, mon):
    from core.run_controller import RunController
    return RunController(
        scheduler=sched, connection=FakeConn(), config=None,
        state_mgr=sm, registry=registry, executor=FakeExec(),
        recognizer=None, event_bus=bus, monitor=mon, account_mgr=None,
    )


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from core.event_bus import EventBus
    from core.scheduler import Scheduler, ScheduleStatus
    from core.state_manager import StateManager
    from core.monitor import Monitor

    tmp = Path(tempfile.mkdtemp(prefix="queue_stall_final_"))
    store_path = tmp / "task_state.json"
    store = TaskStateStore(store_path)

    fake_cfg = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[build_raw("daily_test")]))

    def wait_until(cond, timeout=8.0):
        deadline = time.time() + timeout
        while not cond() and time.time() < deadline:
            time.sleep(0.05)
        return cond()

    # ═══ 1. 第一次启动运行 ═══
    bus1 = EventBus()
    sm1 = StateManager(event_bus=bus1)
    mon1 = Monitor(event_bus=bus1)
    sched1 = make_scheduler(bus1, fake_cfg, store, sm1)
    reg1 = FakeRegistry()
    reg1.tasks["daily_test"] = FakeTask("daily_test", bus=bus1)
    done1 = []
    bus1.subscribe(Events.TASK_COMPLETED, lambda **kw: done1.append(kw.get("task_id", "")))
    ctrl1 = make_ctrl(bus1, sched1, reg1, sm1, mon1)
    ctrl1.execute()
    wait_until(lambda: sched1.task_status.get("daily_test") == ScheduleStatus.WAITING, timeout=8)
    nrt1 = sched1._next_run.get("daily_test")
    print(f"[1] 首次执行后: status=waiting  next_run={nrt1}  （未开始）")
    assert nrt1 and nrt1 > datetime.now(sched1._timezone)

    # ═══ 2. 停止（保存状态） ═══
    ctrl1.stop()
    sched1.save_state()
    print("[2] 停止程序，task_state.json 已保存")
    assert store_path.exists()

    # ═══ 3. 重新启动（新实例，恢复状态） ═══
    bus2 = EventBus()
    sm2 = StateManager(event_bus=bus2)
    mon2 = Monitor(event_bus=bus2)
    sched2 = make_scheduler(bus2, fake_cfg, store, sm2)
    reg2 = FakeRegistry()
    reg2.tasks["daily_test"] = FakeTask("daily_test", bus=bus2)
    done2 = []
    bus2.subscribe(Events.TASK_COMPLETED, lambda **kw: done2.append(kw.get("task_id", "")))
    ctrl2 = make_ctrl(bus2, sched2, reg2, sm2, mon2)
    ctrl2.execute()
    nrt2 = sched2._next_run.get("daily_test")
    st2 = sched2.task_status.get("daily_test")
    print(f"[3] 重启后: status={st2}  next_run={nrt2}")
    assert st2 == ScheduleStatus.WAITING, f"重启后应为未开始，实际 {st2}"
    assert nrt2 and nrt2 > datetime.now(sched2._timezone), "重启后 next_run 应保持明天"

    # ═══ 4. 模拟跨天到期（next_run → 过去） ═══
    past = datetime.now(sched2._timezone) - timedelta(seconds=10)
    sched2._next_run["daily_test"] = past
    print(f"[4] 模拟到期: next_run → {past}（已过，窗口内）")

    # ═══ 5. 观察 filler 是否自动入队执行 ═══
    picked = wait_until(lambda: len(done2) >= 1, timeout=15.0)
    if picked:
        print(f"[5] ✅ 重启后运行中到期自动入队执行: done={done2}")
    else:
        print(f"[5] ❌ 重启后运行中到期未自动入队!")
        due = sched2.build_schedule(publish=False)
        print(f"    手动 build_schedule → due={[t.name for t in due]}")
        print(f"    task_status={sched2.task_status.get('daily_test')}")
        print(f"    next_run={sched2._next_run.get('daily_test')}")
        print(f"    filler_alive={ctrl2._filler_thread.is_alive() if ctrl2._filler_thread else None}")

    ctrl2.stop()
    print("\n结论:", "✅ daily 任务重启后到期自动入队正常"
          if picked else "❌ 复现：重启后运行中到期未自动入队")


if __name__ == "__main__":
    main()
