"""
UI 子面板：ControlBar 启停/暂停按钮。
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QWidget


class ControlBar(QWidget):
    """控制栏：启动/停止/暂停按钮"""

    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    resume_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self.btn_start = QPushButton("▶ 启动")
        self.btn_stop = QPushButton("■ 停止")
        self.btn_pause = QPushButton("⏸ 暂停")

        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)

        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_pause)
        layout.addWidget(self.btn_stop)
        layout.addStretch()

        self.btn_start.clicked.connect(self.start_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_pause.clicked.connect(self._toggle_pause)

    def _toggle_pause(self) -> None:
        if self.btn_pause.text() == "⏸ 暂停":
            self.pause_clicked.emit()
            self.btn_pause.setText("▶ 继续")
        else:
            self.resume_clicked.emit()
            self.btn_pause.setText("⏸ 暂停")

    def set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_pause.setEnabled(running)
