"""
11-用户界面模块

TeamEditor 可复用组件（§5.1）。
阵容编辑器：选择预设阵容并配置组队参数。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel,
    QSpinBox, QVBoxLayout, QWidget,
)


class TeamEditor(QGroupBox):
    """阵容编辑器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 10)
        outer.setSpacing(4)
        outer.addWidget(QLabel("阵容配置"))
        layout = QFormLayout()
        outer.addLayout(layout)

        self.team_combo = QComboBox()
        self.team_combo.addItems(["默认", "主力", "备用", "活动"])
        layout.addRow("预设阵容:", self.team_combo)

        self.teaming_cb = QCheckBox("需要组队")
        layout.addRow(self.teaming_cb)

        self.max_wait_spin = QSpinBox()
        self.max_wait_spin.setRange(10, 300)
        self.max_wait_spin.setValue(120)
        self.max_wait_spin.setSuffix(" 秒")
        layout.addRow("最长等待:", self.max_wait_spin)

    def get_config(self) -> dict:
        return {
            "team_id": self.team_combo.currentText(),
            "teaming": self.teaming_cb.isChecked(),
            "wait_timeout": self.max_wait_spin.value(),
        }
