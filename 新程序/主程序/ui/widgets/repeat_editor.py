"""
11-用户界面模块

RepeatEditor 可复用组件（§5.1）。
任务执行规则编辑器：类型选择 + 间隔/时间参数。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QSpinBox,
    QTimeEdit, QWidget,
)


class RepeatEditor(QGroupBox):
    """执行规则编辑器"""

    def __init__(self, parent=None):
        super().__init__("执行规则", parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)

        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "daily", "weekly", "monthly", "interval_days",
            "interval_hours", "once", "special",
        ])
        layout.addRow("类型:", self.type_combo)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 365)
        self.interval_spin.setValue(1)
        layout.addRow("间隔:", self.interval_spin)

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        layout.addRow("时间:", self.time_edit)

    def get_rule(self) -> dict:
        return {
            "type": self.type_combo.currentText(),
            "value": self.interval_spin.value(),
            "time": self.time_edit.text(),
        }
