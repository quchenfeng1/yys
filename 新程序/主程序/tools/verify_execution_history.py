"""验证：执行历史链路（Monitor → StateManager → STATE_CHANGED 事件 → UI 面板）。

背景：执行历史面板此前为死链路——
  ① run_controller 从不调用 record_task_done（无写入入口）
  ② Monitor._state_mgr 从未注入（set_state_manager 无调用方）
  ③ execution_history 状态永远为空 → 面板永远空白
本次修复：bootstrap 注入 StateManager + run_controller 执行前后调用记录方法。

覆盖：
  ① bootstrap 注入：Monitor.set_state_manager 后 _state_mgr 可用
  ② record_task_start + record_task_done → execution_history 追加记录
  ③ STATE_CHANGED 事件发布（key=execution_history）
  ④ 截断 100 条
  ⑤ 失败记录 success=False
  ⑥ UI 面板刷新逻辑（MainWindow._ui_apply_state 同款）→ 表格行数正确
  ⑦ run_controller._executor_loop 含 record_task_start/record_task_done 调用
"""
import os, sys
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL: {label}  {detail}"
    PASS += 1
    print(f"PASS {label}")


def main():
    from core.event_bus import EventBus, get_global_bus
    from core.events import Events
    from core.state_manager import StateManager
    from core.monitor import Monitor

    bus = EventBus()
    sm = StateManager(event_bus=bus)
    mon = Monitor(event_bus=bus)

    # ═══ ① bootstrap 注入 ═══
    check("① 初始 _state_mgr 为 None", mon._state_mgr is None)
    mon.set_state_manager(sm)
    check("① set_state_manager 注入", mon._state_mgr is sm)

    # ═══ ② 记录任务完成 → 追加 execution_history ═══
    events_received = []
    bus.subscribe(Events.STATE_CHANGED, lambda **kw: events_received.append(kw))

    mon.record_task_start("daily_1")
    mon.record_task_done("daily_1", True)  # duration 内部计时

    hist = sm.get_state("execution_history", [])
    check("② 记录追加", isinstance(hist, list) and len(hist) == 1, str(hist))
    rec = hist[0]
    check("② 字段完整",
          rec.get("task_name") == "daily_1" and rec.get("success") is True
          and rec.get("duration", 0) >= 0 and rec.get("timestamp"), str(rec))

    # ═══ ③ STATE_CHANGED 事件发布（EventBus 异步分发，轮询等待） ═══
    import time
    deadline = time.time() + 2.0
    while not any(e.get("key") == "execution_history" for e in events_received) \
            and time.time() < deadline:
        time.sleep(0.02)
    ev = [e for e in events_received if e.get("key") == "execution_history"]
    check("③ 发布 execution_history 事件", len(ev) >= 1, str(events_received[:2]))

    # ═══ ④ 截断 100 条（数据正确性；事件合并由 EventBus 去重窗口决定，另行验证） ═══
    for i in range(120):
        mon.record_task_start(f"t{i}")
        mon.record_task_done(f"t{i}", True, duration=1.0)
    hist = sm.get_state("execution_history", [])
    check("④ 截断 100 条", len(hist) == 100, str(len(hist)))
    check("④ 保留最新", hist[-1]["task_name"] == "t119", hist[-1]["task_name"])

    # 同引用修复验证：逐条写入（间隔 > EventBus 去重窗口 0.2s）→ 每次均发布事件
    # 先等待前面积压事件分发完成，避免干扰增量计数
    deadline = time.time() + 5.0
    while bus.queue_size() > 0 and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.3)

    def _ev_count() -> int:
        return len([e for e in events_received if e.get("key") == "execution_history"])

    ev_before = _ev_count()
    for i in range(5):
        time.sleep(0.25)
        mon.record_task_start(f"e{i}")
        mon.record_task_done(f"e{i}", True, duration=1.0)
    deadline = time.time() + 2.0
    while _ev_count() < ev_before + 5 and time.time() < deadline:
        time.sleep(0.02)
    check("④ 每次写入均发布事件", _ev_count() - ev_before == 5,
          f"{ev_before} → {_ev_count()}")

    # ═══ ⑤ 失败记录 ═══
    mon.record_task_start("f1")
    mon.record_task_done("f1", False, duration=2.5)
    hist = sm.get_state("execution_history", [])
    check("⑤ 失败记录", hist[-1]["task_name"] == "f1" and hist[-1]["success"] is False)

    # ═══ ⑥ UI 面板刷新逻辑（MainWindow._ui_apply_state 同款） ═══
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from ui.panels.execution_history import ExecutionHistoryPanel
    panel = ExecutionHistoryPanel()
    value = sm.get_state("execution_history", [])
    panel.table.setRowCount(0)
    for rec in value[-100:]:
        if isinstance(rec, dict):
            ts = rec.get("timestamp", "")[:19] if rec.get("timestamp") else ""
            status = "成功" if rec.get("success") else "失败"
            duration = f"{rec.get('duration', 0):.1f}s"
            panel.add_record(ts, rec.get("task_name", ""), status, duration)
    check("⑥ 面板行数 = 记录数", panel.table.rowCount() == len(value),
          f"{panel.table.rowCount()} vs {len(value)}")
    last_status = panel.table.item(panel.table.rowCount() - 1, 2).text()
    check("⑥ 最新行为失败", last_status == "失败", last_status)

    # ═══ ⑦ run_controller 执行点已接入 ═══
    import re
    rc_path = Path(_PROJ_ROOT) / "core" / "run_controller.py"
    src = rc_path.read_text(encoding="utf-8")
    check("⑦ 含 record_task_start 调用", "record_task_start(task_name)" in src)
    check("⑦ 含 record_task_done 调用", "record_task_done(task_name, success)" in src)
    # bootstrap 注入
    boot_path = Path(_PROJ_ROOT) / "core" / "bootstrap.py"
    boot_src = boot_path.read_text(encoding="utf-8")
    check("⑦ bootstrap 含 set_state_manager 调用", "mon.set_state_manager(sm)" in boot_src)

    print(f"\n🎉 执行历史链路验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
