"""验证：任务被脚本「停止」中断后，下次执行时间如何推进。

场景：
  A. 停止时任务执行中（长任务）→ 任务跑完返回 True → mark_done(True) → 正常推进明天
  B. 停止时任务已出队但未执行完/失败 → mark_done(False) → fail_streak+1 → 冷却重试
  C. 连续失败累计 → 熔断（fail_streak >= max_fail_streak）→ SKIPPED
"""
import os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


class FakeRegistry:
    def __init__(self):
        self.tasks = {}
    def get(self, name):
        return self.tasks.get(name)


class FakeTask:
    """duration=执行时长；fail=是否返回失败"""
    task_id = name = ""
    def __init__(self, name, duration=0.1, fail=False, check_stop=False):
        self.task_id = name
        self.name = name
        self.has_assets = True
        self._dur = duration
        self._fail = fail
        self._check_stop = check_stop  # 执行中检查 stop_event（模拟被中断提前退出）
    def execute(self, context):
        stop = getattr(context, 'stop_event', None)
        step = 0.05
        elapsed = 0.0
        while elapsed < self._dur:
            if self._check_stop and stop and stop.is_set():
                return SimpleNamespace(success=False, status="failed",
                                       duration=elapsed, message="interrupted",
                                       reason="stopped")  # 中断 → 失败
            time.sleep(step)
            elapsed += step
        if self._fail:
            return SimpleNamespace(success=False, status="failed", duration=1.0,
                                   message="fail", reason="")
        return SimpleNamespace(success=True, status="success", duration=1.0,
                               message="", reason="")


class FakeExec:
    def set_asset_aliases(self, a): pass
    def set_signal_map(self, m): pass
    def set_dry_run(self, v): pass
    def click_if_exists(self, t): return False
    def detect_scene(self, n): return None


class FakeConn:
    def connect(self): return True
    def is_connected(self): return True


def build_raw(name, rtype="daily", max_fail=10):
    return SimpleNamespace(
        name=name, display_name=name, category="daily", enabled=True,
        priority=10, time_start="06:00", time_end="23:59", max_daily=None,
        active_range=None, total_count=None, execution_mode="daily",
        loop_count=1, time_slots=None, max_fail_streak=max_fail,
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
    from core.task_state import TaskStateStore
    import tempfile as _tf

    bus = EventBus()
    sm = StateManager(event_bus=bus)
    mon = Monitor(event_bus=bus)
    tmpdir = _tf.mkdtemp(prefix="stop_nrt_")

    def build_ctrl(tasks_raw, tasks_map, store=None):
        fake_cfg = SimpleNamespace(tasks_config=SimpleNamespace(tasks=tasks_raw))
        sched = Scheduler(event_bus=bus, config=fake_cfg, state_manager=sm, store=store)
        sched.load_tasks_from_config()
        registry = FakeRegistry()
        for n, t in tasks_map.items():
            registry.tasks[n] = t
        ctrl = RunController(
            scheduler=sched, connection=FakeConn(), config=None,
            state_mgr=sm, registry=registry, executor=FakeExec(),
            recognizer=None, event_bus=bus, monitor=mon, account_mgr=None,
        )
        return sched, ctrl

    def wait_until(cond, timeout=8.0):
        deadline = time.time() + timeout
        while not cond() and time.time() < deadline:
            time.sleep(0.05)
        return cond()

    print("=" * 60)
    print("场景 A：停止时任务执行中（长任务 2s，任务不检查 stop → 跑完算成功）")
    print("=" * 60)
    schedA, ctrlA = build_ctrl([build_raw("task_a")],
                               {"task_a": FakeTask("task_a", duration=2.0)})
    ctrlA.execute()
    # 等任务出队开始执行
    wait_until(lambda: ctrlA.current_task == "task_a", timeout=3.0)
    time.sleep(0.3)
    ctrlA.stop()  # 执行中停止（join 3s 等任务完成）
    nrtA = schedA._next_run.get("task_a")
    stA = schedA.task_status.get("task_a")
    print(f"  任务返回成功 → mark_done(True)")
    print(f"  status={stA.value}  next_run={nrtA}")
    if nrtA:
        delta = nrtA - datetime.now(schedA._timezone)
        print(f"  距下次执行: {delta.days} 天 {delta.seconds // 3600} 小时 "
              f"{(delta.seconds % 3600) // 60} 分钟")

    print()
    print("=" * 60)
    print("场景 B：停止时任务被中断（任务检查 stop_event → 提前退出返回失败）")
    print("=" * 60)
    storeB = TaskStateStore(Path(tmpdir) / "b.json")
    schedB, ctrlB = build_ctrl([build_raw("task_b")],
                               {"task_b": FakeTask("task_b", duration=5.0,
                                                   check_stop=True)},
                               store=storeB)
    ctrlB.execute()
    wait_until(lambda: ctrlB.current_task == "task_b", timeout=3.0)
    time.sleep(0.3)
    ctrlB.stop()  # 执行中停止 → 任务检查 stop 提前退出 → success=False
    nrtB = schedB._next_run.get("task_b")
    stB = schedB.task_status.get("task_b")
    storedB = storeB.get("task_b") if storeB else {}
    failB = (storedB or {}).get('fail_streak', 0)
    print(f"  任务被中断 → mark_done(False)  fail_streak={failB}")
    print(f"  status={stB.value}  next_run={nrtB}")
    if nrtB:
        delta = nrtB - datetime.now(schedB._timezone)
        print(f"  距下次执行: 约 {max(1, round(delta.total_seconds() / 60))} 分钟（冷却重试）")
    else:
        print("  next_run=None（已熔断或无）")

    print()
    print("=" * 60)
    print("场景 C：未执行就停止（任务在队列中，stop 时 executor 未消费）")
    print("=" * 60)
    schedC, ctrlC = build_ctrl([build_raw("task_c")],
                               {"task_c": FakeTask("task_c", duration=0.5)})
    ctrlC.execute()
    time.sleep(0.2)  # 可能还没出队
    ctrlC.stop()
    nrtC = schedC._next_run.get("task_c")
    stC = schedC.task_status.get("task_c")
    print(f"  status={stC.value if stC else None}  next_run={nrtC}")
    if nrtC:
        delta = nrtC - datetime.now(schedC._timezone)
        print(f"  距下次执行: {delta.days} 天 {delta.seconds // 3600} 小时 "
              f"{(delta.seconds % 3600) // 60} 分钟")
    else:
        print("  next_run=None")

    print()
    print("=" * 60)
    print("场景 D：连续失败冷却递增 + 熔断（max_fail_streak=3，真实 store 累计 fail_streak）")
    print("=" * 60)
    storeD = TaskStateStore(Path(tmpdir) / "d.json")
    schedD, ctrlD = build_ctrl([build_raw("task_d", max_fail=3)],
                               {"task_d": FakeTask("task_d", duration=0.05,
                                                   fail=True)},
                               store=storeD)
    for i in range(5):
        schedD.mark_done("task_d", False)
        nrt = schedD._next_run.get("task_d")
        st = schedD.task_status.get("task_d")
        stored = storeD.get("task_d") or {}
        fs = stored.get('fail_streak', 0)
        if nrt:
            delta = nrt - datetime.now(schedD._timezone)
            cool_min = max(1, round(delta.total_seconds() / 60))
            print(f"  第{i+1}次失败: fail_streak={fs}  status={st.value}  "
                  f"冷却≈{cool_min}分钟")
        else:
            print(f"  第{i+1}次失败: fail_streak={fs}  status={st.value}  next_run=None（熔断）")


if __name__ == "__main__":
    main()
