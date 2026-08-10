"""验证：停止中断 vs 异常失败 的 next_run 处理 + UI 异常推迟标注。

规则（本次实现）：
  系统停止中断（interrupted=True）：next_run=当前时间（下次启动立即执行）、
    fail_streak 归零、无推迟标注
  异常失败（识别错误等）：递增冷却（fail_streak×5min ≤ 60min）+ 队列标注"异常推迟"
  熔断（fail_streak ≥ max_fail_streak）：SKIPPED → 归入已失效区"异常熔断"

覆盖：
  ① 停止中断 → next_run≈now、fail_streak 归零、无 defer_reason
  ② 异常失败 → 冷却推进（5min）、fail_streak+1、_defer_reasons 有标注
  ③ 成功 → 正常推进、标注清除
  ④ 熔断 → SKIPPED、_invalid_reason="异常熔断"
  ⑤ get_upcoming 返回 reason
  ⑥ UI：TaskQueuePanel 未开始区显示"异常推迟"徽章
  ⑦ run_controller 真实停止中断场景 → next_run≈now（interrupted 路径）
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


def build_raw(name, rtype="daily", max_fail=10):
    return SimpleNamespace(
        name=name, display_name=name, category="daily", enabled=True,
        priority=10, time_start="06:00", time_end="23:59", max_daily=None,
        active_range=None, total_count=None, execution_mode="daily",
        loop_count=1, time_slots=None, max_fail_streak=max_fail,
        repeat={"type": rtype, "value": 1, "loop_count": 1},
    )


class FakeTask:
    task_id = name = ""
    def __init__(self, name, check_stop=False):
        self.task_id = name
        self.name = name
        self.has_assets = True
        self._check_stop = check_stop
    def execute(self, context):
        stop = getattr(context, 'stop_event', None)
        for _ in range(100):
            if self._check_stop and stop and stop.is_set():
                return SimpleNamespace(success=False, status="failed",
                                       message="interrupted", reason="")
            time.sleep(0.05)
        return SimpleNamespace(success=True, status="success", message="", reason="")


class FakeExec:
    def set_asset_aliases(self, a): pass
    def set_signal_map(self, m): pass
    def set_dry_run(self, v): pass
    def click_if_exists(self, t): return False
    def detect_scene(self, n): return None


class FakeConn:
    def connect(self): return True
    def is_connected(self): return True


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from core.event_bus import EventBus
    from core.scheduler import Scheduler, ScheduleStatus
    from core.task_state import TaskStateStore

    bus = EventBus()
    tmpdir = Path(tempfile.mkdtemp(prefix="interrupt_"))
    store = TaskStateStore(tmpdir / "state.json")

    fake_cfg = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[build_raw("task_x")]))
    sched = Scheduler(event_bus=bus, config=fake_cfg, state_manager=None, store=store)
    sched.load_tasks_from_config()

    now = datetime.now(sched._timezone)

    # ═══ ① 停止中断：mark_done(False, interrupted=True) ═══
    sched.mark_done("task_x", False, interrupted=True)
    nrt = sched._next_run.get("task_x")
    st = sched.task_status.get("task_x")
    fs = (store.get("task_x") or {}).get('fail_streak', 0)
    delta = nrt - now if nrt else timedelta(hours=99)
    check("① 停止中断 next_run≈now", abs(delta.total_seconds()) < 5,
          f"delta={delta}")
    check("① 停止中断 fail_streak 归零", fs == 0, f"fail_streak={fs}")
    check("① 停止中断无推迟标注", not sched._defer_reasons.get("task_x"),
          str(sched._defer_reasons.get("task_x")))

    # ═══ ② 异常失败：mark_done(False) ═══
    sched.mark_done("task_x", False)
    nrt = sched._next_run.get("task_x")
    fs = (store.get("task_x") or {}).get('fail_streak', 0)
    delta = nrt - now if nrt else timedelta(hours=99)
    check("② 异常失败冷却≈5分钟", 240 <= delta.total_seconds() <= 360,
          f"delta={delta}")
    check("② 异常失败 fail_streak=1", fs == 1, f"fail_streak={fs}")
    check("② 有异常推迟标注", "异常推迟" in (sched._defer_reasons.get("task_x") or ""),
          str(sched._defer_reasons.get("task_x")))

    # ═══ ③ 成功：清除标注 + 正常推进 ═══
    sched.mark_done("task_x", True)
    check("③ 成功后标注清除", not sched._defer_reasons.get("task_x"))
    nrt = sched._next_run.get("task_x")
    check("③ 成功后正常推进(明天)", nrt is not None and nrt > now + timedelta(hours=12),
          str(nrt))

    # ═══ ④ 熔断：连续失败到 max_fail ═══
    sched2_store = TaskStateStore(tmpdir / "state2.json")
    fake_cfg2 = SimpleNamespace(tasks_config=SimpleNamespace(
        tasks=[build_raw("task_y", max_fail=3)]))
    sched2 = Scheduler(event_bus=bus, config=fake_cfg2, state_manager=None,
                       store=sched2_store)
    sched2.load_tasks_from_config()
    for _ in range(3):
        sched2.mark_done("task_y", False)
    st = sched2.task_status.get("task_y")
    reason = sched2._invalid_reason(sched2._tasks["task_y"], datetime.now(sched2._timezone), "")
    check("④ 熔断 SKIPPED", st == ScheduleStatus.SKIPPED, str(st))
    check("④ 熔断归入已失效(异常熔断)", reason == "异常熔断", str(reason))

    # ═══ ⑤ get_upcoming 返回 reason ═══
    sched3_store = TaskStateStore(tmpdir / "state3.json")
    fake_cfg3 = SimpleNamespace(tasks_config=SimpleNamespace(
        tasks=[build_raw("task_z")]))
    sched3 = Scheduler(event_bus=bus, config=fake_cfg3, state_manager=None,
                       store=sched3_store)
    sched3.load_tasks_from_config()
    sched3.mark_done("task_z", False)  # 异常失败 → 冷却 + 标注
    upcoming = sched3.get_upcoming()
    entry = next((u for u in upcoming if u["name"] == "task_z"), None)
    check("⑤ get_upcoming 含 reason", entry is not None and "异常推迟" in entry.get("reason", ""),
          str(entry))

    # ═══ ⑥ UI 标注 ═══
    from PyQt5.QtWidgets import QLabel
    from ui.panels.task_queue_panel import TaskQueuePanel
    panel = TaskQueuePanel()
    panel.update_panel(None, [], upcoming, [])
    texts = []
    for i in range(panel.upcoming_list.count()):
        it = panel.upcoming_list.item(i)
        w = panel.upcoming_list.itemWidget(it)
        if w is not None:
            for lab in w.findChildren(QLabel):
                texts.append(lab.text())
    joined = " ".join(texts)
    check("⑥ UI 未开始区显示异常推迟", "异常推迟" in joined and "task_z" in joined,
          joined)

    # ═══ ⑦ run_controller 真实停止中断 ═══
    from core.state_manager import StateManager
    from core.monitor import Monitor
    from core.run_controller import RunController
    bus7 = EventBus()
    sm7 = StateManager(event_bus=bus7)
    mon7 = Monitor(event_bus=bus7)
    store7 = TaskStateStore(tmpdir / "state7.json")
    fake_cfg7 = SimpleNamespace(tasks_config=SimpleNamespace(
        tasks=[build_raw("task_w")]))
    sched7 = Scheduler(event_bus=bus7, config=fake_cfg7, state_manager=sm7, store=store7)
    sched7.load_tasks_from_config()

    class Reg:
        def __init__(self):
            self.tasks = {"task_w": FakeTask("task_w", check_stop=True)}
        def get(self, n):
            return self.tasks.get(n)

    ctrl = RunController(
        scheduler=sched7, connection=FakeConn(), config=None, state_mgr=sm7,
        registry=Reg(), executor=FakeExec(), recognizer=None,
        event_bus=bus7, monitor=mon7, account_mgr=None,
    )
    ctrl.execute()
    deadline = time.time() + 5
    while ctrl.current_task != "task_w" and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.2)
    ctrl.stop()  # 执行中停止 → 任务 check_stop 提前退出 → interrupted
    nrt7 = sched7._next_run.get("task_w")
    delta7 = abs((nrt7 - datetime.now(sched7._timezone)).total_seconds()) if nrt7 else 999
    st7 = sched7.task_status.get("task_w")
    check("⑦ 真实停止中断 next_run≈now", delta7 < 5,
          f"nrt={nrt7} delta={delta7}")
    check("⑦ 真实停止中断 status=waiting", st7 == ScheduleStatus.WAITING, str(st7))
    check("⑦ 真实停止中断无推迟标注", not sched7._defer_reasons.get("task_w"))

    print(f"\n🎉 停止中断/异常失败处理验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
