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

# §3.8 可显隐面板（key, 显示名, 默认可见）
_PANEL_TOGGLE_ITEMS = [
    ("game_task", "游戏任务", True),
    ("task_queue", "任务队列", True),
    ("task_manager", "任务管理", True),
    ("config", "配置", True),
    ("image", "素材管理", True),
    ("accounts", "小号管理", True),
    ("history", "执行历史", True),
    ("ui_settings", "UI 设置", True),
]


class UISettingsPanel(QWidget):
    """UI 自身设置面板（§3.8）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel_checks: dict[str, QCheckBox] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        # ── 主题设置 ───────────────────────────────────────
        from ui.theme import panel_group
        theme_group, theme_content = panel_group("主题")
        theme_layout = theme_content

        theme_row = QHBoxLayout()
        btn_light = QPushButton("☀ 亮色主题")
        btn_light.clicked.connect(lambda: self._set_theme("light"))
        btn_dark = QPushButton("🌙 暗色主题")
        btn_dark.clicked.connect(lambda: self._set_theme("dark"))
        theme_row.addWidget(btn_light)
        theme_row.addWidget(btn_dark)
        theme_row.addStretch()
        theme_layout.addLayout(theme_row)

        layout.addWidget(theme_group)

        # ── 日志设置 ───────────────────────────────────────
        log_group, log_content = panel_group("日志设置")
        log_layout = log_content

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
        font_group, font_content = panel_group("终端字体")
        font_layout = font_content

        self.font_size_slider = QSlider(Qt.Horizontal)
        self.font_size_slider.setRange(8, 24)
        self.font_size_slider.setValue(12)
        font_layout.addWidget(QLabel("字体大小:"))
        font_layout.addWidget(self.font_size_slider)

        layout.addWidget(font_group)

        # ── 面板显隐（§3.8）────────────────────────────────
        vis_group, vis_content = panel_group("面板显隐")
        vis_layout = vis_content
        for key, label, default in _PANEL_TOGGLE_ITEMS:
            cb = QCheckBox(label)
            cb.setChecked(default)
            cb.toggled.connect(
                lambda checked, k=key: self._toggle_panel(k, checked))
            vis_layout.addWidget(cb)
            self._panel_checks[key] = cb

        layout.addWidget(vis_group)

        # ── 面板操作 ───────────────────────────────────────
        action_group, action_content = panel_group("面板操作")
        action_layout = action_content

        reset_btn = QPushButton("重置面板布局")
        reset_btn.clicked.connect(self._reset_layout)
        action_layout.addWidget(reset_btn)

        layout.addWidget(action_group)

        # 弹簧
        layout.addStretch()

    # ── §3.8 主题切换 ─────────────────────────────────────

    def _set_theme(self, theme: str) -> None:
        """切换明/暗主题（经 MainWindow.set_theme）"""
        window = self.window()
        if window and hasattr(window, 'set_theme'):
            window.set_theme(theme)

    # ── §3.8 面板显隐 ─────────────────────────────────────

    def _toggle_panel(self, key: str, visible: bool) -> None:
        """显示/隐藏面板（经 MainWindow.set_panel_visible）"""
        window = self.window()
        if window and hasattr(window, 'set_panel_visible'):
            window.set_panel_visible(key, visible)

    def _reset_layout(self) -> None:
        """重置 QSplitter 默认比例"""
        window = self.window()
        if window and hasattr(window, 'splitter'):
            sizes = [250, 750, 300]
            window.splitter.setSizes(sizes)
