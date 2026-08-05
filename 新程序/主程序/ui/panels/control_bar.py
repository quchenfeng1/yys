"""
UI 子面板：ControlBar 启停/暂停按钮。
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QHBoxLayout, QPushButton, QWidget,
)


class ControlBar(QWidget):
    """控制栏：启动/停止/暂停 + 沙盒开关 + 自检按钮"""

    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    resume_clicked = pyqtSignal()
    dry_run_toggled = pyqtSignal(bool)  # §3.7 沙盒开关
    self_check_clicked = pyqtSignal()   # §3.7 自检按钮

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self.btn_start = QPushButton("▶ 启动")
        self.btn_stop = QPushButton("■ 停止")
        self.btn_pause = QPushButton("⏸ 暂停")

        # 图标（qtawesome，仅样式）
        from ui.theme import icon
        _ic = icon("fa5s.play-circle", "#2e7d32")
        if _ic:
            self.btn_start.setIcon(_ic)
        _ic = icon("fa5s.stop-circle", "#c62828")
        if _ic:
            self.btn_stop.setIcon(_ic)
        _ic = icon("fa5s.pause-circle", "#ef6c00")
        if _ic:
            self.btn_pause.setIcon(_ic)

        # §3.7 沙盒开关 + 自检按钮（设计书 §3.7 按钮状态表）
        self.chk_dry_run = QCheckBox("🧪 沙盒")
        self.chk_dry_run.setToolTip("沙盒模式：只走流程不实际点击（用于试跑验证）")
        self.btn_self_check = QPushButton("🔍 自检")
        self.btn_self_check.setToolTip("检查 ADB 连接 / 素材完整性 / 配置 / 依赖")

        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)

        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_pause)
        layout.addWidget(self.btn_stop)
        layout.addSpacing(16)
        layout.addWidget(self.chk_dry_run)
        layout.addWidget(self.btn_self_check)
        layout.addStretch()

        self.btn_start.clicked.connect(self.start_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.chk_dry_run.toggled.connect(self.dry_run_toggled.emit)
        self.btn_self_check.clicked.connect(self.self_check_clicked.emit)

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
        self.chk_dry_run.setEnabled(not running)
        # 运行开始时暂停按钮复位为「⏸ 暂停」
        if running:
            self.btn_pause.setText("⏸ 暂停")

    def set_paused(self, paused: bool) -> None:
        """更新暂停按钮状态（§3.7 运行启停）"""
        if paused:
            self.btn_pause.setText("▶ 继续")
        else:
            self.btn_pause.setText("⏸ 暂停")
