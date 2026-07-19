"""
全局控制栏（v2.2 现代风格）

启动/停止/暂停三按钮 + 当前状态提示。
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


BTN_STYLE_START = """
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #34A853, stop:1 #2E7D32);
        color: white; font-weight: bold; font-size: 14px;
        border: none; border-radius: 10px;
        padding: 10px 28px; min-width: 100px;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #3CBC5C, stop:1 #348A38);
    }
    QPushButton:pressed {
        background: #2E7D32;
    }
"""

BTN_STYLE_STOP = """
    QPushButton {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #EA4335, stop:1 #C5221F);
        color: white; font-weight: bold; font-size: 14px;
        border: none; border-radius: 10px;
        padding: 10px 28px; min-width: 100px;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F15B4E, stop:1 #D93025);
    }
    QPushButton:pressed {
        background: #C5221F;
    }
"""

BTN_STYLE_PAUSE = """
    QPushButton {
        background: #F9AB00;
        color: white; font-weight: bold; font-size: 14px;
        border: none; border-radius: 10px;
        padding: 10px 24px; min-width: 90px;
    }
    QPushButton:hover { background: #FCC934; }
    QPushButton:pressed { background: #E8A000; }
"""

BTN_STYLE_DISABLED = """
    QPushButton {
        background: #DADCE0; color: #80868B;
        font-weight: bold; font-size: 14px;
        border: none; border-radius: 10px;
        padding: 10px 28px; min-width: 100px;
    }
"""


class ControlBar(QWidget):
    """全局控制栏。"""

    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._paused = False
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 6)
        layout.setSpacing(12)

        self.start_btn = QPushButton("▶  启  动")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setStyleSheet(BTN_STYLE_START)
        self.start_btn.clicked.connect(self._on_start)

        self.stop_btn = QPushButton("■  停  止")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setStyleSheet(BTN_STYLE_DISABLED)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)

        self.pause_btn = QPushButton("⏸  暂  停")
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.setStyleSheet(BTN_STYLE_DISABLED)
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause)

        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.pause_btn)

        self.status_label = QLabel("●  就绪")
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        self.status_label.setStyleSheet("color: #80868B; margin-left: 12px;")
        layout.addWidget(self.status_label)

        layout.addStretch()

    def _on_start(self):
        if self._paused:
            self.set_running(True)
            self.pause_clicked.emit()  # 复用暂停信号表示恢复
        else:
            self.set_running(True)
            self.start_clicked.emit()

    def _on_stop(self):
        self.set_idle()
        self.stop_clicked.emit()

    def _on_pause(self):
        self.set_paused(True)
        self.pause_clicked.emit()

    def set_running(self, running: bool):
        self._running = running
        self._paused = False
        self.start_btn.setText("▶  运行中")
        self.start_btn.setStyleSheet(BTN_STYLE_DISABLED)
        self.start_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(BTN_STYLE_STOP)
        self.stop_btn.setEnabled(True)
        self.pause_btn.setStyleSheet(BTN_STYLE_PAUSE)
        self.pause_btn.setEnabled(True)
        self.status_label.setText("●  运行中")
        self.status_label.setStyleSheet("color: #1A73E8; font-weight: bold; margin-left: 12px;")

    def set_paused(self, paused: bool):
        self._paused = paused
        if paused:
            self.start_btn.setText("▶  继  续")
            self.start_btn.setStyleSheet(BTN_STYLE_START.replace("34A853", "1A73E8").replace("2E7D32", "1557B0"))
            self.start_btn.setEnabled(True)
            self.pause_btn.setStyleSheet(BTN_STYLE_DISABLED)
            self.pause_btn.setEnabled(False)
            self.status_label.setText("⏸  已暂停")
            self.status_label.setStyleSheet("color: #F9AB00; font-weight: bold; margin-left: 12px;")
        else:
            self.set_running(True)

    def set_idle(self):
        self._running = False
        self._paused = False
        self.start_btn.setText("▶  启  动")
        self.start_btn.setStyleSheet(BTN_STYLE_START)
        self.start_btn.setEnabled(True)
        self.stop_btn.setStyleSheet(BTN_STYLE_DISABLED)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setStyleSheet(BTN_STYLE_DISABLED)
        self.pause_btn.setEnabled(False)
        self.status_label.setText("●  就绪")
        self.status_label.setStyleSheet("color: #80868B; margin-left: 12px;")
