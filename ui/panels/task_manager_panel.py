"""
任务管理面板（v2.6 — QScrollArea 行控件方案，彻底解决 setItemWidget 定位问题）

点击「任务管理」子菜单：
  - 日常/常驻/活动/特殊 → 任务列表(上) + 点击后模块标签(下)
  - 通用模块 → 所有通用模块列表（可跳转 Python 文件）
  - 特化模块 → 所有特化模块按分类分组（可跳转 Python 文件）
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QFrame, QScrollArea,
    QMessageBox, QDialog, QFormLayout, QLineEdit, QComboBox,
)

from core.task_manager import TaskManager, TaskModule

# ==================== 样式 ====================

ROW_NORMAL = """
    QFrame#task_row { background: #FFFFFF; border: none;
    border-bottom: 1px solid #F0F0F0; border-radius: 0; }
    QFrame#task_row:hover { background: #F5F8FF; }
"""
ROW_SELECTED = """
    QFrame#task_row { background: #E3F0FF; border: none;
    border-bottom: 1px solid #D0E0F0; border-radius: 0; }
"""
ROW_HEADER = """
    QFrame#task_row { background: #F8F9FA; border: none;
    border-bottom: 1px solid #E8ECF0; border-radius: 0; }
"""
LIST_BOX = """
    QFrame#list_box { background: #FFFFFF; border: 1px solid #E8ECF0; border-radius: 8px; }
"""
BTN_OPEN = """
    QPushButton { background: #34A853; color: white; font-size: 11px; font-weight: bold;
    border: none; border-radius: 4px; padding: 4px 10px; }
    QPushButton:hover { background: #2E7D32; }
"""
BTN_DEL = """
    QPushButton { background: transparent; color: #EA4335; font-size: 11px;
    border: 1px solid #EA4335; border-radius: 4px; padding: 4px 10px; }
    QPushButton:hover { background: #FDECEA; }
"""
BTN_NEW = """
    QPushButton { background: #1A73E8; color: white; font-weight: bold;
    border: none; border-radius: 8px; padding: 8px 20px; }
    QPushButton:hover { background: #1557B0; }
"""
MODULE_TAG = """
    QLabel { background: #F0F4FF; color: #1A73E8; border-radius: 4px;
    padding: 3px 8px; font-size: 11px; margin: 2px; }
"""


# ==================== 可点击行控件 ====================

class ClickableRow(QFrame):
    """可点击的列表行，鼠标悬停高亮。"""
    clicked = pyqtSignal(object)  # 携带数据 (TaskModule)

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self._data = data
        self.setObjectName("task_row")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(ROW_NORMAL)

    def mousePressEvent(self, ev):
        self.clicked.emit(self._data)

    def enterEvent(self, ev):
        if self.styleSheet() == ROW_NORMAL:
            self.setStyleSheet(ROW_SELECTED)

    def leaveEvent(self, ev):
        self.setStyleSheet(ROW_NORMAL)


class HeaderRow(QFrame):
    """分组标题行（不可点击）。"""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setObjectName("task_row")
        self.setStyleSheet(ROW_HEADER)
        ly = QHBoxLayout(self); ly.setContentsMargins(10, 6, 10, 6)
        lb = QLabel(text)
        lb.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        lb.setStyleSheet("color:#1A73E8;")
        ly.addWidget(lb)
        ly.addStretch()


# ==================== 对话框 ====================

class NewTaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建任务"); self.setMinimumWidth(380)
        ly = QFormLayout(self)
        self.cat = QComboBox(); self.cat.addItems(["daily","permanent","event","special"]); ly.addRow("目录分类:",self.cat)
        self.ttype = QComboBox(); self.ttype.addItems(["事件任务","战斗任务"]); ly.addRow("任务类型:",self.ttype)
        self.nm = QLineEdit(); self.nm.setPlaceholderText("snake_case"); ly.addRow("文件名:",self.nm)
        self.dn = QLineEdit(); self.dn.setPlaceholderText("中文显示名"); ly.addRow("显示名:",self.dn)
        br = QHBoxLayout(); ok=QPushButton("创建");ok.clicked.connect(self.accept)
        cancel=QPushButton("取消");cancel.clicked.connect(self.reject)
        br.addStretch();br.addWidget(ok);br.addWidget(cancel);ly.addRow(br)
    def get(self):
        ttype = "battle" if self.ttype.currentText() == "战斗任务" else "event_task"
        return self.cat.currentText(), self.nm.text(), self.dn.text(), ttype


# ==================== 主面板 ====================

class TaskManagerPanel(QWidget):
    def __init__(self, task_mgr: TaskManager, parent=None):
        super().__init__(parent)
        self._mgr = task_mgr; self._section = "daily"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._selected_data = None  # 当前选中的 TaskModule
        self._build(); self.show_section("daily")

    def _build(self):
        ly = QVBoxLayout(self); ly.setContentsMargins(12, 8, 12, 8); ly.setSpacing(6)

        self._title = QLabel(); self._title.setFont(QFont("Microsoft YaHei",13,QFont.Bold))
        self._title.setStyleSheet("color:#1A1A2E;"); ly.addWidget(self._title)

        self._task_label = QLabel("游戏任务")
        self._task_label.setFont(QFont("Microsoft YaHei",10,QFont.Bold))
        self._task_label.setStyleSheet("color:#5F6368;"); ly.addWidget(self._task_label)

        # ★ 列表外框（模拟 QListWidget 的外观）
        self._list_box = QFrame()
        self._list_box.setObjectName("list_box")
        self._list_box.setStyleSheet(LIST_BOX)
        self._list_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._list_box.setMinimumHeight(120)
        box_ly = QVBoxLayout(self._list_box)
        box_ly.setContentsMargins(0, 0, 0, 0); box_ly.setSpacing(0)

        # 滚动区域
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self._rows = QWidget()
        self._rows_layout = QVBoxLayout(self._rows)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._rows_layout.addStretch()
        self._scroll.setWidget(self._rows)
        box_ly.addWidget(self._scroll)
        ly.addWidget(self._list_box, stretch=2)

        # 模块详情区（点击任务后显示）
        self._mod_area = QWidget()
        mly = QVBoxLayout(self._mod_area); mly.setContentsMargins(0,6,0,0); mly.setSpacing(4)
        self._mod_label = QLabel("📦 使用的模块（仅供查看）")
        self._mod_label.setFont(QFont("Microsoft YaHei",9,QFont.Bold)); self._mod_label.setStyleSheet("color:#80868B;")
        self._mod_label.hide(); mly.addWidget(self._mod_label)
        self._tags = QWidget(); self._tags.setLayout(QHBoxLayout())
        self._tags.layout().setContentsMargins(0,0,0,0); self._tags.layout().addStretch()
        self._tags.hide(); mly.addWidget(self._tags); mly.addStretch()
        self._mod_area.hide(); ly.addWidget(self._mod_area)

        # 底部按钮
        br = QHBoxLayout()
        nb = QPushButton("＋ 新建任务"); nb.setStyleSheet(BTN_NEW); nb.clicked.connect(self._on_new); br.addWidget(nb)
        br.addStretch()
        rb = QPushButton("🔄 刷新");
        rb.clicked.connect(lambda: (self._mgr.scan_all(), self.show_section(self._section)))
        br.addWidget(rb)
        ly.addLayout(br)

    # ==================== 切换分类 ====================

    def show_section(self, section: str):
        self._mgr.scan_all(); self._section = section
        self._mod_area.hide(); self._mod_label.hide(); self._tags.hide()
        self._selected_data = None
        labels = {"daily":"📅 日常任务","permanent":"⚔ 常驻任务","event":"🎪 活动任务",
                  "special":"⭐ 特殊任务","common":"🔧 通用模块","specialized":"🔨 特化模块"}
        self._title.setText(labels.get(section, "任务管理"))
        self._task_label.setVisible(section in ("daily","permanent","event","special"))
        self._clear_rows()
        if section == "common":
            self._show_mods(self._mgr.get_generic_modules(), True, False)
        elif section == "specialized":
            self._show_spec()
        else:
            self._show_tasks(section)

    def _clear_rows(self):
        """清空行容器中除 stretch 外的所有 widget。"""
        lay = self._rows_layout
        while lay.count() > 1:  # 保留最后的 stretch
            w = lay.takeAt(0).widget()
            if w: w.deleteLater()

    def _add_empty(self, text):
        lb = QLabel(text); lb.setAlignment(Qt.AlignCenter)
        lb.setStyleSheet("color:#BDC1C6;font-size:13px;padding:24px;")
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, lb)

    # ==================== 填充行 ====================

    def _show_tasks(self, cat):
        tasks = self._mgr.get_tasks_by_category(cat)
        if not tasks: self._add_empty("（暂无任务）"); return
        for t in tasks: self._add_row(t, True, True)

    def _show_mods(self, mods, can_open, can_del):
        if not mods: self._add_empty("（暂无模块）"); return
        for m in mods: self._add_row(m, can_open, can_del)

    def _show_spec(self):
        cats = {"daily":[],"permanent":[],"event":[],"special":[]}
        for t in self._mgr.get_all_tasks():
            if t.category in cats: cats[t.category].append(t)
        lbs = {"daily":"📅 日常","permanent":"⚔ 常驻","event":"🎪 活动","special":"⭐ 特殊"}
        for cat, tasks in cats.items():
            if not tasks: continue
            hdr = HeaderRow(f"{lbs.get(cat,cat)} ({len(tasks)})")
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, hdr)
            for t in tasks: self._add_row(t, True, False)

    def _add_row(self, mod, can_open, can_del):
        """创建一行：ClickableRow 内放 HBoxLayout(name+desc | buttons)。"""
        row = ClickableRow(mod)
        row.clicked.connect(self._on_row_clicked)
        r = QHBoxLayout(row); r.setContentsMargins(10, 8, 10, 8); r.setSpacing(10)

        # 左侧：图标+名称+描述
        left = QWidget()
        lv = QVBoxLayout(left); lv.setContentsMargins(0,0,0,0); lv.setSpacing(3)
        ic = self._mgr.CATEGORY_ICONS.get(mod.category, "📄")
        nm = QLabel(f"{ic}  {mod.display_name}")
        nm.setFont(QFont("Microsoft YaHei", 10, QFont.Bold)); nm.setStyleSheet("color:#1A1A2E;background:transparent;")
        lv.addWidget(nm)
        if mod.description:
            d = QLabel(mod.description[:55])
            d.setStyleSheet("color:#80868B;font-size:11px;background:transparent;"); d.setWordWrap(True)
            lv.addWidget(d)
        r.addWidget(left, stretch=1)

        if can_open:
            ob = QPushButton("📂 打开脚本"); ob.setStyleSheet(BTN_OPEN); ob.setFixedHeight(28)
            ob.clicked.connect(lambda c, m=mod: self._mgr.open_file(m)); r.addWidget(ob)
        if can_del:
            db = QPushButton("✕"); db.setStyleSheet(BTN_DEL); db.setFixedHeight(28)
            db.clicked.connect(lambda c, m=mod: self._on_del(m)); r.addWidget(db)

        row.setMinimumHeight(52)
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    # ==================== 交互 ====================

    def _on_row_clicked(self, data):
        """点击任务行 → 高亮行 + 显示模块标签。"""
        try:
            self._selected_data = data
            for i in range(self._rows_layout.count()):
                w = self._rows_layout.itemAt(i).widget()
                if isinstance(w, ClickableRow):
                    w.setStyleSheet(ROW_SELECTED if w._data is data else ROW_NORMAL)
            if not data or getattr(data, 'is_generic', False):
                self._mod_area.hide(); return
            lt = self._tags.layout()
            while lt.count() > 1:
                w = lt.takeAt(0).widget()
                if w: w.deleteLater()
            for g in self._mgr.get_generic_modules():
                t = QLabel(f"🔧 {g.display_name}"); t.setStyleSheet(MODULE_TAG)
                lt.insertWidget(lt.count() - 1, t)
            self._mod_label.show(); self._tags.show(); self._mod_area.show()
        except Exception:
            pass  # UI 辅助功能，出错不阻塞

    def _on_new(self):
        try:
            d = NewTaskDialog(self)
            if d.exec_() == QDialog.Accepted:
                c, n, dn, tt = d.get()
                if not n: QMessageBox.warning(self, "错误", "文件名不能为空"); return
                r = self._mgr.new_task(c, n, dn, task_type=tt)
                if r:
                    self._mgr.open_file(TaskModule(name=n, category=c, filepath=str(r)))
                    self._mgr.scan_all(); self.show_section(self._section)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"新建任务失败:\n{e}")

    def _on_del(self, mod):
        try:
            if QMessageBox.question(self, "确认删除", f"删除「{mod.display_name}」？",
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                self._mgr.delete_task(mod); self._mgr.scan_all(); self.show_section(self._section)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除失败:\n{e}")
