"""端到端验证：UI「■ 停止」按钮的调用链路与停止语义。

链路：
  ControlBar.btn_stop.click → stop_clicked → RunBridge.request_stop
    → EventBus(STOP_REQUESTED) → RunController._on_stop（is_running/is_paused 保护）
    → stop()：置 STOPPED → _stop_event.set + _paused.set（唤醒暂停）
      → stop_trigger_watcher → join 三线程(3s) → 保存运行时进度 → scheduler.save_state
      → 清理线程/队列/current_task → run_status=stopped → RUN_STOPPED
  UI 反馈：RUN_STOPPED → MainWindow._on_run_stopped → set_running(False)

覆盖：
  ① 停止 → STOP_REQUESTED、RUN_STOPPED、run_status=stopped
  ② 三线程退出、队列清空、current_task=None
  ③ UI 按钮恢复（启动/沙盒启用、停止/暂停禁用）
  ④ 幂等：重复停止不重复执行
  ⑤ 停止后可重新启动（新线程）
  ⑥ scheduler.save_state 被调用
  ⑦ 运行时进度保存到文件
  ⑧ trigger_watcher 已停止
  ⑨ 执行中停止：长任务正常收尾 + execution_history 记录（record_task_done 不丢）
  ⑩ 暂停中停止：线程被唤醒退出
"""
import os, sys, tempfile, time
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


class FakeTask:
    task_id = name = ""
    def __init__(self, name, duration=0.12):
        self.task_id = name
        self.name = name
        self.has_assets = True
        self._dur = duration
    def execute(self, context):
        time.sleep(self._dur)
        return SimpleNamespace(success=True, status="success", duration=1.0,
                               message="", reason="")


class FakeScheduler:
    def __init__(self, names):
        self._due = list(names)
        self.marked = []
        self.save_state_called = 0
    def load_tasks_from_config(self):
        pass
    def build_schedule(self):
        return []
    def get_all_tasks(self):
        return []
    def get_next_task(self):
        if self._due:
            return self._due.pop(0)
        return None
    def mark_done(self, name, success, interrupted=False):
        self.marked.append((name, success))
    def get_config(self, name):
        return None
    def save_state(self):
        self.save_state_called += 1


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
    registry.tasks["task_a"] = FakeTask("task_a", duration=0.12)
    registry.tasks["task_long"] = FakeTask("task_long", duration=1.0)
    sched = FakeScheduler(["task_a"])

    tmp = Path(tempfile.mkdtemp(prefix="stop_chain_"))
    prog_path = tmp / "progress.json"

    ctrl = RunController(
        scheduler=sched, connection=FakeConnection(), config=None,
        state_mgr=sm, registry=registry, executor=FakeExecutor(),
        recognizer=SimpleNamespace(),   # 创建 TriggerWatcher
        event_bus=bus, monitor=mon, account_mgr=None,
        runtime_progress_path=prog_path,
    )
    bridge = RunBridge(event_bus=bus)
    cb = ControlBar()
    cb.start_clicked.connect(lambda: bridge.request_start())
    cb.stop_clicked.connect(lambda: bridge.request_stop())
    cb.pause_clicked.connect(lambda: bridge.request_pause())
    cb.resume_clicked.connect(lambda: bridge.request_resume())

    events = {"RUN_STOPPED": 0}
    bus.subscribe(Events.RUN_STOPPED, lambda **kw: events.__setitem__("RUN_STOPPED", events["RUN_STOPPED"] + 1))
    stop_req = []
    bus.subscribe(Events.STOP_REQUESTED, lambda **kw: stop_req.append(kw))

    def wait_until(cond, timeout=6.0):
        deadline = time.time() + timeout
        while not cond() and time.time() < deadline:
            time.sleep(0.03)
        return cond()

    # 预置运行时进度（供 ⑦ 验证保存）
    sm.set_state("task_runtime_progress", {"task_a": {"completed": 3, "total": 10}})

    # ═══ 0. 启动 ═══
    cb.btn_start.click()
    wait_until(lambda: sm.get_state("run_status") == "running")
    cb.set_running(True)  # 模拟 MainWindow._on_run_started
    wait_until(lambda: len(sched.marked) >= 1)
    check("0 启动并完成 task_a", sched.marked == [("task_a", True)], str(sched.marked))

    # ═══ ① 点停止 ═══
    cb.btn_stop.click()
    wait_until(lambda: sm.get_state("run_status") == "stopped", timeout=6.0)
    check("① STOP_REQUESTED 发布", len(stop_req) >= 1)
    check("① RUN_STOPPED 发布", events["RUN_STOPPED"] >= 1)
    check("① run_status=stopped", sm.get_state("run_status") == "stopped")
    check("① ctrl 状态 STOPPED", ctrl.status == "stopped", ctrl.status)

    # ═══ ② 线程退出 / 清理 ═══
    check("② filler 线程已退出", ctrl._filler_thread is None or not ctrl._filler_thread.is_alive())
    check("② executor 线程已退出", ctrl._executor_thread is None or not ctrl._executor_thread.is_alive())
    check("② 线程引用清空", ctrl._filler_thread is None and ctrl._executor_thread is None)
    check("② current_task=None", ctrl.current_task is None)
    check("② 队列已清空", ctrl.task_queue_size == 0)

    # ═══ ③ UI 按钮恢复（模拟 MainWindow._on_run_stopped） ═══
    cb.set_running(False)
    check("③ 启动按钮恢复", cb.btn_start.isEnabled())
    check("③ 游戏下拉恢复", cb.combo_game.isEnabled())
    check("③ 停止按钮禁用", not cb.btn_stop.isEnabled())
    check("③ 暂停按钮禁用", not cb.btn_pause.isEnabled())

    # ═══ ④ 幂等：重复停止 ═══
    before = events["RUN_STOPPED"]
    ctrl.stop()  # 直接调（已 stopped → return）
    check("④ 重复停止被忽略", events["RUN_STOPPED"] == before)
    check("④ 状态仍 stopped", ctrl.status == "stopped")

    # ═══ ⑤ 停止后重新启动 ═══
    cb.set_running(False)  # 模拟 ④ 停止后 MainWindow 复位按钮
    sched._due.append("task_a")
    cb.btn_start.click()
    wait_until(lambda: sm.get_state("run_status") == "running")
    cb.set_running(True)
    check("⑤ 重启成功 running", ctrl.is_running)
    check("⑤ 新线程启动", ctrl._filler_thread is not None and ctrl._filler_thread.is_alive())
    wait_until(lambda: len(sched.marked) >= 2)
    check("⑤ 重启后任务完成", sched.marked[-1] == ("task_a", True), str(sched.marked[-1]))

    # ═══ ⑥ scheduler.save_state 被调用 ═══
    cb.btn_stop.click()
    wait_until(lambda: sm.get_state("run_status") == "stopped", timeout=6.0)
    cb.set_running(False)  # 模拟停止后复位
    check("⑥ scheduler.save_state 调用", sched.save_state_called >= 1)

    # ═══ ⑦ 运行时进度保存到文件 ═══
    check("⑦ 进度文件已写入", prog_path.exists())
    import json
    saved = json.loads(prog_path.read_text(encoding="utf-8"))
    # 注意：task 执行完成后场次进度会被 _update_task_progress 重置（completed=0），
    # 这里验证的是「进度保存机制」：文件写入 + 结构完整
    check("⑦ 进度含 task_a", "task_a" in saved, str(saved))
    entry = saved.get("task_a", {})
    check("⑦ 进度字段完整", "completed" in entry and "total" in entry, str(entry))

    # ═══ ⑧ trigger_watcher 已停止 ═══
    tw = ctrl._trigger_watcher
    check("⑧ TriggerWatcher 存在", tw is not None)
    check("⑧ 停止事件已置位", tw._stop_event.is_set())

    # ═══ ⑨ 执行中停止：长任务收尾 + 记录不丢 ═══
    sched._due.append("task_long")
    cb.btn_start.click()
    wait_until(lambda: sm.get_state("run_status") == "running")
    cb.set_running(True)
    # 等待 executor 出队并开始执行（current_task 置位）
    wait_until(lambda: ctrl.current_task == "task_long", timeout=3.0)
    check("⑨ 长任务执行中", ctrl.current_task == "task_long")
    cb.btn_stop.click()  # 执行中停止
    wait_until(lambda: sm.get_state("run_status") == "stopped", timeout=6.0)
    check("⑨ 停止后线程退出", ctrl._executor_thread is None or not ctrl._executor_thread.is_alive())
    check("⑨ 长任务被 mark_done", ("task_long", True) in sched.marked, str(sched.marked))
    _stats = getattr(mon, "_task_stats", {})
    check("⑨ 长任务完成统计已记录",
          _stats.get("task_long") is not None and _stats["task_long"].total >= 1,
          str(getattr(_stats.get("task_long"), "total", None)))

    # ═══ ⑩ 暂停中停止 ═══
    cb.set_running(False)  # 模拟 ⑨ 停止后复位，确保启动按钮可用
    sched._due.append("task_a")
    cb.btn_start.click()
    wait_until(lambda: sm.get_state("run_status") == "running", timeout=6.0)
    cb.set_running(True)
    check("⑩ 已重启 running", ctrl.is_running)
    cb.btn_pause.click()  # 暂停
    wait_until(lambda: ctrl.is_paused, timeout=3.0)
    check("⑩ 已暂停", ctrl.is_paused)
    cb.btn_stop.click()  # 暂停中停止
    wait_until(lambda: sm.get_state("run_status") == "stopped", timeout=6.0)
    check("⑩ 暂停中停止成功", sm.get_state("run_status") == "stopped")
    check("⑩ 线程已退出", ctrl._filler_thread is None or not ctrl._filler_thread.is_alive())

    print(f"\n🎉 停止按钮调用链路验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
