"""
UI 子面板：ImageManagerPanel 素材管理。
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QGridLayout, QLabel, QListWidget, QPushButton,
    QVBoxLayout, QWidget,
)


class ImageManagerPanel(QWidget):
    """素材管理面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # 分组列表
        self.group_list = QListWidget()
        layout.addWidget(QLabel("素材分组"))
        layout.addWidget(self.group_list)

        # 素材列表
        self.asset_list = QListWidget()
        layout.addWidget(QLabel("素材列表"))
        layout.addWidget(self.asset_list)

        # 操作按钮
        btn_layout = QGridLayout()
        btn_layout.addWidget(QPushButton("扫描目录"), 0, 0)
        btn_layout.addWidget(QPushButton("删除素材"), 0, 1)
        btn_layout.addWidget(QPushButton("刷新"), 1, 0)
        layout.addLayout(btn_layout)
