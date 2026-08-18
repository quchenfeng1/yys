"""端到端验证：UI「⏸ 暂停」按钮的调用链路与暂停语义。

链路：
  ControlBar.btn_pause.click → _toggle_pause（文本状态机）
    → pause_clicked → RunBridge.request_pause → EventBus(PAUSE_REQUESTED)
    → RunController._on_pause（is_running 保护）→ pause()
    → _paused.clear() → is_paused / RUN_PAUSED / run_status=paused
    → filler/executor 线程阻塞在 _paused.wait()（暂停调度，不中断当前任务）
恢复：点「▶ 继续」→ resume_clicked → RESUME_REQUESTED → _on_resume → resume()

覆盖：
  ① 暂停 → PAUSE_REQUESTED、is_paused、RUN_PAUSED、run_status=paused
  ② 暂停中任务不消费（filler 阻塞、新到期任务不执行）
  ③ 【漏洞修复】暂停中收到 START_REQUESTED 不重启（不绕过暂停）
  ④ 继续 → is_running、RUN_RESUMED、run_status=running、任务恢复消费
  ⑤ UI 文本状态机：暂停后「▶ 继续」/继续后「⏸ 暂停」
  ⑥ 暂停中点停止 → 线程被唤醒退出、RUN_STOPPED
  ⑦ 边界：停止后点暂停 → pause() 被拒绝（is_paused=False）；文本切换（已知脱钩）
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


class FakeTask:
    task_id = name = ""
    def __init__(self, name):
        self.task_id = name
        self.name = name
        self.has_assets = True
    def execute(self, context):
        time.sleep(0.12)
        return SimpleNamespace(success=True, status="success", duration=1.0,
                               message="", reason="")


class FakeScheduler:
    """连续提供多个到期任务，供验证暂停时消费中断"""
    def __init__(self, names):
        self._due = list(names)
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
    registry.tasks["task_a"] = FakeTask("task_a")
    registry.tasks["task_b"] = FakeTask("task_b")
    registry.tasks["task_c"] = FakeTask("task_c")
    sched = FakeScheduler(["task_a"])  # 初始仅 1 个到期任务（暂停边界精确）

    ctrl = RunController(
        scheduler=sched, connection=FakeConnection(), config=None,
        state_mgr=sm, registry=registry, executor=FakeExecutor(),
        recognizer=None, event_bus=bus, monitor=mon, account_mgr=None,
    )
    bridge = RunBridge(event_bus=bus)
    cb = ControlBar()
    cb.start_clicked.connect(lambda: bridge.request_start())
    cb.stop_clicked.connect(lambda: bridge.request_stop())
    cb.pause_clicked.connect(lambda: bridge.request_pause())
    cb.resume_clicked.connect(lambda: bridge.request_resume())

    events = {"RUN_PAUSED": 0, "RUN_RESUMED": 0, "RUN_STOPPED": 0}
    bus.subscribe(Events.RUN_PAUSED, lambda **kw: events.__setitem__("RUN_PAUSED", events["RUN_PAUSED"] + 1))
    bus.subscribe(Events.RUN_RESUMED, lambda **kw: events.__setitem__("RUN_RESUMED", events["RUN_RESUMED"] + 1))
    bus.subscribe(Events.RUN_STOPPED, lambda **kw: events.__setitem__("RUN_STOPPED", events["RUN_STOPPED"] + 1))
    pause_req = []
    resume_req = []
    bus.subscribe(Events.PAUSE_REQUESTED, lambda **kw: pause_req.append(kw))
    bus.subscribe(Events.RESUME_REQUESTED, lambda **kw: resume_req.append(kw))

    def wait_until(cond, timeout=5.0):
        deadline = time.time() + timeout
        while not cond() and time.time() < deadline:
            time.sleep(0.03)
        return cond()

    # ═══ 0. 启动并等待首个任务完成 ═══
    cb.btn_start.click()
    wait_until(lambda: sm.get_state("run_status") == "running")
    # 模拟 MainWindow._on_run_started → control_bar.set_running(True)（启用暂停/停止按钮）
    cb.set_running(True)
    wait_until(lambda: len(sched.marked) >= 1)  # task_a 完成
    check("0 启动后 task_a 完成", sched.marked == [("task_a", True)], str(sched.marked))

    # ═══ ① 点击暂停 ═══
    cb.btn_pause.click()  # 文本「⏸ 暂停」→ 发 pause + 文本「▶ 继续」
    wait_until(lambda: ctrl.is_paused)
    check("① PAUSE_REQUESTED 发布", len(pause_req) >= 1)
    check("① is_paused", ctrl.is_paused)
    check("① RUN_PAUSED 发布", events["RUN_PAUSED"] >= 1)
    check("① run_status=paused", sm.get_state("run_status") == "paused")

    # ═══ ② 暂停中任务不消费（暂停后新增到期任务） ═══
    sched._due.append("task_b")  # 暂停期间新任务到期
    time.sleep(1.2)  # 足够 filler/executor 多轮循环
    check("② 暂停中 task_b 未被消费", len(sched.marked) == 1,
          f"已消费 {len(sched.marked)} 个")
    _stats = getattr(mon, "_task_stats", {})
    check("② 任务完成统计仍 1 次",
          _stats.get("task_a") is not None and _stats["task_a"].total == 1,
          str(getattr(_stats.get("task_a"), "total", None)))

    # ═══ ③ 【漏洞修复】暂停中收到 START_REQUESTED 不重启 ═══
    filler_before = id(ctrl._filler_thread)
    time.sleep(0.3)  # 越过 EventBus 去重窗口
    cb.btn_start.click()  # 等价于误发 start_requested
    time.sleep(0.6)
    check("③ 暂停中 start 请求被拦截", ctrl.is_paused,
          f"status={ctrl.status}")
    check("③ 未重启线程", id(ctrl._filler_thread) == filler_before)
    check("③ run_status 仍 paused", sm.get_state("run_status") == "paused")

    # ═══ ④ 继续 → 任务恢复消费 ═══
    cb.btn_pause.click()  # 文本「▶ 继续」→ 发 resume + 文本「⏸ 暂停」
    wait_until(lambda: ctrl.is_running)
    check("④ RESUME_REQUESTED 发布", len(resume_req) >= 1)
    check("④ is_running", ctrl.is_running)
    check("④ RUN_RESUMED 发布", events["RUN_RESUMED"] >= 1)
    check("④ run_status=running", sm.get_state("run_status") == "running")
    wait_until(lambda: len(sched.marked) >= 2)  # task_b 完成
    check("④ 恢复后新任务被消费", sched.marked == [
        ("task_a", True), ("task_b", True)], str(sched.marked))

    # ═══ ⑤ UI 文本状态机 ═══
    cb.btn_pause.click()  # 暂停
    wait_until(lambda: ctrl.is_paused)
    check("⑤ 暂停后文本「▶ 继续」", cb.btn_pause.text() == "▶ 继续", cb.btn_pause.text())
    cb.btn_pause.click()  # 继续
    wait_until(lambda: ctrl.is_running)
    check("⑤ 继续后文本「⏸ 暂停」", cb.btn_pause.text() == "⏸ 暂停", cb.btn_pause.text())

    # ═══ ⑥ 暂停中点停止 → 唤醒退出 ═══
    cb.btn_pause.click()  # 暂停
    wait_until(lambda: ctrl.is_paused)
    cb.btn_stop.click()
    wait_until(lambda: sm.get_state("run_status") == "stopped", timeout=6.0)
    check("⑥ RUN_STOPPED 发布", events["RUN_STOPPED"] >= 1)
    check("⑥ 停止后线程退出", (ctrl._filler_thread is None or not ctrl._filler_thread.is_alive())
          and (ctrl._executor_thread is None or not ctrl._executor_thread.is_alive()))
    check("⑥ 停止后 run_status=stopped", sm.get_state("run_status") == "stopped")

    # ═══ ⑦ 边界：停止后暂停按钮禁用（UI 层防护） ═══
    # 模拟 MainWindow._on_run_stopped → set_running(False)：暂停/停止按钮禁用，
    # 启动按钮恢复 → 用户无法在停止态触发暂停（避免 _toggle_pause 文本脱钩）
    cb.set_running(False)
    check("⑦ 停止后暂停按钮禁用", not cb.btn_pause.isEnabled())
    check("⑦ 停止后停止按钮禁用", not cb.btn_stop.isEnabled())
    check("⑦ 停止后启动按钮恢复", cb.btn_start.isEnabled())
    check("⑦ 停止后游戏下拉恢复", cb.combo_game.isEnabled())
    check("⑦ 停止后连接按钮恢复", cb.btn_connect.isEnabled())

    print(f"\n🎉 暂停按钮调用链路验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
