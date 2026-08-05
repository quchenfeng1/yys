"""
UI 全局主题（QSS）

统一浅色清爽风格，与 task_queue_panel 卡片风格协调：
- 白色面板 + 浅蓝主色
- 圆角分组框 / 按钮 / 列表
- 细滚动条（不突兀，减少"滚动条太多"的视觉）
- 仅样式，不涉及任何按钮/业务逻辑
"""
from pathlib import Path

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QAbstractSpinBox, QComboBox, QGroupBox, QLabel, QVBoxLayout

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
/* 说明：GroupBox 不再使用浮在边框上的标题（subcontrol-position: top left），
   标题一律作为内部普通 QLabel 嵌入（与素材管理"图片位置/预览"一致）。 */
QGroupBox {
    background: #ffffff;
    border: 1px solid #e0e4ea;
    margin-top: 0px;
    padding-top: 4px;
    padding-left: 8px;
    padding-right: 8px;
    padding-bottom: 8px;
    color: #34495e;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    background: transparent;
    color: #2c3e50;
}

/* ── 按钮 ───────────────────────────────────────────── */
QPushButton {
    background: #eef4fd;
    border: 1px solid #bcd4f0;
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
    padding: 4px 8px;
    selection-background-color: #bcd9f7;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTimeEdit:focus { border-color: #4a90d9; }

/* ── 下拉框 QComboBox ──────────────────────────────── */
QComboBox {
    background: #ffffff;
    border: 1px solid #d5dae2;
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
}
QComboBox::drop-down:hover { background: #eef4fd; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d5dae2;
    padding: 4px;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 2px 8px;
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
    width: 10px; height: 10px;
    image: url("__ARROW_UP__");
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow,
QDateEdit::down-arrow, QTimeEdit::down-arrow {
    width: 10px; height: 10px;
    image: url("__ARROW_DOWN__");
}
QComboBox::down-arrow {
    width: 10px; height: 10px;
    image: url("__ARROW_DOWN__");
    margin-right: 2px;
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
    outline: none;
}
QListWidget::item, QTreeWidget::item {
    padding: 4px 6px;
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
    background: #c5ccd8; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #a9b4c6; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 8px; margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #c5ccd8; min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #a9b4c6; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ── Tab 页 ─────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #e0e4ea;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: #eef1f6;
    border: 1px solid #e0e4ea;
    border-bottom: none;
    padding: 7px 18px;
    margin-right: 3px;
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
    background: #eef1f6;
    text-align: center;
    color: #2c3e50;
}
QProgressBar::chunk {
    background: #4a90d9;
}

/* ── 工具提示 ───────────────────────────────────────── */
QToolTip {
    background: #ffffff;
    color: #2c3e50;
    border: 1px solid #d5dae2;
    padding: 4px 8px;
}
"""

# 注入对勾图标绝对路径（QCheckBox::indicator:checked 用）
_CHECK_IMG = (Path(__file__).resolve().parent / "check.png").as_posix()
GLOBAL_QSS = GLOBAL_QSS.replace("__CHECK_IMG__", _CHECK_IMG)
# 注入箭头图标绝对路径（QSpinBox/QComboBox 增减/下拉箭头用）
_ARROW_UP_IMG = (Path(__file__).resolve().parent / "arrow_up.png").as_posix()
_ARROW_DOWN_IMG = (Path(__file__).resolve().parent / "arrow_down.png").as_posix()
GLOBAL_QSS = GLOBAL_QSS.replace("__ARROW_UP__", _ARROW_UP_IMG)
GLOBAL_QSS = GLOBAL_QSS.replace("__ARROW_DOWN__", _ARROW_DOWN_IMG)

# ── 深色主题（明/暗切换，§3.8 主题切换）──────────────────
# 基于 GLOBAL_QSS 的深色变体：背景/前景互换，保持控件结构一致。
DARK_QSS = GLOBAL_QSS
DARK_QSS = DARK_QSS.replace("#f4f6fb", "#1e1e1e")   # 主背景
DARK_QSS = DARK_QSS.replace("#ffffff", "#2d2d30")   # 面板/输入背景
DARK_QSS = DARK_QSS.replace("#eef4fd", "#3a3a3e")   # 按钮/项背景
DARK_QSS = DARK_QSS.replace("#eef1f6", "#333338")   # 状态栏/表头
DARK_QSS = DARK_QSS.replace("#f7f8fa", "#2a2a2d")   # 队列面板背景
DARK_QSS = DARK_QSS.replace("#f2f5f9", "#38383d")   # 表头
DARK_QSS = DARK_QSS.replace("#fbfbfd", "#333338")   # 卡片背景
DARK_QSS = DARK_QSS.replace("#eef7ee", "#2f3a2f")   # 正在执行卡片
DARK_QSS = DARK_QSS.replace("#e0e4ea", "#4a4a4f")   # 边框
DARK_QSS = DARK_QSS.replace("#d5dae2", "#4a4a4f")   # 输入框边框
DARK_QSS = DARK_QSS.replace("#c8ccd4", "#4a4a4f")   # 队列边框
DARK_QSS = DARK_QSS.replace("#d8dbe0", "#4a4a4f")   # 卡片边框
DARK_QSS = DARK_QSS.replace("#dde2ea", "#4a4a4f")   # 状态栏边框
DARK_QSS = DARK_QSS.replace("#c5ccd8", "#5a5a60")   # 滚动条滑块
DARK_QSS = DARK_QSS.replace("#b8c2d0", "#6a6a70")   # 复选框边框
DARK_QSS = DARK_QSS.replace("#bcd4f0", "#4a6a8a")   # 按钮边框
DARK_QSS = DARK_QSS.replace("#2c3e50", "#d0d0d0")   # 主文字
DARK_QSS = DARK_QSS.replace("#34495e", "#c0c0c0")   # 分组框文字
DARK_QSS = DARK_QSS.replace("#5a6a7a", "#a0a0a8")   # tab 文字
DARK_QSS = DARK_QSS.replace("#333", "#d0d0d0")       # 队列文字
DARK_QSS = DARK_QSS.replace("#888", "#9a9a9a")       # 次要文字
DARK_QSS = DARK_QSS.replace("#aaa", "#8a8a8a")       # 提示文字
DARK_QSS = DARK_QSS.replace("#f0f0f0", "#2a2a2d")   # 禁用背景
DARK_QSS = DARK_QSS.replace("#f0f5ff", "#2f3a4a")   # 卡片 hover
DARK_QSS = DARK_QSS.replace("#e8f1fc", "#2f3a4a")   # 输入区选中
DARK_QSS = DARK_QSS.replace("#f7fbff", "#2f3a4a")   # 下拉 hover
DARK_QSS = DARK_QSS.replace("#f0f7ff", "#2f3a4a")   # 下拉 focus
DARK_QSS = DARK_QSS.replace("#dcebfc", "#3a4a5e")   # 按钮 hover
DARK_QSS = DARK_QSS.replace("#cfe3fb", "#3a4a5e")   # 按钮 pressed
DARK_QSS = DARK_QSS.replace("#d4e6fb", "#3a4a5e")   # 队列按钮 hover
DARK_QSS = DARK_QSS.replace("#d6e8fb", "#2f3a4a")   # 选中背景
DARK_QSS = DARK_QSS.replace("#eef4fd", "#3a3a3e")   # 其他浅背景
DARK_QSS = DARK_QSS.replace("#bcd9f7", "#2f3a4a")   # 输入选中背景


def apply_theme(app, theme: str = "light") -> None:
    """应用全局主题（§3.8 明/暗切换）。

    theme: "light" 优先 qt-material 浅蓝，失败回退 GLOBAL_QSS；
           "dark"  优先 qt-material 深蓝，失败回退 DARK_QSS。

    qt-material 的 `icon:/primary/xxx.svg` 前缀不会自动注册为 Qt 资源，
    这里把 `icon:/` 替换为 qt_material 包内 svg 的绝对路径，保证下拉箭头/复选框等图标正常显示。
    """
    if theme == "dark":
        try:
            from qt_material import apply_stylesheet as _apply_material
            _apply_material(app, theme="dark_blue.xml")
            import qt_material as _qtm
            _src = Path(_qtm.__file__).resolve().parent / "resources" / "source"
            if _src.exists():
                _qss = app.styleSheet()
                app.setStyleSheet(_qss.replace("icon:/", f"{_src.as_posix()}/"))
        except Exception:
            pass
        # 兜底：内置深色主题
        try:
            app.setStyleSheet(DARK_QSS)
        except Exception:
            pass
    else:
        try:
            from qt_material import apply_stylesheet as _apply_material
            _apply_material(app, theme="light_blue.xml")
            # 修复 icon:/ 前缀 → svg 绝对路径
            import qt_material as _qtm
            _src = Path(_qtm.__file__).resolve().parent / "resources" / "source"
            if _src.exists():
                _qss = app.styleSheet()
                app.setStyleSheet(_qss.replace("icon:/", f"{_src.as_posix()}/"))
        except Exception:
            pass
        # 兜底：内置浅色主题
        try:
            app.setStyleSheet(GLOBAL_QSS)
        except Exception:
            pass
    # 输入框滚轮防护（防止滚轮误改数值/下拉值）
    disable_wheel_on_inputs(app)


def panel_group(title: str):
    """创建"标题嵌入"的分组框（与素材管理'图片位置/预览'一致）。

    GroupBox 不再使用浮在边框上的标题，标题作为内部普通 QLabel 嵌入内容顶部。
    返回 (group_box, content_layout)，内容布局为 QVBoxLayout（可再 addLayout 表单）。
    """
    box = QGroupBox()
    outer = QVBoxLayout(box)
    outer.setContentsMargins(10, 6, 10, 10)
    outer.setSpacing(4)
    outer.addWidget(QLabel(title))
    return box, outer


def icon(name: str, color: str = "#4a90d9"):
    """qtawesome 图标（FontAwesome）。失败返回 None，调用方自行判断。"""
    try:
        import qtawesome as qta
        return qta.icon(name, color=color)
    except Exception:
        return None


# ── 输入框滚轮防护（防止鼠标滚轮误改数值/下拉值） ────────────

class _WheelGuard(QObject):
    """拦截 QAbstractSpinBox（数值/时间）与 QComboBox 的滚轮事件，防止误改。

    滚轮在滚动区域/列表上仍正常（只拦截这两类输入控件）。
    """

    def __init__(self, app):
        super().__init__(app)
        self._event_type = QEvent.Wheel
        self._spinbox = QAbstractSpinBox
        self._combo = QComboBox

    def eventFilter(self, obj, event):
        if (event.type() == self._event_type
                and isinstance(obj, (self._spinbox, self._combo))):
            return True  # 吞掉滚轮事件，不改值
        return False


_wheel_guard = None


def disable_wheel_on_inputs(app) -> None:
    """关闭数值/时间/下拉输入框的鼠标滚轮修改（防止误改），全局生效。"""
    global _wheel_guard
    try:
        if _wheel_guard is None:
            _wheel_guard = _WheelGuard(app)
        app.installEventFilter(_wheel_guard)
    except Exception:
        pass
