"""
11-用户界面模块

UI 自控面板（元控面板，§3.8）。
控制 UI 自身行为，不涉及程序核心配置。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)


class UISettingsPanel(QWidget):
    """UI 自身设置面板（§3.8）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        # ── 日志设置 ───────────────────────────────────────
        log_group = QGroupBox("日志设置")
        log_layout = QVBoxLayout(log_group)

        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setCurrentText("INFO")
        log_layout.addWidget(QLabel("日志级别:"))
        log_layout.addWidget(self.log_level_combo)

        self.auto_scroll_cb = QCheckBox("自动滚动")
        self.auto_scroll_cb.setChecked(True)
        log_layout.addWidget(self.auto_scroll_cb)

        layout.addWidget(log_group)

        # ── 字体设置 ───────────────────────────────────────
        font_group = QGroupBox("终端字体")
        font_layout = QVBoxLayout(font_group)

        self.font_size_slider = QSlider(Qt.Horizontal)
        self.font_size_slider.setRange(8, 24)
        self.font_size_slider.setValue(12)
        font_layout.addWidget(QLabel("字体大小:"))
        font_layout.addWidget(self.font_size_slider)

        layout.addWidget(font_group)

        # ── 面板操作 ───────────────────────────────────────
        action_group = QGroupBox("面板操作")
        action_layout = QVBoxLayout(action_group)

        reset_btn = QPushButton("重置面板布局")
        reset_btn.clicked.connect(self._reset_layout)
        action_layout.addWidget(reset_btn)

        layout.addWidget(action_group)

        # 弹簧
        layout.addStretch()

    def _reset_layout(self) -> None:
        """重置 QSplitter 默认比例"""
        window = self.window()
        if window and hasattr(window, 'splitter'):
            sizes = [250, 750, 300]
            window.splitter.setSizes(sizes)
