"""
任务行组件（11-用户界面模块）

单行任务展示：名称 + 启用开关 + 优先级 + 状态 + 操作按钮。
用于游戏任务列表和任务管理面板中复用。
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QCheckBox, QSpinBox, QPushButton,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


# 优先级 → 色标
PRIORITY_COLORS = {
    1: "#EA4335", 2: "#F9AB00", 3: "#FBBC04",
    5: "#34A853", 10: "#1A73E8", 20: "#9334E6", 99: "#80868B",
}


class TaskRow(QWidget):
    """任务行组件：启用/名称/优先级/状态。"""

    toggled = pyqtSignal(str, bool)      # task_name, enabled
    priority_changed = pyqtSignal(str, int)  # task_name, value
    skip_clicked = pyqtSignal(str)       # task_name
    single_step_clicked = pyqtSignal(str)  # task_name

    def __init__(self, task_name: str, enabled: bool = False,
                 priority: int = 10, status: str = "等待中",
                 parent=None):
        super().__init__(parent)
        self.task_name = task_name
        self._build(enabled, priority, status)

    def _build(self, enabled: bool, priority: int, status: str):
        ly = QHBoxLayout(self)
        ly.setContentsMargins(8, 4, 8, 4)
        ly.setSpacing(10)

        # 启用开关
        self._enabled = QCheckBox()
        self._enabled.setChecked(enabled)
        self._enabled.toggled.connect(
            lambda v: self.toggled.emit(self.task_name, v))
        ly.addWidget(self._enabled)

        # 任务名
        name_lbl = QLabel(self.task_name)
        name_lbl.setFont(QFont("Microsoft YaHei", 10))
        name_lbl.setMinimumWidth(100)
        ly.addWidget(name_lbl)

        # 优先级
        prio_lbl = QLabel(f"P{priority}")
        color = PRIORITY_COLORS.get(priority, "#80868B")
        prio_lbl.setStyleSheet(
            f"color:white;background:{color};border-radius:4px;"
            f"padding:2px 8px;font-size:11px;font-weight:bold;")
        ly.addWidget(prio_lbl)
        self._prio_label = prio_lbl

        # 状态
        status_lbl = QLabel(status)
        status_lbl.setStyleSheet("color:#5F6368;font-size:12px;")
        ly.addWidget(status_lbl)
        self._status_label = status_lbl

        ly.addStretch()

        # 跳过按钮
        skip_btn = QPushButton("跳过")
        skip_btn.setFixedSize(50, 24)
        skip_btn.setStyleSheet("""
            QPushButton{background:#F1F3F4;color:#5F6368;border:none;
            border-radius:4px;font-size:11px;}
            QPushButton:hover{background:#F9AB00;color:white;}
        """)
        skip_btn.clicked.connect(lambda: self.skip_clicked.emit(self.task_name))
        ly.addWidget(skip_btn)

        # 单步按钮
        step_btn = QPushButton("单步")
        step_btn.setFixedSize(50, 24)
        step_btn.setStyleSheet("""
            QPushButton{background:#E3F0FF;color:#1A73E8;border:none;
            border-radius:4px;font-size:11px;}
            QPushButton:hover{background:#1A73E8;color:white;}
        """)
        step_btn.clicked.connect(lambda: self.single_step_clicked.emit(self.task_name))
        ly.addWidget(step_btn)

        self.setStyleSheet("TaskRow:hover{background:#F8F9FA;border-radius:6px;}")

    def set_status(self, status: str):
        self._status_label.setText(status)

    def set_priority(self, priority: int):
        color = PRIORITY_COLORS.get(priority, "#80868B")
        self._prio_label.setText(f"P{priority}")
        self._prio_label.setStyleSheet(
            f"color:white;background:{color};border-radius:4px;"
            f"padding:2px 8px;font-size:11px;font-weight:bold;")
