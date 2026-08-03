"""
UI 全局主题（QSS）

统一浅色清爽风格，与 task_queue_panel 卡片风格协调：
- 白色面板 + 浅蓝主色
- 圆角分组框 / 按钮 / 列表
- 细滚动条（不突兀，减少"滚动条太多"的视觉）
- 仅样式，不涉及任何按钮/业务逻辑
"""
from pathlib import Path

GLOBAL_QSS = """
/* ── 基础 ───────────────────────────────────────────── */
QWidget {
    font-size: 13px;
    color: #2c3e50;
}
QMainWindow, QWidget#central_widget {
    background: #f4f6fb;
}

/* ── 标签 ───────────────────────────────────────────── */
QLabel {
    background: transparent;
    color: #2c3e50;
}

/* ── 分组框 ─────────────────────────────────────────── */
QGroupBox {
    background: #ffffff;
    border: 1px solid #e0e4ea;
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 8px;
    font-weight: bold;
    color: #34495e;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    background: transparent;
    color: #2c7be5;
}

/* ── 按钮 ───────────────────────────────────────────── */
QPushButton {
    background: #eef4fd;
    border: 1px solid #bcd4f0;
    border-radius: 8px;
    padding: 5px 14px;
    color: #1e6fd9;
    font-weight: bold;
}
QPushButton:hover  { background: #dcebfc; border-color: #7fb2ea; }
QPushButton:pressed{ background: #cfe3fb; }
QPushButton:disabled { background: #f0f0f0; color: #aaaaaa; border-color: #dddddd; }

/* ── 输入控件（文本/数值） ─────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {
    background: #ffffff;
    border: 1px solid #d5dae2;
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: #bcd9f7;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus { border-color: #4a90d9; }

/* ── 下拉框 QComboBox ──────────────────────────────── */
QComboBox {
    background: #ffffff;
    border: 1px solid #d5dae2;
    border-radius: 8px;
    padding: 2px 8px;
    min-height: 24px;
    color: #2c3e50;
}
QComboBox:hover { border-color: #7fb2ea; background: #f7fbff; }
QComboBox:focus, QComboBox:on { border-color: #4a90d9; background: #f0f7ff; }
QComboBox::drop-down {
    border: none;
    width: 22px;
    border-left: 1px solid #e4e9f0;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
}
QComboBox::drop-down:hover { background: #eef4fd; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d5dae2;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 2px 8px;
    border-radius: 6px;
    color: #2c3e50;
}
QComboBox QAbstractItemView::item:hover { background: #eef4fd; }
QComboBox QAbstractItemView::item:selected {
    background: #d6e8fb; color: #1e5fa8;
}

/* ── 数值输入框增减按钮（清晰可见） ──────────────────── */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QDateEdit::up-button, QTimeEdit::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button,
QDateEdit::down-button, QTimeEdit::down-button {
    background: #eef4fd;
    border: none;
    border-left: 1px solid #d5dae2;
    width: 18px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QDateEdit::up-button:hover, QTimeEdit::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover,
QDateEdit::down-button:hover, QTimeEdit::down-button:hover {
    background: #dcebfc;
}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QDateEdit::up-button:pressed, QTimeEdit::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed,
QDateEdit::down-button:pressed, QTimeEdit::down-button:pressed {
    background: #cfe3fb;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow,
QDateEdit::up-arrow, QTimeEdit::up-arrow {
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #4a90d9;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow,
QDateEdit::down-arrow, QTimeEdit::down-arrow {
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #4a90d9;
}
QComboBox::down-arrow {
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #4a90d9;
    margin-right: 2px;
}
QComboBox::down-arrow:hover {
    border-top-color: #1e5fa8;
}

/* ── 复选/单选 ──────────────────────────────────────── */
QCheckBox, QRadioButton {
    spacing: 8px;
    background: transparent;
    color: #2c3e50;
}
QCheckBox::indicator {
    width: 18px; height: 18px;
    border: 2px solid #b8c2d0;
    border-radius: 5px;
    background: #ffffff;
}
QCheckBox::indicator:hover { border-color: #4a90d9; }
QCheckBox::indicator:pressed { background: #e8f1fc; }
QCheckBox::indicator:checked {
    background: #4a90d9;
    border-color: #4a90d9;
    image: url("__CHECK_IMG__");
}
QCheckBox::indicator:checked:hover { background: #2f7fd4; }
QCheckBox::indicator:disabled {
    border-color: #d5dae2;
    background: #f0f0f0;
}
QRadioButton::indicator {
    width: 18px; height: 18px;
    border: 2px solid #b8c2d0;
    border-radius: 9px;
    background: #ffffff;
}
QRadioButton::indicator:hover { border-color: #4a90d9; }
QRadioButton::indicator:checked {
    background: #4a90d9;
    border-color: #4a90d9;
}

/* ── 列表 / 树 ──────────────────────────────────────── */
QListWidget, QTreeWidget, QTreeView {
    background: #ffffff;
    border: 1px solid #e0e4ea;
    border-radius: 8px;
    outline: none;
}
QListWidget::item, QTreeWidget::item {
    padding: 4px 6px;
    border-radius: 6px;
    margin: 1px 2px;
    color: #2c3e50;
}
QListWidget::item:hover, QTreeWidget::item:hover { background: #eef4fd; }
QListWidget::item:selected, QTreeWidget::item:selected {
    background: #d6e8fb; color: #1e5fa8;
}

/* ── 滚动区域 ───────────────────────────────────────── */
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* ── 细滚动条 ───────────────────────────────────────── */
QScrollBar:vertical {
    background: transparent; width: 8px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: #c5ccd8; border-radius: 4px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #a9b4c6; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 8px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #c5ccd8; border-radius: 4px; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #a9b4c6; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ── Tab 页 ─────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #e0e4ea;
    border-radius: 8px;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: #eef1f6;
    border: 1px solid #e0e4ea;
    border-bottom: none;
    padding: 7px 18px;
    margin-right: 3px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: #5a6a7a;
}
QTabBar::tab:selected {
    background: #ffffff; color: #1e6fd9; font-weight: bold;
}
QTabBar::tab:hover:!selected { background: #e3eaf4; }

/* ── 分割条 ─────────────────────────────────────────── */
QSplitter::handle { background: #e4e8ef; }
QSplitter::handle:hover { background: #bcd4f0; }
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }

/* ── 状态栏 ─────────────────────────────────────────── */
QStatusBar {
    background: #eef1f6;
    border-top: 1px solid #dde2ea;
    color: #34495e;
}

/* ── 表格 ───────────────────────────────────────────── */
QTableWidget, QTableView {
    background: #ffffff;
    border: 1px solid #e0e4ea;
    border-radius: 8px;
    gridline-color: #eef1f6;
    selection-background-color: #d6e8fb;
    selection-color: #1e5fa8;
}
QHeaderView::section {
    background: #f2f5f9;
    border: none;
    border-bottom: 1px solid #dde2ea;
    padding: 6px;
    font-weight: bold;
    color: #34495e;
}

/* ── 进度条 ─────────────────────────────────────────── */
QProgressBar {
    border: 1px solid #d5dae2;
    border-radius: 6px;
    background: #eef1f6;
    text-align: center;
    color: #2c3e50;
}
QProgressBar::chunk {
    background: #4a90d9;
    border-radius: 6px;
}

/* ── 工具提示 ───────────────────────────────────────── */
QToolTip {
    background: #ffffff;
    color: #2c3e50;
    border: 1px solid #d5dae2;
    border-radius: 6px;
    padding: 4px 8px;
}
"""

# 注入对勾图标绝对路径（QCheckBox::indicator:checked 用）
_CHECK_IMG = (Path(__file__).resolve().parent / "check.png").as_posix()
GLOBAL_QSS = GLOBAL_QSS.replace("__CHECK_IMG__", _CHECK_IMG)


def apply_theme(app) -> None:
    """应用全局主题：优先 qt-material（Material 浅蓝），失败回退内置 GLOBAL_QSS。

    qt-material 的 `icon:/primary/xxx.svg` 前缀不会自动注册为 Qt 资源，
    这里把 `icon:/` 替换为 qt_material 包内 svg 的绝对路径，保证下拉箭头/复选框等图标正常显示。
    """
    try:
        from qt_material import apply_stylesheet as _apply_material
        _apply_material(app, theme="light_blue.xml")
        # 修复 icon:/ 前缀 → svg 绝对路径
        import qt_material as _qtm
        _src = Path(_qtm.__file__).resolve().parent / "resources" / "source"
        if _src.exists():
            _qss = app.styleSheet()
            app.setStyleSheet(_qss.replace("icon:/", f"{_src.as_posix()}/"))
        return
    except Exception:
        pass
    # 兜底：内置浅色主题
    try:
        app.setStyleSheet(GLOBAL_QSS)
    except Exception:
        pass


def icon(name: str, color: str = "#4a90d9"):
    """qtawesome 图标（FontAwesome）。失败返回 None，调用方自行判断。"""
    try:
        import qtawesome as qta
        return qta.icon(name, color=color)
    except Exception:
        return None
