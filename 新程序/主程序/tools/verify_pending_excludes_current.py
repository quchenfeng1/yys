"""验证：正在执行的任务只显示在「正在执行」区，不进「待执行」区。

复现问题：执行中任务的 next_run 尚未被 mark_done 清空 → get_due_tasks 仍判定到期
→ 修复前会被并进待执行区。修复后 _refresh_queue_panel 合并时排除 current。
"""
import os, sys
from datetime import datetime

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from core.event_bus import EventBus
from core.scheduler import Scheduler, TaskConfig, RepeatConfig


class FakeStore:
    def __init__(self):
        self.data = {}
    def load(self): pass
    def save(self, data): self.data = data
    def get(self, name): return self.data.get(name)
    def get_or_create(self, name): return self.data.setdefault(name, {})
    def update(self, name, **kw): self.data.setdefault(name, {}).update(kw)


class FakeRun:
    def __init__(self, current, queue):
        self._current = current
        self._queue = list(queue)
    def get_current_task(self): return self._current
    def get_queue_snapshot(self): return list(self._queue)


class FakeTask:
    def __init__(self, scheduler):
        self._s = scheduler
    def get_due_tasks(self): return self._s.get_due_tasks()
    def get_upcoming(self): return self._s.get_upcoming()
    def get_invalid_tasks(self): return self._s.get_invalid_tasks()


class FakeBridge:
    def __init__(self, run, task):
        self.run = run
        self.task = task


class FakeSignal:
    """模拟 ui_update：emit 立即执行携带的 lambda"""
    def __init__(self, calls):
        self._calls = calls
    def emit(self, fn):
        fn()
        self._calls.append(True)


class FakePanel:
    def __init__(self, calls):
        self._calls = calls

    def update_panel(self, current, pending, upcoming, invalid,
                     trigger=None, paused=None):
        self._calls["update_panel"] = (current, list(pending),
                                       list(upcoming), list(invalid),
                                       list(trigger or []), list(paused or []))


def _names(items):
    return [p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in items]


def main():
    bus = EventBus()
    s = Scheduler(event_bus=bus, store=FakeStore())
    # once_test（on_enter）：启动激活，正在执行中（next_run 未清）
    s._tasks["once_test"] = TaskConfig(
        name="once_test", category="special", repeat=RepeatConfig(type="on_enter"),
    )
    # manual_trigger_test（trigger）：已手动触发，在等待队列
    s._tasks["manual_trigger_test"] = TaskConfig(
        name="manual_trigger_test", category="special",
        repeat=RepeatConfig(type="trigger"),
    )
    s.load_state()
    # once_test 启动激活（next_run=now）；manual_trigger_test 被手动触发
    s.update_next_run("manual_trigger_test", datetime.now(s._timezone))

    # 复现 bug 前提：执行中的 once_test next_run 未清 → get_due_tasks 仍返回它
    due_names = [d["name"] for d in s.get_due_tasks()]
    assert "once_test" in due_names, f"执行中任务应仍被调度器判定到期: {due_names}"
    print("① PASS 复现：执行中任务 next_run 未清 → get_due_tasks 仍返回它")

    # 调用真实 MainWindow._refresh_queue_panel 合并逻辑
    from ui.main_window import MainWindow
    mw = MainWindow.__new__(MainWindow)
    calls = {"update_panel": None}
    mw._param_bridge = FakeBridge(
        FakeRun(current="once_test", queue=["manual_trigger_test"]), FakeTask(s))
    mw.panels = {"task_queue": FakePanel(calls)}
    mw.ui_update = FakeSignal([])
    mw._refresh_queue_panel()

    current, pending, _, _, _, _ = calls["update_panel"]
    pending_names = _names(pending)
    assert current == "once_test", f"current 应为 once_test: {current}"
    assert "once_test" not in pending_names, f"执行中任务不应在待执行区: {pending_names}"
    assert "manual_trigger_test" in pending_names, f"真正待执行任务应保留: {pending_names}"
    print(f"② PASS 执行中任务移出待执行区，保留真正待执行: {pending_names}")

    # 场景2：无执行中任务（current=None）→ 不受影响
    mw._param_bridge = FakeBridge(
        FakeRun(current=None, queue=["manual_trigger_test"]), FakeTask(s))
    mw._refresh_queue_panel()
    _, pending2, _, _, _, _ = calls["update_panel"]
    assert "manual_trigger_test" in _names(pending2), f"无执行中时待执行区应正常: {_names(pending2)}"
    print(f"③ PASS 无执行中任务时待执行区正常: {_names(pending2)}")

    print("\n🎉 待执行区排除执行中任务验证 3/3 通过")


if __name__ == "__main__":
    main()
