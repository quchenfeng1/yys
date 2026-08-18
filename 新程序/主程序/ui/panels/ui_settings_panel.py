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
# 注：
#  - 「配置」与「UI 设置」已合并为「设置」面板（两个 Tab）
#  - 「设置」为元控制面板，**不可隐藏**（否则无 UI 入口恢复）→ 不列入
_PANEL_TOGGLE_ITEMS = [
    ("game_task", "游戏任务", True),
    ("task_queue", "任务队列", True),
    ("task_manager", "任务管理", True),
    ("image", "素材管理", True),
    ("accounts", "账号管理", True),
    ("emulators", "模拟器管理", True),
    ("signals", "信号管理", True),
    ("anomalies", "异常任务", True),
]


class UISettingsPanel(QWidget):
    """UI 自身设置面板（§3.8）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel_checks: dict[str, QCheckBox] = {}
        self._log_panel = None  # MainWindow 创建后经 bind_log_panel 注入
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
        self.log_level_combo.currentTextChanged.connect(self._apply_log_level)
        log_layout.addWidget(QLabel("日志级别:"))
        log_layout.addWidget(self.log_level_combo)

        self.auto_scroll_cb = QCheckBox("自动滚动")
        self.auto_scroll_cb.setChecked(True)
        self.auto_scroll_cb.toggled.connect(self._apply_auto_scroll)
        log_layout.addWidget(self.auto_scroll_cb)

        layout.addWidget(log_group)

        # ── 字体设置 ───────────────────────────────────────
        font_group, font_content = panel_group("终端字体")
        font_layout = font_content

        self.font_size_slider = QSlider(Qt.Horizontal)
        self.font_size_slider.setRange(8, 24)
        self.font_size_slider.setValue(12)
        self.font_size_slider.valueChanged.connect(self._apply_font_size)
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

    # ── §3.8 日志设置联动（LogPanel） ─────────────────────

    def bind_log_panel(self, log_panel) -> None:
        """绑定 LogPanel（MainWindow 创建后调用）：应用当前控件值并建立实时联动。"""
        self._log_panel = log_panel
        self._apply_log_level(self.log_level_combo.currentText())
        self._apply_auto_scroll(self.auto_scroll_cb.isChecked())
        self._apply_font_size(self.font_size_slider.value())

    def _resolve_log_panel(self):
        """获取 LogPanel：优先已绑定引用，其次从顶层窗口查找（容错）"""
        lp = getattr(self, '_log_panel', None)
        if lp is None:
            win = self.window()
            lp = getattr(win, 'log_panel', None) if win is not None else None
        return lp

    def _apply_log_level(self, level: str) -> None:
        lp = self._resolve_log_panel()
        if lp is not None and hasattr(lp, 'set_level_filter'):
            lp.set_level_filter(level)

    def _apply_auto_scroll(self, checked: bool) -> None:
        lp = self._resolve_log_panel()
        if lp is not None and hasattr(lp, 'set_auto_scroll'):
            lp.set_auto_scroll(checked)

    def _apply_font_size(self, size: int) -> None:
        lp = self._resolve_log_panel()
        if lp is not None and hasattr(lp, 'set_log_font_size'):
            lp.set_log_font_size(size)

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
