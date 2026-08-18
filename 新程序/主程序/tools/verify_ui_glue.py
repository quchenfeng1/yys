"""验证：UI 胶水链路（子代理审计缺口 #5/#6/#7/#8/#11/#12/#13/#19）。

覆盖：
  1. 时段增删（GameTaskPanel _add_slot_row / _remove_slot_row 边界）
  2. StatusBar 9 项状态显示
  3. MainWindow.closeEvent（确认退出 → RUN_SHUTDOWN；取消 → ignore）
  4. MainWindow.set_theme 主题切换
  5. TaskQueuePanel ⚡触发 卡片按钮点击 → manual_trigger_requested 信号
  6. 连接按钮/沙盒后端链路：ControlBar.btn_connect → connect_toggled；RunBridge.set_dry_mode → ctrl
  7. LogPanel.export_log 实际写文件
"""
import os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def main():
    from PyQt5.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])

    # ═══ 1. 时段增删 ═══
    print("\n[1] 时段增删边界")
    from ui.panels.game_task_panel import GameTaskPanel
    bridge = SimpleNamespace(task=SimpleNamespace(
        get_task_detail=lambda n: {"name": n, "display_name": n, "task_type": "daily",
                                   "uses_battle": False, "repeat": {"type": "daily", "value": 1},
                                   "time_start": "06:00", "time_end": "23:59",
                                   "time_slots": None, "max_daily": 0,
                                   "next_run_time": ""},
        get_next_run_time=lambda n: None))
    panel = GameTaskPanel(param_bridge=bridge)
    panel.load_tasks([{"name": "t", "display_name": "t", "task_type": "daily",
                       "uses_battle": False}])
    panel.task_list.setCurrentRow(0)
    n0 = len(panel._slot_rows)
    panel._add_slot_row("10:00", "12:00")
    check("1a 添加时段 → 行数+1", len(panel._slot_rows) == n0 + 1,
          f"{len(panel._slot_rows)}")
    check("1b 新行值正确", panel._slot_rows[-1][0].text() == "10:00"
          and panel._slot_rows[-1][1].text() == "12:00",
          f"{panel._slot_rows[-1][0].text()}/{panel._slot_rows[-1][1].text()}")
    row_w, pair = panel._slot_row_widgets[-1], panel._slot_rows[-1]
    panel._remove_slot_row(row_w, pair)
    check("1c 删除时段 → 行数-1", len(panel._slot_rows) == n0, str(len(panel._slot_rows)))
    # 删到只剩 1 行时拒绝
    while len(panel._slot_rows) > 1:
        rw, pr = panel._slot_row_widgets[-1], panel._slot_rows[-1]
        panel._remove_slot_row(rw, pr)
    before = len(panel._slot_rows)
    panel._remove_slot_row(panel._slot_row_widgets[-1], panel._slot_rows[-1])
    check("1d 至少保留一行", len(panel._slot_rows) == 1 and before == 1,
          f"{len(panel._slot_rows)}")

    # ═══ 2. StatusBar 9 项 ═══
    print("\n[2] StatusBar 9 项状态显示")
    from ui.panels.status_bar import StatusBar
    sb = StatusBar()
    sb.update_run_status("running")
    check("2a 运行状态", sb.status_label.text() == "运行中", sb.status_label.text())
    sb.update_run_status("paused")
    check("2b 暂停状态", sb.status_label.text() == "已暂停", sb.status_label.text())
    sb.update_current_task("task_a")
    check("2c 当前任务", sb.task_label.text() == "当前: task_a", sb.task_label.text())
    sb.update_current_task(None)
    check("2d 清空任务", sb.task_label.text() == "", sb.task_label.text())
    sb.update_current_scene("courtyard")
    check("2e 当前场景", "courtyard" in sb.scene_label.text(), sb.scene_label.text())
    sb.update_connection("connected")
    check("2f 连接状态", "已连接" in sb.connection_label.text(), sb.connection_label.text())
    sb.update_quality("good")
    check("2g 连接质量", "良好" in sb.connection_label.text(), sb.connection_label.text())
    sb.update_current_account("main1")
    check("2h 当前账号", "main1" in sb.account_label.text(), sb.account_label.text())
    sb.update_run_duration(3661)
    check("2i 运行时长", sb.duration_label.text() == "时长: 01:01:01", sb.duration_label.text())
    sb.update_queue_length(3)
    check("2j 队列长度", "3" in sb.queue_label.text(), sb.queue_label.text())
    sb.reset_all()
    check("2k 重置", sb.status_label.text() == "就绪", sb.status_label.text())

    # ═══ 3. closeEvent ═══
    print("\n[3] closeEvent 退出确认")
    from core.event_bus import EventBus
    from core.events import Events
    import ui.main_window as mw
    from ui.main_window import MainWindow
    win = MainWindow.__new__(MainWindow)
    bus = EventBus()
    win._bus = bus
    shutdown = []
    bus.subscribe(Events.RUN_SHUTDOWN, lambda **kw: shutdown.append(kw))
    class FakeEvent:
        def __init__(self):
            self.accepted = False
            self.ignored = False
        def accept(self):
            self.accepted = True
        def ignore(self):
            self.ignored = True
    orig_q = mw.QMessageBox.question
    mw.QMessageBox.question = lambda *a, **k: QMessageBox.Yes
    try:
        ev = FakeEvent()
        win.closeEvent(ev)
        import time
        time.sleep(0.4)  # 等待 EventBus dispatch 线程处理事件
    finally:
        mw.QMessageBox.question = orig_q
    check("3a 确认退出 → RUN_SHUTDOWN 发布", len(shutdown) == 1, str(len(shutdown)))
    check("3b 确认退出 → accept()", ev.accepted and not ev.ignored, "")
    mw.QMessageBox.question = lambda *a, **k: QMessageBox.No
    try:
        ev2 = FakeEvent()
        win.closeEvent(ev2)
    finally:
        mw.QMessageBox.question = orig_q
    check("3c 取消退出 → ignore()，不发布", ev2.ignored and len(shutdown) == 1, "")

    # ═══ 4. 主题切换 ═══
    print("\n[4] 主题切换")
    applied = []
    orig_apply = mw.apply_theme
    mw.apply_theme = lambda app, theme=None: applied.append(theme)
    try:
        win2 = MainWindow.__new__(MainWindow)
        win2._current_theme = None
        win2.set_theme("dark")
    finally:
        mw.apply_theme = orig_apply
    check("4a set_theme('dark') → apply_theme 被调", applied == ["dark"], str(applied))
    check("4b _current_theme 记录", win2._current_theme == "dark", str(getattr(win2, '_current_theme', None)))

    # ═══ 5. 触发胶水 ═══
    print("\n[5] ⚡触发卡片按钮 → 信号")
    from ui.panels.task_queue_panel import TaskQueuePanel
    qp = TaskQueuePanel()
    got = []
    qp.manual_trigger_requested.connect(lambda n: got.append(n))
    qp.update_panel(None, [], [],
                    [{"name": "trigger_a", "status": "待触发", "detail": ""}])
    from PyQt5.QtWidgets import QPushButton
    btns = qp.invalid_list.findChildren(QPushButton)
    check("5a 待触发卡片含⚡触发按钮", len(btns) >= 1 and "触发" in btns[0].text(),
          f"按钮数={len(btns)}")
    if btns:
        btns[0].click()
    check("5b 点击按钮 → manual_trigger_requested('trigger_a')",
          got == ["trigger_a"], str(got))

    # ═══ 6. 连接按钮/沙盒后端链路（2026-08-16：沙盒 UI 移除，后端保留） ═══
    print("\n[6] 连接按钮 + 沙盒后端链路")
    from ui.panels.control_bar import ControlBar
    from ui.param_bridge.run_bridge import RunBridge
    cb = ControlBar()
    toggles = []
    cb.connect_toggled.connect(lambda: toggles.append(True))
    cb.btn_connect.click()
    check("6a btn_connect → connect_toggled", toggles == [True], str(toggles))
    ctrl = SimpleNamespace(set_dry_mode=lambda v: setattr(ctrl, "_dry", bool(v)),
                           dry=False)
    ctrl._dry = False
    rb = RunBridge(event_bus=EventBus())
    rb.set_controller(ctrl)
    rb.set_dry_mode(True)
    check("6b RunBridge.set_dry_mode → ctrl.set_dry_mode(True)",
          ctrl._dry is True, str(ctrl._dry))

    # ═══ 7. export_log 实际写文件 ═══
    print("\n[7] 日志导出写文件")
    from ui.panels.log_panel import LogPanel
    import ui.panels.log_panel as lp
    log_panel = LogPanel()
    log_panel.append_log(level="INFO", message="测试日志行")
    tmp_dir = tempfile.mkdtemp()
    out_path = os.path.join(tmp_dir, "yys_log.txt")
    orig_save = lp.QFileDialog.getSaveFileName
    lp.QFileDialog.getSaveFileName = lambda *a, **k: (out_path, "文本文件 (*.txt)")
    try:
        log_panel.export_log()
    finally:
        lp.QFileDialog.getSaveFileName = orig_save
    check("7a 导出文件已创建", os.path.exists(out_path), out_path)
    if os.path.exists(out_path):
        content = Path(out_path).read_text(encoding="utf-8")
        check("7b 文件含缓存日志", "测试日志行" in content, content)

    print(f"\n🎉 UI 胶水链路验证 {PASS} 项通过"
          + ("" if FAIL == 0 else f"，失败 {FAIL} 项"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
