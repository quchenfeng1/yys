"""UI 主题预览：离屏渲染关键面板并保存截图（验证美观 + 滚动条）。"""
import sys, os
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import (QApplication, QWidget, QHBoxLayout, QVBoxLayout,
                             QSplitter, QLabel, QFormLayout, QGroupBox,
                             QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
                             QRadioButton)
from PyQt5.QtCore import Qt
from ui.theme import apply_theme
from ui.panels.control_bar import ControlBar


def main():
    app = QApplication(sys.argv)
    apply_theme(app)

    from ui.panels.task_queue_panel import TaskQueuePanel
    from ui.panels.task_manager_panel import TaskManagerPanel
    from ui.panels.image_manager_panel import ImageManagerPanel

    # 队列面板（数据）
    qp = TaskQueuePanel()
    qp.update_panel(
        current="combat_test  (战斗测试)",
        pending=[
            {"name": "combat_test", "next_run": "08-04 06:00", "priority": 5},
            {"name": "daily_test", "next_run": "08-04 06:00", "priority": 10},
        ],
        upcoming=[{"name": "once_test", "next_run": "08-04 06:00"}],
        invalid=[
            {"name": "trig_test", "status": "待触发", "detail": "等待外部触发（按钮/识图）"},
            {"name": "old_task", "status": "已过期", "detail": "累计 5/5 次已完成"},
        ],
    )

    # 任务管理面板（任务 + 通用模块）
    tm = TaskManagerPanel()
    tm.load_tasks([
        {"name": "daily_test", "display_name": "日常测试", "category": "daily",
         "task_type": "event_task"},
        {"name": "combat_test", "display_name": "战斗测试", "category": "special",
         "task_type": "battle", "uses_battle": True},
        {"name": "once_test", "display_name": "单次测试", "category": "special",
         "task_type": "on_enter"},
    ])
    tm.load_generic([
        {"name": "soul_configure", "display_name": "御魂配置", "category": "common"},
        {"name": "pre_battle_prep", "display_name": "战前准备", "category": "common"},
    ])
    tm._current_is_generic = False
    tm._render_detail({"name": "combat_test", "display_name": "战斗测试",
                       "category": "special", "task_type": "battle",
                       "uses_battle": True, "description": "战斗测试任务"})

    # 素材管理面板
    im = ImageManagerPanel()

    # 输入控件 demo（数值框增减按钮可读性）
    demo = QWidget()
    dl = QVBoxLayout(demo)
    gb = QGroupBox("输入控件 Demo")
    form = QFormLayout(gb)
    sp1 = QSpinBox(); sp1.setRange(0, 100); sp1.setValue(42)
    sp2 = QDoubleSpinBox(); sp2.setRange(0, 100); sp2.setValue(12.5)
    cb = QComboBox(); cb.addItems(["选项A", "选项B", "选项C"])
    ch1 = QCheckBox("勾选状态"); ch1.setChecked(True)
    ch2 = QCheckBox("未勾选状态")
    r1 = QRadioButton("单选一"); r1.setChecked(True)
    r2 = QRadioButton("单选二")
    form.addRow("QSpinBox:", sp1)
    form.addRow("QDoubleSpinBox:", sp2)
    form.addRow("QComboBox:", cb)
    ch_row = QWidget(); ch_l = QHBoxLayout(ch_row); ch_l.setContentsMargins(0, 0, 0, 0)
    ch_l.addWidget(ch1); ch_l.addWidget(ch2)
    form.addRow("QCheckBox:", ch_row)
    rd_row = QWidget(); rd_l = QHBoxLayout(rd_row); rd_l.setContentsMargins(0, 0, 0, 0)
    rd_l.addWidget(r1); rd_l.addWidget(r2)
    form.addRow("QRadioButton:", rd_row)
    dl.addWidget(gb)
    dl.addStretch()

    # 组合展示
    win = QWidget()
    win.setWindowTitle("主题预览")
    win.resize(1500, 780)
    outer = QVBoxLayout(win)
    outer.setContentsMargins(10, 10, 10, 10)
    outer.setSpacing(8)
    outer.addWidget(ControlBar())
    lay = QHBoxLayout()
    lay.setSpacing(10)
    lay.addWidget(qp, 1)
    lay.addWidget(tm, 2)
    lay.addWidget(im, 2)
    lay.addWidget(demo, 1)
    outer.addLayout(lay, 1)
    win.show()
    app.processEvents()

    out = os.path.join(_PROJ_ROOT, "ui_theme_preview.png")
    win.grab().save(out)
    print(f"预览已保存: {out}")
    print("面板无崩溃，主题应用成功")


if __name__ == "__main__":
    main()
