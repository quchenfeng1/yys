"""
UI 设置面板（11-用户界面模块）

用户通过此面板控制 UI 自身的行为：主题/字体/日志级别/面板显隐/刷新频率等。
实现"用 UI 控制 UI"的元控能力。
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QSpinBox, QCheckBox, QPushButton, QGroupBox, QFormLayout,
    QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


THEME_PRESETS = {
    "light": "浅色主题（默认）",
    "dark": "深色主题",
    "auto": "跟随系统",
}

FONT_SIZES = ["11", "12", "13", "14", "15", "16"]

PANEL_TOGGLES = [
    ("show_status_bar", "底部状态栏", True),
    ("show_control_bar", "全局控制栏", True),
    ("show_log_panel", "右侧日志面板", True),
    ("show_menu_tree", "左侧菜单树", True),
    ("auto_scroll_log", "日志自动滚动", True),
    ("confirm_on_stop", "停止时确认", True),
    ("show_tooltips", "显示提示框", True),
]


class UISettingsPanel(QWidget):
    """UI 自身行为设置面板 — 通过 11 模块控制 UI。"""

    settings_changed = pyqtSignal(str, object)  # key, value

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._build()
        self._load()

    def _build(self):
        ly = QVBoxLayout(self)
        ly.setContentsMargins(16, 12, 16, 12)
        ly.setSpacing(12)

        title = QLabel("🖥  UI 设置")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title.setStyleSheet("color:#1A1A2E;")
        ly.addWidget(title)

        desc = QLabel("在此控制界面外观和行为。所有设置即时生效。")
        desc.setStyleSheet("color:#80868B;font-size:12px;margin-bottom:8px;")
        ly.addWidget(desc)

        # ── 外观 ──
        g1 = QGroupBox("外观")
        f1 = QFormLayout(g1)
        f1.setSpacing(8)

        self._theme_combo = QComboBox()
        for k, v in THEME_PRESETS.items():
            self._theme_combo.addItem(v, k)
        self._theme_combo.currentIndexChanged.connect(
            lambda: self._emit("theme", self._theme_combo.currentData()))
        f1.addRow("主题:", self._theme_combo)

        self._font_size = QComboBox()
        self._font_size.addItems(FONT_SIZES)
        self._font_size.currentTextChanged.connect(
            lambda v: self._emit("font_size", int(v)))
        f1.addRow("字号:", self._font_size)

        ly.addWidget(g1)

        # ── 面板显隐 ──
        g2 = QGroupBox("面板显隐")
        f2 = QFormLayout(g2)
        f2.setSpacing(4)
        self._panel_cbs = {}
        for key, label, default in PANEL_TOGGLES:
            cb = QCheckBox(label)
            cb.setChecked(default)
            cb.toggled.connect(lambda v, k=key: self._emit(k, v))
            self._panel_cbs[key] = cb
            f2.addRow("", cb)
        ly.addWidget(g2)

        # ── 刷新与性能 ──
        g3 = QGroupBox("刷新与性能")
        f3 = QFormLayout(g3)
        f3.setSpacing(8)

        self._refresh_interval = QSpinBox()
        self._refresh_interval.setRange(500, 10000)
        self._refresh_interval.setSingleStep(500)
        self._refresh_interval.setSuffix(" ms")
        self._refresh_interval.valueChanged.connect(
            lambda v: self._emit("refresh_interval", v))
        f3.addRow("刷新间隔:", self._refresh_interval)

        self._max_log_lines = QSpinBox()
        self._max_log_lines.setRange(100, 50000)
        self._max_log_lines.setSingleStep(500)
        self._max_log_lines.setSuffix(" 行")
        self._max_log_lines.valueChanged.connect(
            lambda v: self._emit("max_log_lines", v))
        f3.addRow("日志上限:", self._max_log_lines)

        self._enable_animations = QCheckBox("启用动画效果")
        self._enable_animations.setChecked(True)
        self._enable_animations.toggled.connect(
            lambda v: self._emit("enable_animations", v))
        f3.addRow("", self._enable_animations)

        ly.addWidget(g3)

        ly.addStretch()

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        reset_btn = QPushButton("恢复默认")
        reset_btn.setStyleSheet("""
            QPushButton{background:#F1F3F4;color:#5F6368;border:1px solid #DADCE0;
            border-radius:6px;padding:8px 16px;}
            QPushButton:hover{background:#E8ECF0;}
        """)
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)
        ly.addLayout(btn_row)

    def _load(self):
        theme = self._config.get("ui.theme", "light")
        idx = self._theme_combo.findData(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

        fs = str(self._config.get("ui.font_size", 12))
        idx = self._font_size.findText(fs)
        if idx >= 0:
            self._font_size.setCurrentIndex(idx)

        self._refresh_interval.setValue(
            self._config.get("ui.refresh_interval", 2000))
        self._max_log_lines.setValue(
            self._config.get("ui.max_log_lines", 10000))
        self._enable_animations.setChecked(
            self._config.get("ui.enable_animations", True))

        for key, _, default in PANEL_TOGGLES:
            val = self._config.get(f"ui.{key}", default)
            if key in self._panel_cbs:
                self._panel_cbs[key].setChecked(val)

    def _emit(self, key: str, value):
        self._config.set(f"ui.{key}", value)
        self.settings_changed.emit(key, value)

    def _reset_defaults(self):
        reply = QMessageBox.question(
            self, "恢复默认", "将所有 UI 设置恢复为默认值？",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            defaults = {
                "ui.theme": "light", "ui.font_size": 12,
                "ui.refresh_interval": 2000, "ui.max_log_lines": 10000,
                "ui.enable_animations": True,
            }
            for key, _, default in PANEL_TOGGLES:
                defaults[f"ui.{key}"] = default
            for k, v in defaults.items():
                self._config.set(k, v)
            self._load()
            QMessageBox.information(self, "已重置", "UI 设置已恢复默认值，部分变更需重启生效。")
