"""完整复现：运行中「未开始」任务到期后是否被 filler 自动推入待执行队列。

真实 Scheduler + 真实 RunController（filler/executor 线程）：
  1. 启动运行 → daily 任务窗口内立即 DUE → 执行 → mark_done 推进 next_run=明天 → WAITING（未开始）
  2. 模拟"第二天到期"：把 next_run 改为过去（模拟时间流逝越过 next_run）
  3. 观察 filler 是否在运行中自动拾取入队并执行（无需重启/手动触发）
"""
import os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from core.events import Events


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


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from core.event_bus import EventBus
    from core.scheduler import Scheduler, ScheduleStatus
    from core.state_manager import StateManager
    from core.monitor import Monitor
    from core.run_controller import RunController

    bus = EventBus()
    sm = StateManager(event_bus=bus)
    mon = Monitor(event_bus=bus)
    mon.set_state_manager(sm)

    fake_cfg = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[build_raw("daily_test")]))
    sched = Scheduler(event_bus=bus, config=fake_cfg, state_manager=sm, store=None)
    sched.load_tasks_from_config()

    registry = FakeRegistry()
    registry.tasks["daily_test"] = FakeTask("daily_test", bus=bus)

    ctrl = RunController(
        scheduler=sched, connection=FakeConn(), config=None,
        state_mgr=sm, registry=registry, executor=FakeExec(),
        recognizer=None, event_bus=bus, monitor=mon, account_mgr=None,
    )

    done_events = []
    bus.subscribe(Events.TASK_COMPLETED,
                  lambda **kw: done_events.append(kw.get("task_id", "")))

    def wait_until(cond, timeout=8.0):
        deadline = time.time() + timeout
        while not cond() and time.time() < deadline:
            time.sleep(0.05)
        return cond()

    # ═══ 1. 启动运行 ═══
    ctrl.execute()
    sm.set_state("run_status", "running")
    print("[1] 启动运行")
    wait_until(lambda: len(done_events) >= 1)
    # 等待 mark_done 完成（TASK_COMPLETED 在 execute 内发布，mark_done 在其后）
    wait_until(lambda: sched.task_status.get("daily_test") == ScheduleStatus.WAITING)
    print(f"[1] daily_test 首次执行完成，done_events={done_events}")

    # 检查 mark_done 后状态
    st = sched.task_status.get("daily_test")
    nrt = sched._next_run.get("daily_test")
    print(f"[1] mark_done 后: status={st}  next_run={nrt}")
    assert st == ScheduleStatus.WAITING, f"预期 WAITING，实际 {st}"
    assert nrt and nrt > datetime.now(sched._timezone), f"next_run 应推进到未来: {nrt}"
    print("    ✅ 执行后任务正确进入「未开始」（next_run=明天）")

    # ═══ 2. 模拟真实到期：next_run = 未来 3 秒（未开始），时间自然流逝跨过 ═══
    now = datetime.now(sched._timezone)
    future = now + timedelta(seconds=3)
    sched._next_run["daily_test"] = future
    sched.task_status["daily_test"] = ScheduleStatus.WAITING
    print(f"[2] 未开始: next_run={future.strftime('%H:%M:%S')}（3 秒后到期）")
    print("    等待 filler 在运行中自动拾取入队（不重启/不手动触发）...")

    # ═══ 3. 观察 filler 是否自动拾取 ═══
    picked = wait_until(lambda: len(done_events) >= 2, timeout=15.0)
    if picked:
        print(f"[3] ✅ 运行中自动拾取并执行: done_events={done_events}")
    else:
        print(f"[3] ❌ 运行中未自动拾取！done_events={done_events}")
        # 诊断：手动触发一次 build_schedule / get_next_task
        due = sched.build_schedule(publish=False)
        print(f"    手动 build_schedule → due={[t.name for t in due]}")
        print(f"    task_status={sched.task_status.get('daily_test')}")
        print(f"    next_run={sched._next_run.get('daily_test')}")
        print(f"    _task_queue={list(ctrl._task_queue)}  current_task={ctrl.current_task}")
        nt = sched.get_next_task()
        print(f"    get_next_task → {nt}")
        # 检查 filler 线程是否还活着
        print(f"    filler_alive={ctrl._filler_thread.is_alive() if ctrl._filler_thread else None}")
        # 检查是否被 already 去重逻辑拦住
        print(f"    next_task==current? {sched.get_next_task() == ctrl.current_task}")

    print("\n结论:", "✅ 运行中到期自动入队正常" if picked else "❌ 复现问题：运行中到期未自动入队")
    # 清理
    ctrl.stop()


if __name__ == "__main__":
    main()
