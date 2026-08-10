"""端到端验证：UI「▶ 启动」按钮 → RunBridge → START_REQUESTED → RunController.execute → 三线程 → 任务执行 → UI 反馈 → 停止。

模拟真实链路（含 UI 侧信号连接，与 main_window._connect_control_bar 同款）：
  ControlBar.start_clicked → RunBridge.request_start → EventBus(START_REQUESTED)
    → RunController._on_start → execute() → 三线程
    → filler 取到期任务入队 → executor 执行（record_task_start/done）→ TASK_QUEUED/COMPLETED
    → RUN_STARTED → UI ControlBar.set_running(True)

覆盖：
  ① 点击启动 → START_REQUESTED 事件发布
  ② execute 启动：RUN_STARTED 发布、run_status=running、filler/executor 线程活跃
  ③ UI 反馈：ControlBar 启动按钮禁用 / 停止暂停启用 / 沙盒禁用
  ④ 任务全流程：入队(TASK_QUEUED) → 执行(TASK_STARTED/TASK_COMPLETED) → mark_done → execution_history 记录
  ⑤ 重复点击启动被幂等拦截（不重复启动线程）
  ⑥ 暂停 → RUN_PAUSED + is_paused；继续 → RUN_RESUMED
  ⑦ 停止 → RUN_STOPPED、run_status=stopped、三线程退出、队列清空
"""
import os, sys, time
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


# ── 最小依赖替身 ──────────────────────────────────────────
class FakeRegistry:
    def __init__(self):
        self.tasks = {}
    def get(self, name):
        return self.tasks.get(name)
    def get_all(self):
        return list(self.tasks.values())


class FakeTask:
    """模拟任务：发布开始/完成事件（真实 BaseTask 职责）后返回成功"""
    task_id = name = ""
    def __init__(self, name, bus=None):
        self.task_id = name
        self.name = name
        self.has_assets = True
        self._bus = bus
    def execute(self, context):
        from core.events import Events
        if self._bus:
            self._bus.publish(Events.TASK_STARTED, source="fake",
                              task_id=self.task_id, task_name=self.name)
        time.sleep(0.15)
        if self._bus:
            self._bus.publish(Events.TASK_COMPLETED, source="fake",
                              task_id=self.task_id, duration=1.0)
        return SimpleNamespace(success=True, status="success", duration=1.0,
                               message="", reason="")


class FakeScheduler:
    def __init__(self):
        self._due = ["task_a"]
        self.marked = []
    def load_tasks_from_config(self):
        pass
    def build_schedule(self):
        return []
    def get_next_task(self):
        if self._due:
            return self._due.pop(0)
        return None
    def mark_done(self, name, success, interrupted=False):
        self.marked.append((name, success))
    def get_config(self, name):
        return None
    def update_next_run(self, name, t):
        pass


class FakeExecutor:
    def set_asset_aliases(self, aliases):
        pass
    def set_signal_map(self, m):
        pass
    def set_dry_run(self, v):
        pass
    def click_if_exists(self, tmpl):
        return False
    def detect_scene(self, names):
        return None


class FakeConnection:
    def connect(self):
        return True
    def is_connected(self):
        return True
    def switch_device(self, dev):
        pass


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from core.event_bus import EventBus
    from core.events import Events
    from core.state_manager import StateManager
    from core.monitor import Monitor
    from core.run_controller import RunController
    from ui.param_bridge.run_bridge import RunBridge
    from ui.panels.control_bar import ControlBar

    bus = EventBus()
    sm = StateManager(event_bus=bus)
    mon = Monitor(event_bus=bus)
    mon.set_state_manager(sm)

    registry = FakeRegistry()
    registry.tasks["task_a"] = FakeTask("task_a", bus=bus)
    sched = FakeScheduler()

    ctrl = RunController(
        scheduler=sched,
        connection=FakeConnection(),
        config=None,
        state_mgr=sm,
        registry=registry,
        executor=FakeExecutor(),
        recognizer=None,   # 不创建 TriggerWatcher
        event_bus=bus,
        monitor=mon,
        account_mgr=None,  # 不启动 scanner 线程
    )
    bridge = RunBridge(event_bus=bus)
    cb = ControlBar()

    # 与 main_window._connect_control_bar 同款的信号连接
    cb.start_clicked.connect(lambda: bridge.request_start())
    cb.stop_clicked.connect(lambda: bridge.request_stop())
    cb.pause_clicked.connect(lambda: bridge.request_pause())
    cb.resume_clicked.connect(lambda: bridge.request_resume())

    # 模拟 MainWindow 事件 handler：RUN_STARTED → set_running(True)
    events = {"RUN_STARTED": 0, "RUN_STOPPED": 0, "RUN_PAUSED": 0, "RUN_RESUMED": 0,
              "TASK_QUEUED": 0, "TASK_STARTED": 0, "TASK_COMPLETED": 0}
    bus.subscribe(Events.RUN_STARTED, lambda **kw: events.__setitem__("RUN_STARTED", events["RUN_STARTED"] + 1))
    bus.subscribe(Events.RUN_STOPPED, lambda **kw: events.__setitem__("RUN_STOPPED", events["RUN_STOPPED"] + 1))
    bus.subscribe(Events.RUN_PAUSED, lambda **kw: events.__setitem__("RUN_PAUSED", events["RUN_PAUSED"] + 1))
    bus.subscribe(Events.RUN_RESUMED, lambda **kw: events.__setitem__("RUN_RESUMED", events["RUN_RESUMED"] + 1))
    bus.subscribe(Events.TASK_QUEUED, lambda **kw: events.__setitem__("TASK_QUEUED", events["TASK_QUEUED"] + 1))
    bus.subscribe(Events.TASK_STARTED, lambda **kw: events.__setitem__("TASK_STARTED", events["TASK_STARTED"] + 1))
    bus.subscribe(Events.TASK_COMPLETED, lambda **kw: events.__setitem__("TASK_COMPLETED", events["TASK_COMPLETED"] + 1))

    # ═══ ① 点击「启动」→ START_REQUESTED ═══
    start_events = []
    bus.subscribe("start_requested", lambda **kw: start_events.append(kw))
    cb.btn_start.click()  # 等价于用户点击
    deadline = time.time() + 2.0
    while not start_events and time.time() < deadline:
        time.sleep(0.02)
    check("① 点击启动发布 START_REQUESTED", len(start_events) == 1, str(start_events))

    # 兼容路径：RunBridge.start() 应走事件（RunController 无 start 方法，直接调会 AttributeError）
    # 注意：需超过 EventBus 去重窗口（0.2s），否则与 ① 相同事件被合并
    time.sleep(0.3)
    start_events.clear()
    bridge.start()
    deadline = time.time() + 2.0
    while not start_events and time.time() < deadline:
        time.sleep(0.02)
    check("① RunBridge.start() 走事件路径", len(start_events) == 1, str(start_events))
    # 该事件不会重复启动（is_running 幂等）
    check("① 兼容 start() 未重复启动", sm.get_state("run_status") == "running")

    # ═══ ② execute 启动 ═══
    deadline = time.time() + 3.0
    while sm.get_state("run_status") != "running" and time.time() < deadline:
        time.sleep(0.02)
    check("② run_status=running", sm.get_state("run_status") == "running")
    check("② RUN_STARTED 发布", events["RUN_STARTED"] >= 1)
    check("② filler 线程活跃", ctrl._filler_thread is not None and ctrl._filler_thread.is_alive())
    check("② executor 线程活跃", ctrl._executor_thread is not None and ctrl._executor_thread.is_alive())

    # ═══ ③ UI 反馈（RUN_STARTED → set_running） ═══
    # 模拟 MainWindow._on_run_started
    cb.set_running(True)
    check("③ 启动按钮禁用", not cb.btn_start.isEnabled())
    check("③ 停止按钮启用", cb.btn_stop.isEnabled())
    check("③ 暂停按钮启用", cb.btn_pause.isEnabled())
    check("③ 沙盒禁用", not cb.chk_dry_run.isEnabled())

    # ═══ ④ 任务全流程 ═══
    deadline = time.time() + 5.0
    while not sched.marked and time.time() < deadline:
        time.sleep(0.05)
    check("④ TASK_QUEUED 发布", events["TASK_QUEUED"] >= 1, str(events["TASK_QUEUED"]))
    check("④ TASK_STARTED 发布", events["TASK_STARTED"] >= 1)
    check("④ TASK_COMPLETED 发布", events["TASK_COMPLETED"] >= 1)
    check("④ mark_done 调用", sched.marked == [("task_a", True)], str(sched.marked))
    deadline = time.time() + 3.0
    while not sm.get_state("execution_history", []) and time.time() < deadline:
        time.sleep(0.05)
    hist = sm.get_state("execution_history", [])
    check("④ execution_history 已记录", len(hist) == 1 and hist[0]["task_name"] == "task_a"
          and hist[0]["success"] is True, str(hist))

    # ═══ ⑤ 重复点击启动 → 幂等 ═══
    t_before = id(ctrl._filler_thread)
    cb.btn_start.click()
    time.sleep(0.6)
    check("⑤ 重复点击不重复启动线程", id(ctrl._filler_thread) == t_before)
    check("⑤ 重复点击后仍 running", ctrl.is_running and sm.get_state("run_status") == "running")

    # ═══ ⑥ 暂停 / 继续 ═══
    cb.btn_pause.click()   # 「⏸ 暂停」→ pause
    deadline = time.time() + 2.0
    while not ctrl.is_paused and time.time() < deadline:
        time.sleep(0.02)
    check("⑥ 暂停 is_paused", ctrl.is_paused)
    check("⑥ RUN_PAUSED 发布", events["RUN_PAUSED"] >= 1)
    check("⑥ run_status=paused", sm.get_state("run_status") == "paused")
    cb.btn_pause.click()   # 「▶ 继续」→ resume
    deadline = time.time() + 2.0
    while not ctrl.is_running and time.time() < deadline:
        time.sleep(0.02)
    check("⑥ 继续 is_running", ctrl.is_running)
    check("⑥ RUN_RESUMED 发布", events["RUN_RESUMED"] >= 1)
    check("⑥ run_status=running", sm.get_state("run_status") == "running")

    # ═══ ⑦ 停止 ═══
    cb.btn_stop.click()
    deadline = time.time() + 5.0
    while sm.get_state("run_status") != "stopped" and time.time() < deadline:
        time.sleep(0.05)
    check("⑦ RUN_STOPPED 发布", events["RUN_STOPPED"] >= 1)
    check("⑦ run_status=stopped", sm.get_state("run_status") == "stopped")
    check("⑦ filler 线程已退出", ctrl._filler_thread is None
          or not ctrl._filler_thread.is_alive())
    check("⑦ executor 线程已退出", ctrl._executor_thread is None
          or not ctrl._executor_thread.is_alive())
    # 模拟 MainWindow._on_run_stopped → control_bar.set_running(False)
    cb.set_running(False)
    check("⑦ 停止按钮禁用", not cb.btn_stop.isEnabled())
    check("⑦ 启动按钮恢复", cb.btn_start.isEnabled())

    print(f"\n🎉 启动按钮调用链路验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
