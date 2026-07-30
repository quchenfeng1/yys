"""
UI 子面板：TaskManagerPanel 任务文件管理。
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QVBoxLayout, QWidget,
)


class TaskManagerPanel(QWidget):
    """任务文件管理面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)

        # 左侧任务列表
        left = QVBoxLayout()
        left.addWidget(QLabel("任务库"))
        self.task_list = QListWidget()
        left.addWidget(self.task_list)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(QPushButton("导入"))
        btn_layout.addWidget(QPushButton("导出"))
        btn_layout.addWidget(QPushButton("删除"))
        left.addLayout(btn_layout)

        # 右侧详情
        right = QVBoxLayout()
        right.addWidget(QLabel("任务详情"))
        right.addWidget(QLabel("（详情表单占位）"))
        right.addStretch()

        layout.addLayout(left, 1)
        layout.addLayout(right, 2)

    def load_tasks(self, tasks: list[str]) -> None:
        """加载任务列表（由 MainWindow.refresh_task_list() 调用）"""
        self.task_list.clear()
        for name in tasks:
            self.task_list.addItem(name)
