"""
UI 子面板：ConfigPanel 内联配置面板。
"""
from __future__ import annotations

from PyQt5.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget


class ConfigPanel(QWidget):
    """配置面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        group = QGroupBox("全局配置")
        form = QFormLayout(group)
        form.addRow("ADB 主机:", QLabel("127.0.0.1"))
        form.addRow("ADB 端口:", QLabel("5037"))
        form.addRow("截屏方式:", QLabel("adb"))
        form.addRow("模板匹配阈值:", QLabel("0.8"))
        form.addRow("最小操作间隔:", QLabel("0.5s"))
        layout.addWidget(group)
        layout.addStretch()
