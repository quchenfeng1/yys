
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = r"d:/yys/新程序/主程序"
sys.path.insert(0, _ROOT)
from PyQt5.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)
    from ui.theme import apply_theme
    apply_theme(app)
    from ui.panels.task_queue_panel import TaskQueuePanel
    panel = TaskQueuePanel()
    panel.update_panel(
        current="combat_test  (战斗测试)",
        pending=[
            {"name": "combat_test", "next_run": "08-04 06:00", "priority": 5},
            {"name": "daily_test", "next_run": "08-04 06:00", "priority": 10},
        ],
        upcoming=[
            {"name": "once_test", "next_run": "08-04 06:00"},
            {"name": "unplanned", "next_run": ""},
        ],
        invalid=[
            {"name": "trig_test", "status": "待触发", "detail": "等待外部触发（按钮/识图）"},
            {"name": "old_task", "status": "已过期", "detail": "累计 5/5 次已完成"},
            {"name": "once_test", "status": "本轮已完成", "detail": "下次启动执行"},
        ],
    )
    app.processEvents()
    from PyQt5.QtWidgets import QPushButton, QLabel
    btns = panel.invalid_list.findChildren(QPushButton)
    up_btns = panel.upcoming_list.findChildren(QPushButton)
    card = panel.upcoming_list.itemWidget(panel.upcoming_list.item(0))
    labels = [lbl.text() for lbl in card.findChildren(QLabel)]
    panel.drawer_btn.click()
    panel.drawer_btn.click()
    panel.resize(1000, 620)
    panel.show()
    app.processEvents()
    shot = panel.grab()
    out = os.path.join(_ROOT, "ui_queue_preview.png")
    shot.save(out)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
