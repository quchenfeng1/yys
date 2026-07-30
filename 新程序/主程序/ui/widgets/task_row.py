"""
11-用户界面模块

TaskRow 可复用组件（§5.1）。
单行任务配置控件：启用开关 + 名称 + 优先级 + 规则编辑器。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QSpinBox, QWidget,
)


class TaskRow(QWidget):
    """单行任务配置控件"""

    def __init__(self, task_name: str, parent=None):
        super().__init__(parent)
        self.task_name = task_name
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self.enabled_cb = QCheckBox()
        layout.addWidget(self.enabled_cb)

        self.name_label = QLabel(self.task_name)
        self.name_label.setMinimumWidth(120)
        layout.addWidget(self.name_label)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 99)
        self.priority_spin.setValue(10)
        layout.addWidget(self.priority_spin)

        layout.addStretch()

    def get_values(self) -> dict:
        return {
            "name": self.task_name,
            "enabled": self.enabled_cb.isChecked(),
            "priority": self.priority_spin.value(),
        }
