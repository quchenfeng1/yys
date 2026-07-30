"""
UI 子面板：游戏任务面板（列表+配置表单+日历导入）。
"""
from __future__ import annotations

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget


class GameTaskPanel(QWidget):
    """游戏任务面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)

        # 左侧任务列表
        left = QVBoxLayout()
        left.addWidget(QLabel("任务列表"))
        self.task_list = QListWidget()
        left.addWidget(self.task_list)

        # 右侧配置表单（占位）
        right = QVBoxLayout()
        right.addWidget(QLabel("任务配置"))
        right.addWidget(QLabel("（配置表单占位）"))
        right.addStretch()

        layout.addLayout(left, 1)
        layout.addLayout(right, 2)
