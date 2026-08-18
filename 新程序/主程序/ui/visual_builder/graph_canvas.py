"""
17-可视化构建模块：NodeGraphQt 节点画布封装（P2，4.15/4.19）。

- 为每个节点类型动态生成 BaseNode 子类（含输入/输出端口 + 参数 widget）；
- load_task()：任务 JSON（nodes/connections）→ 画布；
- export_task()：画布 → 任务 JSON；
- 示教产物（场景/点击点/OCR区域/素材元素）动态填充参数下拉（combo_scene 等）；
- 惰性加载：仅构建面板创建时 import NodeGraphQt，不影响主流程。

节点内嵌 widget 映射（参数面板全部下拉/输入，不写代码）：
  combo            → 固定选项下拉
  combo_scene      → 示教场景下拉（动态）
  combo_point      → 示教点击点下拉（动态）
  combo_element    → 素材元素下拉（动态）
  combo_ocr_region → 已标注 OCR 区域下拉（动态）
  spinbox / text / checkbox
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (QBrush, QFontMetrics, QImage, QPainter, QPen,
                         QPixmap)
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                             QInputDialog, QLabel, QListWidget, QListWidgetItem,
                             QMessageBox, QPushButton, QSplitter, QStyle,
                             QStyledItemDelegate, QTabWidget, QVBoxLayout,
                             QWidget)

from NodeGraphQt import BaseNode, NodeGraph
from NodeGraphQt.widgets import node_widgets as _nw2

from ui.visual_builder.pan_viewer import PanNodeViewer
from visual import visual_schema as vs
from visual.node_defs import NODE_DEFS

NODE_IDENTIFIER = "visual.nodes"
COMPOUND_IDENTIFIER = "visual.compound"   # 复合节点单独命名空间（palette 隐藏）


class _CompoundGridDelegate(QStyledItemDelegate):
    """基础节点（NodesGridView）同款圆角按钮绘制，适配 QListWidget（2026-08-16）。

    复刻 NodeGraphQt custom_widgets/nodes_palette.py 的 _NodesGridDelegate：
    圆角矩形 + 左右端口竖条/圆点 + 居中文本；无图标。
    """

    def paint(self, painter, option, index):
        if index.column() != 0:
            super().paint(painter, option, index)
            return
        item_text = str(index.data(Qt.DisplayRole) or "")

        sub_margin = 2
        radius = 5
        base_rect = QRectF(
            option.rect.x() + sub_margin,
            option.rect.y() + sub_margin,
            option.rect.width() - (sub_margin * 2),
            option.rect.height() - (sub_margin * 2),
        )
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        bg_color = option.palette.window().color()
        pen_color = option.palette.midlight().color().lighter(120)
        if option.state & QStyle.State_Selected:
            bg_color = bg_color.lighter(120)
            pen_color = pen_color.lighter(160)
        pen = QPen(pen_color, 3.0)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(QBrush(bg_color))
        painter.drawRoundedRect(base_rect,
                                int(base_rect.height() / radius),
                                int(base_rect.width() / radius))
        if option.state & QStyle.State_Selected:
            pen_color = option.palette.highlight().color()
        else:
            pen_color = option.palette.midlight().color().darker(130)
        pen = QPen(pen_color, 1.0)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        sub_margin = 6
        sub_rect = QRectF(
            base_rect.x() + sub_margin,
            base_rect.y() + sub_margin,
            base_rect.width() - (sub_margin * 2),
            base_rect.height() - (sub_margin * 2),
        )
        painter.drawRoundedRect(sub_rect,
                                int(sub_rect.height() / radius),
                                int(sub_rect.width() / radius))
        painter.setBrush(QBrush(pen_color))
        edge_size = 2, sub_rect.height() - 6
        left_x = sub_rect.left()
        right_x = sub_rect.right() - edge_size[0]
        pos_y = sub_rect.center().y() - (edge_size[1] / 2)
        for pos_x in [left_x, right_x]:
            painter.drawRect(QRectF(pos_x, pos_y, edge_size[0], edge_size[1]))
        painter.setBrush(QBrush(bg_color))
        dot_size = 4
        left_x = sub_rect.left() - 1
        right_x = sub_rect.right() - (dot_size - 1)
        pos_y = sub_rect.center().y() - (dot_size / 2)
        for pos_x in [left_x, right_x]:
            painter.drawEllipse(QRectF(pos_x, pos_y, dot_size, dot_size))
            pos_x -= dot_size + 2
        pen_color = option.palette.text().color()
        pen = QPen(pen_color, 0.5)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        font = painter.font()
        fm = QFontMetrics(font)
        if hasattr(fm, 'horizontalAdvance'):
            font_width = fm.horizontalAdvance(item_text.replace(' ', '_'))
        else:
            font_width = fm.width(item_text.replace(' ', '_'))
        font_height = fm.height()
        text_rect = QRectF(
            sub_rect.center().x() - (font_width / 2),
            sub_rect.center().y() - (font_height * 0.55),
            font_width, font_height)
        painter.drawText(text_rect, item_text)
        painter.restore()


class CompoundListWidget(QListWidget):
    """节点组合列表（2026-08-16）：无抓取轮询式手动拖拽部署。

    ⚠️ 卡死教训：
    - QListWidget 内置拖拽 = 阻塞式 QDrag.exec_() 模态循环 → 已禁用；
    - grabMouse() 抓取在真机拖经画布时可能与 NodeGraphQt 控件抢事件
      → 不再抓取，改用 50ms 定时器轮询左键状态（release 事件丢失也能完成）。
    """

    compound_drop_requested = pyqtSignal(str)  # 手动拖拽释放（节点名）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_item = None
        self._press_pos = None
        self._dragging = False
        self.setMouseTracking(True)
        # 与基础节点一致的按钮网格样式（IconMode），无图标纯文本
        self.setViewMode(QListWidget.IconMode)
        self.setSpacing(4)
        self.setWrapping(True)
        self.setMovement(QListWidget.Static)
        self.setUniformItemSizes(True)
        self.setResizeMode(QListWidget.Adjust)
        # 基础节点同款圆角按钮绘制（delegate 复刻）
        self.setItemDelegate(_CompoundGridDelegate(self))
        # 禁用内置拖拽（阻塞模态 QDrag 会卡死）
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        # 左键状态轮询（不依赖 release 事件投递）
        from PyQt5.QtCore import QTimer
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(50)
        self._watch_timer.timeout.connect(self._watch_drag)

    def hideEvent(self, event):
        """隐藏时停止轮询（防残留定时器）"""
        self._reset_drag()
        super().hideEvent(event)

    def _reset_drag(self) -> None:
        self._press_item = None
        self._press_pos = None
        self._dragging = False
        self.unsetCursor()
        self._watch_timer.stop()

    def _emit_drop(self, item) -> None:
        name = item.data(Qt.UserRole)
        if name:
            self.compound_drop_requested.emit(name)

    def _watch_drag(self) -> None:
        """轮询：左键已释放而 release 事件未达 → 完成拖拽（2026-08-16）。"""
        if self._press_item is None:
            self._watch_timer.stop()
            return
        from PyQt5.QtWidgets import QApplication
        if not (QApplication.mouseButtons() & Qt.LeftButton):
            was_dragging = self._dragging
            item = self._press_item
            self._reset_drag()
            if was_dragging:
                self._emit_drop(item)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None and item.data(Qt.UserRole):
                self._press_item = item
                self._press_pos = event.pos()
                self._dragging = False
                self.setCurrentItem(item)   # 单击仍可选中（删除按钮用）
                self._watch_timer.start()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_item is not None:
            if not self._dragging and \
                    (event.pos() - self._press_pos).manhattanLength() > 10:
                self._dragging = True
                self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press_item is not None:
            was_dragging = self._dragging
            item = self._press_item
            self._reset_drag()
            if was_dragging:
                self._emit_drop(item)
            event.accept()
            return
        super().mouseReleaseEvent(event)

# 节点内嵌输入控件统一深色样式（模块级：自绘下拉控件等复用）
_INPUT_QSS = """
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit, QDateEdit,
QTimeEdit, QDateTimeEdit {
    background-color: #1b2026;
    color: #e8eaed;
    border: 1px solid #3a4149;
    border-radius: 3px;
    padding: 1px 5px;
}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {
    border: 1px solid #5a6673;
}
QComboBox::drop-down {
    border: none;
    width: 16px;
}
QComboBox QAbstractItemView {
    background-color: #1b2026;
    color: #e8eaed;
    border: 1px solid #3a4149;
    selection-background-color: #2b6cb0;
}
QCheckBox { color: #e8eaed; background: transparent; }
QCheckBox::indicator { width: 13px; height: 13px; }
QPushButton {
    background-color: #1b2026;
    color: #e8eaed;
    border: 1px solid #3a4149;
    border-radius: 3px;
    padding: 1px 5px;
}
QPushButton:hover { border: 1px solid #5a6673; }
QPushButton:pressed { background-color: #2a313a; }
"""


def _patch_horizontal_node_widgets() -> None:
    """统一节点内嵌参数控件样式（label 左/输入右，深色主题与节点卡片一致）。

    通过替换 NodeGraphQt 的私有 _NodeGroupBox 布局类实现（不修改第三方源码）：
    - 布局：label 左 / 输入右（水平）
    - 容器：真正透明（WA_TranslucentBackground + QSS transparent），
      直接透出节点卡片自身背景色，天然完全一致（已验证可行）
    - 输入控件：深色 QSS 统一（下拉/数字/文本/勾选）
    """
    from PyQt5.QtCore import Qt as _Qt
    from PyQt5.QtWidgets import QGroupBox, QHBoxLayout, QLabel as _QLabel
    from NodeGraphQt.widgets import node_widgets as _nw

    _DARK_QSS = """
    QGroupBox {
        background: transparent;
        border: none;
    }
    """ + _INPUT_QSS

    def _unbounded_proxy(widget_cls):
        """去掉 NodeLineEdit/NodeSpinBox/NodeCheckBox 的 proxy 最大宽 140 限制。

        NodeGraphQt 这三类在 __init__ 末尾调用 self.widget().setMaximumWidth(140)，
        导致这些控件的 proxy 只有 140 宽（而 QComboBox 无此限制 = 全宽），
        表现为输入框长度不一致。包装 __init__ 在构造后取消限制。
        """
        orig_init = widget_cls.__init__

        def wrapper(self, *args, **kwargs):
            orig_init(self, *args, **kwargs)
            proxy = self.widget()
            if proxy is not None:
                proxy.setMaximumWidth(16777215)  # 取消 140 限制，回到 group 布局宽度

        widget_cls.__init__ = wrapper

    for _cls in (_nw.NodeLineEdit, _nw.NodeSpinBox, _nw.NodeCheckBox):
        _unbounded_proxy(_cls)

    class _HorizontalNodeBox(QGroupBox):
        # 固定列宽：label 列（右对齐，文字间隔不同）+ 输入框列（长度一致）
        LABEL_W = 80
        INPUT_W = 170

        def __init__(self, label, parent=None):
            super().__init__(parent)
            # 真正透明：透出节点卡片自身背景色（非白块、与卡片完全一致）
            self.setAttribute(_Qt.WA_TranslucentBackground, True)
            self._lab = _QLabel(label)
            self._lab.setAlignment(_Qt.AlignRight | _Qt.AlignVCenter)
            self._lab.setFixedWidth(self.LABEL_W)
            self._lab.setStyleSheet("color:#9aa4b2;background:transparent;")
            lay = QHBoxLayout(self)
            lay.setSpacing(4)
            lay.setContentsMargins(6, 2, 6, 2)
            lay.addWidget(self._lab, 0, _Qt.AlignVCenter)
            super().setTitle("")  # 不用 QGroupBox 顶部 title（label 已放左侧）
            self.setStyleSheet(_DARK_QSS)

        def setTitle(self, text):
            self._lab.setText(text)

        def setTitleAlign(self, align="center"):
            pass

        def add_node_widget(self, widget):
            # 输入框固定宽度 → 所有行输入框长度一致，右边缘对齐
            widget.setFixedWidth(self.INPUT_W)
            # 直接覆盖 NodeLineEdit/SpinBox/CheckBox 自带半透明浅色 QSS → 统一深色
            widget.setStyleSheet(_INPUT_QSS)
            # 下拉框：固定高度（弹出列表高度由 _NodeCombo.showPopup 强制，
            # 不依赖 AdjustToContentsOnFirstShow/view QSS——后者在部分平台/主题下
            # 会被算成极小弹出框，列表只剩一行）
            if isinstance(widget, QComboBox):
                widget.setMinimumHeight(28)
                widget.setFixedHeight(28)
            self.layout().addWidget(widget, 0, _Qt.AlignVCenter)

        def get_node_widget(self):
            return self.layout().itemAt(1).widget()

    _nw._NodeGroupBox = _HorizontalNodeBox

_PORT_COLORS = {
    "control": (160, 170, 185),
    "scene": (110, 190, 120),
    "text": (120, 160, 220),
    "value": (220, 180, 100),
    "point": (200, 120, 170),
    "image": (150, 150, 150),
}


def _port_color(port_type: str) -> tuple:
    return _PORT_COLORS.get(port_type, (150, 150, 150))


def _add_param_widget(node, p: dict) -> None:
    """按参数定义添加内嵌 widget"""
    name = p["name"]
    label = p.get("label", name)
    kind = p.get("widget", "text")
    if kind == "combo":
        # 固定选项下拉：同样走自绘控件（统一弹出列表强制尺寸，杜绝被压缩）
        node.add_custom_widget(_NodeComboWidget(
            parent=node.view, name=name, label=label,
            items=list(p.get("options", []))))
    elif kind in ("combo_scene", "combo_point", "combo_ocr_region",
                  "combo_element", "combo_signal", "combo_ocr"):
        # 动态下拉（场景/点击点/OCR区域/图标素材/场景信号/OCR识别素材）：全部走自绘控件
        # - 图标素材/OCR识别素材：显示条目名、值存完整路径（避免长路径挤爆）
        # - 其余：显示条目名、值存条目名（combo_signal 存信号名，触发器据此匹配）
        # - 弹出列表高度在 showPopup 强制，不依赖平台默认计算
        node.add_custom_widget(_NodeComboWidget(
            parent=node.view, name=name, label=label,
            path_mode=(kind in ("combo_element", "combo_ocr"))))
    elif kind == "spinbox":
        node.add_spinbox(name, label,
                         value=p.get("default", 0),
                         min_value=p.get("min", 0),
                         max_value=p.get("max", 100))
    elif kind == "text":
        node.add_text_input(name, label, text=str(p.get("default", "")))
    elif kind == "checkbox":
        node.add_checkbox(name, label, state=bool(p.get("default", False)))
    elif kind == "button":
        # 变量组/常量组【详情】按钮：点击打开变量定义编辑弹窗。
        # ⚠️ 必须延迟到系统双击窗口结束后再打开（QTimer.singleShot）：
        # 在鼠标点击/信号处理栈中立即创建 QDialog 会与鼠标释放事件竞态，
        # 真实 Windows 平台 Qt C++ 崩溃（0xC0000409；offscreen 复现不了）。
        # 实测：0ms 崩 / 300ms 崩 / doubleClickInterval+100 安全。
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication as _QApp
        delay = _QApp.doubleClickInterval() + 100
        node.add_custom_widget(_NodeButtonWidget(
            parent=node.view, name=name, label=label,
            # ⚠️ clicked 信号会传 checked(bool)——必须用 *a 吞掉，
            # 否则 node 会被覆盖成 False（AttributeError 闪退）
            clicked=lambda *a, n=node, d=delay: QTimer.singleShot(
                d, lambda: _open_var_edit_dialog(n))))


def _build_node_class(node_type: str,
                      identifier: str = NODE_IDENTIFIER) -> type:
    """动态生成 BaseNode 子类（类名 = 节点类型 → type_ = {identifier}.{type}）"""
    d = NODE_DEFS[node_type]

    def __init__(self):
        BaseNode.__init__(self)
        for inp in d.get("inputs", []):
            self.add_input(inp["name"], color=_port_color(inp.get("port_type", "control")))
        for out in d.get("outputs", []):
            self.add_output(out["name"], color=_port_color(out.get("port_type", "control")))
        for p in d.get("params", []):
            _add_param_widget(self, p)
        # 截图器节点：内嵌图片预览（ComfyUI PreviewImage 风格，直接显示截到的帧）
        # parent=self.view：必须挂到节点图形项上才会进场景渲染
        # （官方 add_combo_menu 等同样传 self.view；parent=None 的 proxy 不渲染）
        if node_type == "screenshot":
            self._preview = _PreviewWidget(parent=self.view,
                                           name="frame_preview")
            self.add_custom_widget(self._preview)

    return type(node_type, (BaseNode,), {
        "__identifier__": identifier,
        "NODE_NAME": d.get("label", node_type),  # 节点库显示名（中文），类型识别用 type_
        "__init__": __init__,
    })


def _open_var_edit_dialog(node) -> None:
    """打开变量/常量组定义编辑弹窗，保存后写回节点 property。"""
    # 防御：clicked 信号会传 checked(bool)——槽用 *a 吞参后再调这里，
    # 此处再验类型，避免非法对象导致 UI 闪退
    if node is None or not hasattr(node, "properties"):
        return
    from ui.visual_builder.variable_dialog import (ConstantGroupDialog,
                                                   VariableGroupDialog)
    ntype = node.type_.split(".")[-1] if hasattr(node, "type_") else ""
    custom = dict((node.properties() or {}).get("custom", {}) or {})
    variables = list(custom.get("variables") or [])
    group_name = str(custom.get("group_name", "") or node.name() or "")
    dlg = None
    if ntype == "constant_group":
        dlg = ConstantGroupDialog(group_name, variables)
    else:
        dlg = VariableGroupDialog(group_name, variables)
    if dlg.exec_() != dlg.Accepted:
        return
    custom["variables"] = dlg.variables
    try:
        node.set_property("variables", dlg.variables)
    except Exception:
        pass
    # 图变更 → 父级刷新「变量配置」Tab
    try:
        from PyQt5.QtCore import QCoreApplication
        canvas = _find_canvas(node)
        if canvas is not None:
            canvas.graph_changed.emit()
    except Exception:
        pass


def _find_canvas(node):
    """从节点往上找 GraphCanvas（graph view → canvas widget）"""
    try:
        g = node.graph
        w = g.widget
        while w is not None:
            from ui.visual_builder.graph_canvas import GraphCanvas
            if isinstance(w, GraphCanvas):
                return w
            w = w.parentWidget() if hasattr(w, "parentWidget") else None
    except Exception:
        pass
    return None


# 节点内嵌按钮（变量组/常量组【详情】）：与输入框一致的长宽/圆角/深色背景
# （规则同时并入 _INPUT_QSS：add_node_widget 会用它覆盖子控件样式）
_BTN_QSS = """
QPushButton {
    background-color: #1b2026;
    color: #e8eaed;
    border: 1px solid #3a4149;
    border-radius: 3px;
    padding: 1px 5px;
}
QPushButton:hover { border: 1px solid #5a6673; }
QPushButton:pressed { background-color: #2a313a; }
"""


class _NodeButtonWidget(_nw2.NodeBaseWidget):
    """节点内嵌按钮（变量组/常量组【详情】）。

    ⚠️ QPushButton 必须直接作为 custom widget（与官方 NodeCheckBox 一致），
    不能包一层 holder QWidget：QGraphicsProxyWidget 内嵌嵌套 QWidget 的鼠标
    事件转发会在真实 Windows 平台递归 → 栈溢出崩溃（0xC0000409）。
    """

    W, H = 170, 28   # 与输入框一致（_HorizontalNodeBox.INPUT_W × 下拉高度）

    def __init__(self, parent=None, name="", label="", clicked=None):
        super().__init__(parent, name=name, label=label)
        btn = QPushButton("📝 详情编辑")
        btn.setFixedSize(self.W, self.H)
        btn.setStyleSheet(_BTN_QSS)
        btn.setCursor(Qt.PointingHandCursor)
        if clicked is not None:
            btn.clicked.connect(clicked)
        self._btn = btn
        self.set_custom_widget(btn)

    def get_value(self):
        return None

    def set_value(self, value):
        pass


class _NodeCombo(QComboBox):
    """节点内嵌下拉（2026-08-15）：弹出列表高度强制。

    Qt 在部分平台/主题（尤其 QGraphicsProxyWidget 内嵌 + 全局 QSS）下会把
    QComboBox 弹出列表算成极小高度，只能露出一个选项（用户看到"列表被压缩、
    选项只能显示一个"）。这里在每次 showPopup 后按 条目数 × 行高 强制设置
    视图高度，容器随视图调整，从根上保证列表完整可见。
    """

    ROW_H = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(28)
        self.setFixedHeight(28)
        self.setMaxVisibleItems(12)
        self._want_h = 0

    def showPopup(self) -> None:
        # 1) 弹出前：按 条目数×行高 钉死视图最小高度。
        #    真实 Windows 平台会把弹出列表算成极小（行高仅 ~12px，只露一行），
        #    预先设最小高度让弹出容器按正确尺寸展开。
        self._want_h = 0
        try:
            v = self.view()
            if v is not None and self.count() > 0:
                rows = min(max(1, self.count()), self.maxVisibleItems())
                row_h = max(self.ROW_H, v.sizeHintForRow(0) + 8)
                self._want_h = rows * row_h
                v.setMaximumHeight(16777215)   # 解除上次可能遗留的固定高度
                v.setMinimumHeight(self._want_h)
        except Exception:
            pass
        super().showPopup()
        # 2) 弹出后兑底：若平台仍按极小尺寸弹出，只钉视图高度。
        #    严禁 adjustSize/操作弹出容器——真实 Windows 平台会把容器压成
        #    2px 宽（列表实际已开但不可见，表现为"打不开下拉菜单"）。
        if self._want_h:
            try:
                v = self.view()
                if v is not None and v.height() < self._want_h:
                    v.setMinimumHeight(self._want_h)
                    v.setFixedHeight(self._want_h)
            except Exception:
                pass


class _NodeComboWidget(_nw2.NodeBaseWidget):
    """节点内嵌下拉（2026-08-15）：统一场景/点击点/OCR区域/图标素材下拉。

    - 显示文本 = 条目名（如 模板图标3 / 模拟器界面），不再挤爆节点
    - itemData  = 完整路径（path_mode=True，图标素材）或条目名本身
    - get_value() 返回 itemData → 节点参数/任务 JSON 直接存路径/条目名
    - showPopup 强制弹出列表高度（防被平台/主题压缩成单行）
    """

    def __init__(self, parent=None, name="", label="",
                 path_mode: bool = False, items=None):
        super().__init__(parent, name=name, label=label)
        self.setZValue(_nw2.Z_VAL_NODE_WIDGET + 1)
        self._path_mode = bool(path_mode)
        combo = _NodeCombo()
        combo.setStyleSheet(_INPUT_QSS)
        combo.currentIndexChanged.connect(self.on_value_changed)
        self.set_custom_widget(combo)
        if items:
            self.set_value(list(items))

    @staticmethod
    def _disp(rel: str) -> str:
        s = str(rel or "").strip()
        if not s:
            return s
        try:
            return Path(s).stem or s
        except Exception:
            return s

    def type_(self):
        return "NodeComboWidget"

    def get_value(self):
        """返回 itemData（路径模式=完整路径）；未选中返回空串"""
        combo = self.get_custom_widget()
        return combo.currentData() or ""

    def set_value(self, value):
        combo = self.get_custom_widget()
        if isinstance(value, (list, tuple)):
            # 重新填充：显示名 + data（路径模式存完整路径，否则存条目名）
            cur = self.get_value()
            combo.blockSignals(True)
            combo.clear()
            for rel in value:
                rel = str(rel)
                combo.addItem(self._disp(rel) if self._path_mode else rel,
                              rel)
            combo.blockSignals(False)
            if cur:
                idx = combo.findData(cur)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            return
        idx = combo.findData(value)
        if idx >= 0:
            if idx != combo.currentIndex():
                combo.setCurrentIndex(idx)
            else:
                # 目标已是当前项：仍强制同步 property（重载后首项未写入的情况）
                self.on_value_changed()

    def all_items(self) -> list:
        combo = self.get_custom_widget()
        return [combo.itemData(i) for i in range(combo.count())]


# 兼容旧名（历史引用）
_ElementComboWidget = _NodeComboWidget


class _PreviewWidget(_nw2.NodeBaseWidget):
    """截图器节点内嵌预览控件：显示最近一次截到的帧（缩略图）"""

    W, H = 224, 126   # 16:9 缩略图

    class _Holder(QWidget):
        """内嵌容器：NodeGraphQt 布局器会调 setTitle/setTitleAlign"""

        def setTitle(self, text):
            pass

        def setTitleAlign(self, align="center"):
            pass

    def __init__(self, parent=None, name="frame_preview", label=""):
        super().__init__(parent, name=name, label=label)
        holder = self._Holder()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self._label = QLabel("📷 截图预览\n等待截图器执行…")
        self._label.setFixedSize(self.W, self.H)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "background:#0d1117;color:#9aa4b2;font-size:11px;"
            "border:2px dashed #3a4149;border-radius:4px;")
        lay.addWidget(self._label)
        self.setWidget(holder)

    def get_value(self):
        return None

    def set_value(self, value):
        pass

    def set_image(self, img: QImage) -> None:
        """把截图帧显示到节点上（保持比例缩放到缩略图）"""
        if img is None or img.isNull():
            return
        pix = QPixmap.fromImage(img).scaled(
            self.W - 6, self.H - 6, Qt.KeepAspectRatio,
            Qt.SmoothTransformation)
        self._label.setPixmap(pix)
        self._label.setText("")
        self._label.update()
        self.update()   # 强制节点重绘（真实 GUI 下确保立即显示）


def _apply_params(node, params: dict) -> None:
    """把 JSON 参数填入节点（widget 优先，fallback set_property；
    backdrop 等 NodeObject 无 get_widget 时走 set_property）。

    防御：BaseNode 上无 widget 的未知参数直接跳过（set_property 会把
    未注册属性压入 undo 栈，redo 时 NodePropertyError 崩溃）。
    """
    has_widget = hasattr(node, "get_widget")
    for name, value in (params or {}).items():
        if has_widget:
            w = node.get_widget(name)
            if w is not None:
                try:
                    w.set_value(value)
                except Exception:
                    pass
            continue   # 未知参数不写 property
        try:
            node.set_property(name, value)
        except Exception:
            pass


class GraphCanvas(QWidget):
    """节点画布（编辑视图）"""

    selection_changed = pyqtSignal()  # 选中节点变化（供父级更新示教按钮状态）
    teach_node_requested = pyqtSignal(str, str)  # 右键菜单请求示教 (node_id, node_type)
    graph_changed = pyqtSignal()  # 图变更（变量组编辑/加载/增删节点 → 父级刷新变量配置页）
    progress_group_added = pyqtSignal(dict)  # 保存进度节点（2026-08-16）：{name, nodes}

    def __init__(self, element_provider: Callable[[], list[str]] | None = None,
                 scene_provider: Callable[[], list[str]] | None = None,
                 point_provider: Callable[[], list[str]] | None = None,
                 ocr_provider: Callable[[], list[str]] | None = None,
                 signal_provider: Callable[[], list[str]] | None = None,
                 ocr_material_provider: Callable[[], list[str]] | None = None,
                 compound_list_provider: Callable[[], list[dict]] | None = None,
                 compound_loader: Callable[[str], dict | None] | None = None,
                 save_compound_cb: Callable[[dict], None] | None = None,
                 delete_compound_cb: Callable[[str], bool] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._element_provider = element_provider  # 素材元素下拉源
        self._scene_provider = scene_provider          # 示教场景下拉源（实时）
        self._point_provider = point_provider          # 示教点击点下拉源（实时）
        self._ocr_provider = ocr_provider              # OCR 区域下拉源（实时）
        self._signal_provider = signal_provider        # 场景信号下拉源（信号触发器）
        self._ocr_material_provider = ocr_material_provider  # OCR识别素材下拉源
        self._compound_list_provider = compound_list_provider  # 节点组合列表源
        self._compound_loader = compound_loader        # 节点组合定义加载器
        self._save_compound_cb = save_compound_cb      # 保存节点组合回调
        self._delete_compound_cb = delete_compound_cb  # 删除节点组合回调（2026-08-16）
        self._task: dict = {}
        self._hl_node_id: str = ""      # 运行中高亮节点 id
        self._hl_orig_color: tuple | None = None   # 高亮前原颜色（恢复用）
        # 标签框（2026-08-16）：tag id → {node(backdrop), name, nodes(task ids), stage}
        self._tag_map: dict[str, dict] = {}
        self._move_guard = False         # 节点位置钳制防重入
        # 任务 JSON id ↔ 画布节点双向映射（NodeGraphQt 节点 id 是内存地址，
        # 与任务 JSON id 不同；运行期高亮/预览按任务 id 查找走此映射）
        self._task_to_node: dict[str, Any] = {}
        self._node_to_task: dict[Any, str] = {}

        # 节点参数控件：label 左 / 输入右（水平布局）
        _patch_horizontal_node_widgets()

        self._graph = NodeGraph(viewer=PanNodeViewer())  # 左键拖空白平移
        # 选中变化 → 转发给父级（更新示教按钮状态）
        try:
            self._graph.viewer().node_selection_changed.connect(
                self._on_selection_changed)
        except Exception:
            pass
        self._node_classes: dict[str, type] = {}
        self._register_all()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # 顶部：仅撤销 / 重做（添加节点用右侧节点库拖放；删除用右键菜单/Delete 键）
        toolbar = QHBoxLayout()
        self._undo_btn = QPushButton("↩ 撤销")
        self._undo_btn.clicked.connect(self._graph._undo_stack.undo)
        toolbar.addWidget(self._undo_btn)
        self._redo_btn = QPushButton("↪ 重做")
        self._redo_btn.clicked.connect(self._graph._undo_stack.redo)
        toolbar.addWidget(self._redo_btn)
        # 封装标签（2026-08-16）：框选节点后点击 → 装进可命名标签框
        self._tag_btn = QPushButton("🏷 封装标签")
        self._tag_btn.setToolTip("框选节点后点击：把选中节点装进一个可命名的标签框")
        self._tag_btn.clicked.connect(self.tag_selected_nodes)
        toolbar.addWidget(self._tag_btn)
        toolbar.addStretch(1)
        lay.addLayout(toolbar)

        # NodeGraphQt 视图（键盘 Delete 删除选中）
        self._viewer = self._graph.widget
        self._viewer.installEventFilter(self)
        # 右键菜单（删除节点/连线）：真正的 viewer 是 graph.viewer()（PanNodeViewer），
        # 而非 graph.widget（NodeGraphWidget 容器）
        try:
            self._graph.viewer().node_context_action.connect(self._on_context_action)
            # 节点移动 → 标签内节点钳制在标签范围内（2026-08-16）
            self._graph.viewer().moved_nodes.connect(self._on_nodes_moved)
            # 标签阶段状态查询（右键菜单区分「设为阶段/取消阶段」）
            self._graph.viewer().stage_checker = self._tag_is_stage
            # 通用节点拖放 → 部署为标签（2026-08-16）
            self._graph.viewer().compound_dropped.connect(
                self._on_compound_dropped)
        except Exception:
            pass

        # 右侧：节点库（基础节点 + 通用节点）
        # （属性面板 PropertiesBinWidget 已移除：它只显示底层 model 属性，
        #   对我们的自定义节点无实际作用——节点参数已内嵌在节点本体直接编辑）
        from NodeGraphQt import NodesPaletteWidget
        self._palette = NodesPaletteWidget(node_graph=self._graph)
        self._palette.setWindowTitle("节点库")
        # 隐藏 compound 的节点库 Tab（复合节点由封装/通用节点库产生，不手动拖）
        try:
            tw = self._palette._tab_widget
            for i in range(tw.count()):
                if "compound" in str(tw.tabText(i)).lower():
                    tw.removeTab(i)
                    break
        except Exception:
            pass
        # 隐藏内置 BackdropNode 的节点库 Tab（标签框仅由右键创建，2026-08-16）
        try:
            tw = self._palette._tab_widget
            for i in range(tw.count() - 1, -1, -1):
                title = str(tw.tabText(i)).lower()
                if title.startswith("nodegraphqt") or "backdrop" in title:
                    tw.removeTab(i)
        except Exception:
            pass
        # 只有 visual.nodes 一个分组时，隐藏内部 Tab 栏（去掉嵌套的 visual 子 Tab，
        # 节点直接显示在「基础节点」下一层），保留拖放/双击功能
        try:
            self._palette._tab_widget.setTabBarAutoHide(True)
        except Exception:
            pass

        # 节点组合 Tab（2026-08-16 更名，原「通用节点」）：像基础节点一样拖动部署为标签，可删除
        op_widget = QWidget()
        op_lay = QVBoxLayout(op_widget)
        op_lay.setContentsMargins(2, 2, 2, 2)
        op_lay.setSpacing(3)
        self._compound_list = CompoundListWidget()
        self._compound_list.setToolTip("拖到画布（或双击）：部署为一个标签")
        self._compound_list.itemDoubleClicked.connect(
            self._on_compound_double_clicked_async)
        # 手动拖拽释放 → 异步部署（脱离鼠标事件栈，避免同步建图卡顿/冲突）
        from PyQt5.QtCore import QTimer
        self._compound_list.compound_drop_requested.connect(
            lambda name: QTimer.singleShot(
                0, lambda: self._on_compound_manual_drop(name)))
        op_lay.addWidget(self._compound_list, 1)
        self._compound_del_btn = QPushButton("🗑 删除节点组合")
        self._compound_del_btn.setToolTip("删除选中的节点组合（从节点组合库移除）")
        self._compound_del_btn.clicked.connect(self._on_compound_delete)
        op_lay.addWidget(self._compound_del_btn)

        # 节点分类 Tab
        self._side_tabs = QTabWidget()
        self._side_tabs.addTab(self._palette, "基础节点")
        self._side_tabs.addTab(op_widget, "节点组合")

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(2)
        lab_p = QLabel("节点库")
        lab_p.setStyleSheet("font-weight:bold;font-size:11px;color:#5a6a80;")
        side.addWidget(lab_p)
        side.addWidget(self._side_tabs, 1)
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setMaximumWidth(280)

        body = QSplitter(Qt.Horizontal)
        body.addWidget(self._viewer)
        body.addWidget(side_widget)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 0)
        body.setSizes([900, 240])
        lay.addWidget(body, 1)

        self.refresh_compound_list()

    # ── 节点注册 ──────────────────────────────────────────
    def _register_all(self) -> None:
        for t in NODE_DEFS:
            ident = COMPOUND_IDENTIFIER if t == "compound" \
                else NODE_IDENTIFIER
            cls = _build_node_class(t, ident)
            self._node_classes[t] = cls
            self._graph.register_node(cls)
        # 标签框（2026-08-16）：注册内置 BackdropNode（不进入节点库，仅由右键创建）
        try:
            from NodeGraphQt.nodes.backdrop_node import BackdropNode
            self._graph.register_node(BackdropNode)
        except Exception:
            pass

    def _node_type_path(self, node_type: str) -> str:
        """节点类型 → NodeGraphQt 类型路径"""
        ident = COMPOUND_IDENTIFIER if node_type == "compound" \
            else NODE_IDENTIFIER
        return f"{ident}.{node_type}"

    # ── 任务加载 / 导出 ───────────────────────────────────
    def load_task(self, task: dict) -> None:
        """任务 JSON → 画布"""
        self._task = vs.normalize_task(task)
        self._graph.clear_session()
        self._task_to_node = {}
        self._node_to_task = {}
        node_map: dict[str, Any] = {}
        for n in self._task.get("graph", {}).get("nodes", []):
            ntype = n.get("type", "")
            if ntype not in self._node_classes:
                continue
            try:
                node = self._graph.create_node(
                    self._node_type_path(ntype),
                    name=n.get("name", "") or NODE_DEFS[ntype]["label"],
                    pos=n.get("pos", [0, 0]),
                    selected=False, push_undo=False)
                _apply_params(node, n.get("params", {}))
                # 记录任务参数：自绘下拉（combo 空时 set_value 无效）重填后据此恢复选中
                setattr(node, "_task_params", dict(n.get("params") or {}))
                setattr(node, "_subgraph", n.get("subgraph"))  # 复合子图（自定义）
                node_map[n["id"]] = node
                self._task_to_node[n["id"]] = node
                self._node_to_task[node] = n["id"]
            except Exception:
                continue
        for c in self._task.get("graph", {}).get("connections", []):
            out_node = node_map.get(c.get("out_node"))
            in_node = node_map.get(c.get("in_node"))
            if out_node is None or in_node is None:
                continue
            try:
                out_node.get_output(c["out_port"]).connect_to(
                    in_node.get_input(c["in_port"]))
            except Exception:
                continue
        # 标签框（2026-08-16）：重建 backdrop（节点无效的标签自动跳过）
        self._tag_map = {}
        for t in self._task.get("graph", {}).get("tags", []) or []:
            if not isinstance(t, dict):
                continue
            tag_nodes = [node_map[str(n)] for n in (t.get("nodes") or [])
                         if str(n) in node_map]
            if not tag_nodes:
                continue
            try:
                b = self._graph.create_node(
                    "nodeGraphQt.nodes.BackdropNode",
                    name=t.get("name") or "标签", selected=False,
                    push_undo=False)
                b.set_text(str(t.get("name") or "标签"))
                b.wrap_nodes(tag_nodes)
                _p = t.get("pos") or list(tag_nodes[0].pos())
                b.set_pos(float(_p[0]), float(_p[1]))   # wrap 重算后恢复保存位置
                try:
                    b.view.setZValue(-100)
                except Exception:
                    pass
            except Exception:
                continue
            self._tag_map[str(t.get("id", "") or uuid.uuid4().hex[:12])] = {
                "node": b, "name": str(t.get("name") or "标签"),
                "nodes": set(tag_nodes),
                "stage": bool(t.get("stage")),
            }
            self._apply_tag_color(
                self._tag_map[str(t.get("id", "") or uuid.uuid4().hex[:12])])
        self.refresh_combos()
        self.graph_changed.emit()

    def export_task(self, task: dict) -> dict:
        """画布 → 任务 JSON（节点/连线/参数/位置）；节点 id 稳定（沿用已有任务 id）"""
        task = vs.normalize_task(task)
        nodes: list[dict] = []
        for node in self._graph.all_nodes():
            # 跳过标签框（backdrop 不入任务节点列表，见下方 tags）
            if node.type_.split(".")[-1] == "BackdropNode":
                continue
            custom = dict(node.properties().get("custom", {}) or {})
            # 已有任务 id 沿用（保存后运行期高亮/预览按此 id 匹配画布节点）
            nid = self._node_to_task.get(node) or uuid.uuid4().hex[:12]
            self._node_to_task[node] = nid
            self._task_to_node[nid] = node
            d = {
                "id": nid,
                "type": node.type_.split(".")[-1],
                "name": node.name(),
                "pos": list(node.pos()),
                "params": custom,
            }
            sub = getattr(node, "_subgraph", None)
            if sub:
                d["subgraph"] = sub   # 复合子图随节点序列化
            nodes.append(d)
        conns: list[dict] = []
        for out_port, in_port in self._iter_connections(self._graph):
            conns.append({
                "id": uuid.uuid4().hex[:12],
                # 用稳定任务 id（与上方节点 id 一致）
                "out_node": self._node_to_task.get(out_port.node(),
                                                   out_port.node().id),
                "out_port": out_port.name(),
                "in_node": self._node_to_task.get(in_port.node(),
                                                  in_port.node().id),
                "in_port": in_port.name(),
            })
        task["graph"]["nodes"] = nodes
        task["graph"]["connections"] = conns
        # 标签框序列化（2026-08-16）：已删节点的标签成员自动过滤
        valid_ids = {n["id"] for n in nodes}
        tags: list[dict] = []
        for tid, t in self._tag_map.items():
            member_ids = [self._node_to_task.get(n, n.id)
                          for n in t["nodes"]
                          if self._node_to_task.get(n, n.id) in valid_ids]
            if not member_ids:
                continue
            b = t["node"]
            try:
                if self._graph.get_node_by_id(b.id) is None:
                    continue   # 标签框已被删除（如 Delete 键）→ 跳过
                size = list(b.size())
            except Exception:
                size = [300, 160]
            tags.append({
                "id": tid, "name": t["name"], "pos": list(b.pos()),
                "size": size, "nodes": member_ids, "stage": bool(t["stage"]),
            })
        task["graph"]["tags"] = tags
        return task

    @staticmethod
    def _iter_connections(graph):
        """枚举所有连线 → (out_port, in_port)；跳过无端口节点（如 backdrop）"""
        seen: set = set()
        for node in graph.all_nodes():
            if not hasattr(node, "output_ports"):
                continue
            for out_port in node.output_ports():
                for in_port in out_port.connected_ports():
                    key = (id(out_port), id(in_port))
                    if key in seen:
                        continue
                    seen.add(key)
                    yield out_port, in_port

    def connection_count(self) -> int:
        return sum(1 for _ in self._iter_connections(self._graph))

    # ── 节点操作 ──────────────────────────────────────────
    def add_node(self, node_type: str, pos: list | None = None,
                 name: str = "") -> Any:
        """添加节点到画布（返回节点对象）"""
        if node_type not in self._node_classes:
            return None
        if pos is None:
            pos = [120 + len(self._graph.all_nodes()) * 30,
                   120 + len(self._graph.all_nodes()) * 30]
        try:
            node = self._graph.create_node(
                self._node_type_path(node_type),
                name=name or NODE_DEFS[node_type]["label"],
                pos=pos, selected=True)
            self.refresh_combos()
            self.graph_changed.emit()
            return node
        except Exception:
            return None

    # ── 通用节点（框选封装 → 保存为通用节点，2026-08-15）──
    def refresh_compound_list(self) -> None:
        """刷新右侧「节点组合」列表（像基础节点：图标 + 名称，拖动部署）"""
        self._compound_list.clear()
        items: list[dict] = []
        if self._compound_list_provider is not None:
            try:
                items = list(self._compound_list_provider() or [])
            except Exception:
                items = []
        for it in items:
            name = it.get("name", "")
            display = it.get("display_name", name)
            # 与基础节点一致：无图标，纯文本圆角按钮（同款 delegate 绘制）
            item = QListWidgetItem(f"{display}")
            item.setData(Qt.UserRole, name)
            item.setSizeHint(QSize(130, 40))
            item.setToolTip(f"{name} · 子图节点数:{it.get('node_count', 0)}\n"
                            "拖动或双击部署为标签")
            self._compound_list.addItem(item)
        if not items:
            it = QListWidgetItem(
                "（暂无节点组合 — 框选节点封装标签后保存）")
            it.setFlags(Qt.NoItemFlags)
            self._compound_list.addItem(it)
            self._compound_list.setEnabled(False)
            self._compound_del_btn.setEnabled(False)
        else:
            self._compound_list.setEnabled(True)
            self._compound_del_btn.setEnabled(True)

    def _on_compound_delete(self) -> None:
        """删除选中的节点组合（从节点组合库移除，2026-08-16）。"""
        item = self._compound_list.currentItem()
        if item is None:
            QMessageBox.information(self, "删除节点组合", "请先选中要删除的节点组合")
            return
        name = item.data(Qt.UserRole)
        if not name:
            return
        display = item.text()
        reply = QMessageBox.question(
            self, "删除节点组合",
            f"确认删除节点组合「{display}」？\n（从库中移除，不影响已部署到任务中的标签）",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        if self._delete_compound_cb is None:
            QMessageBox.information(self, "删除节点组合", "未配置删除接口")
            return
        try:
            ok = bool(self._delete_compound_cb(name))
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))
            return
        if not ok:
            QMessageBox.warning(self, "删除失败", f"「{display}」不存在或无法删除")
            return
        self.refresh_compound_list()

    def _on_compound_double_clicked_async(self, item) -> None:
        """双击 → 异步部署（脱离双击事件栈，2026-08-16）。"""
        name = item.data(Qt.UserRole)
        if name:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.place_compound_tag(name))

    def _on_compound_double_clicked(self, item) -> None:
        name = item.data(Qt.UserRole)
        if name:
            self.place_compound_tag(name)

    def _on_compound_manual_drop(self, name: str):
        """手动拖拽释放：全局鼠标位置 → 画布场景坐标 → 部署标签（2026-08-16）。"""
        try:
            from PyQt5.QtGui import QCursor
            gpos = QCursor.pos()
            viewer = self._graph.viewer()
            scene_pos = viewer.mapToScene(viewer.mapFromGlobal(gpos))
            return self.place_compound_tag(name, [scene_pos.x(), scene_pos.y()])
        except Exception:
            return self.place_compound_tag(name)

    def _on_compound_dropped(self, name: str, pos) -> None:
        """通用节点拖放到画布 → 部署为标签（拖放点 = 标签位置）。"""
        try:
            self.place_compound_tag(name, [pos.x(), pos.y()])
        except Exception:
            pass

    def place_compound_tag(self, name: str, drop_pos=None) -> str | None:
        """把通用节点部署为标签（2026-08-16）：复制子图节点 + 内部连线，
        外包一个标签框，与「封装标签」产物一致。

        - 子图节点 id 重新生成（复制多份互不冲突）
        - 整次部署注册为一个 undo 宏：点撤销一次即回到部署前
        - 返回标签 id（失败返回 None）
        """
        if self._compound_loader is None:
            return None
        try:
            data = self._compound_loader(name)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return None
        sub = data.get("subgraph") or {}
        nodes = [n for n in (sub.get("nodes") or [])
                 if isinstance(n, dict) and n.get("type") in self._node_classes]
        if not nodes:
            return None
        # 子图绝对坐标 → 相对左上角归一化
        minx = min((n.get("pos") or [0, 0])[0] for n in nodes)
        miny = min((n.get("pos") or [0, 0])[1] for n in nodes)
        if drop_pos is None:
            drop_pos = [120 + len(self._graph.all_nodes()) * 30,
                        120 + len(self._graph.all_nodes()) * 30]
        id_map: dict[str, str] = {}
        created: list = []
        # 整次部署 = 一个 undo 宏（2026-08-16：撤销一次直接回到部署前）
        self._graph.begin_undo("放置节点组合")
        try:
            for n in nodes:
                old_id = str(n.get("id", "") or "") or uuid.uuid4().hex[:12]
                nid = uuid.uuid4().hex[:12]   # 新任务内唯一 id（复制多份不冲突）
                id_map[old_id] = nid
                p = n.get("pos") or [0, 0]
                pos = [drop_pos[0] + (p[0] - minx) + 30,
                       drop_pos[1] + (p[1] - miny) + 40]
                try:
                    node = self._graph.create_node(
                        self._node_type_path(n["type"]),
                        name=n.get("name", "") or NODE_DEFS[n["type"]]["label"],
                        pos=pos, selected=False)
                except Exception:
                    continue
                _apply_params(node, n.get("params", {}))
                setattr(node, "_task_params", dict(n.get("params") or {}))
                setattr(node, "_subgraph", n.get("subgraph"))
                self._task_to_node[nid] = node
                self._node_to_task[node] = nid
                created.append(node)
            if not created:
                return None
            # 仅保留子图内部连线（外部进出不复制）
            for c in sub.get("connections") or []:
                out_n = self._task_to_node.get(id_map.get(str(c.get("out_node", "")), ""))
                in_n = self._task_to_node.get(id_map.get(str(c.get("in_node", "")), ""))
                if out_n is None or in_n is None:
                    continue
                try:
                    out_n.get_output(c.get("out_port", "out")).connect_to(
                        in_n.get_input(c.get("in_port", "in")))
                except Exception:
                    pass
            # 外包标签框（与「封装标签」一致）
            display = data.get("display_name") or name
            b = None
            try:
                b = self._graph.create_node(
                    "nodeGraphQt.nodes.BackdropNode", name=display,
                    selected=False)
                b.set_text(display)
                b.wrap_nodes(created)
                try:
                    b.view.setZValue(-100)
                except Exception:
                    pass
            except Exception:
                b = None
            tid = uuid.uuid4().hex[:12]
            if b is not None:
                self._tag_map[tid] = {"node": b, "name": display,
                                      "nodes": set(created), "stage": False}
        finally:
            self._graph.end_undo()
        self.refresh_combos()
        self.graph_changed.emit()
        try:
            self._graph.center_on([created[0]])
        except Exception:
            pass
        return tid

    def add_compound_node(self, name: str):
        """从通用节点库添加复合节点到画布（子图内嵌，任务可独立运行）"""
        if self._compound_loader is None:
            return None
        try:
            data = self._compound_loader(name)
        except Exception:
            data = None
        if data is None:
            return None
        node = self.add_node("compound",
                             name=data.get("display_name", name))
        if node is None:
            return None
        w = node.get_widget("source")
        if w is not None:
            try:
                w.set_value(name)
            except Exception:
                pass
        setattr(node, "_subgraph", data.get("subgraph"))
        try:
            self._graph.center_on([node])
        except Exception:
            pass
        return node

    def _node_by_id(self, node_id: str) -> Any:
        """按任务 id 或画布 id 查节点（运行期高亮/预览查找入口）"""
        node = self._task_to_node.get(node_id)
        if node is not None:
            return node
        try:
            return self._graph.get_node_by_id(node_id)
        except Exception:
            return None

    # ── 运行中节点红框高亮（2026-08-15）───────────────
    def highlight_node(self, node_id: str) -> None:
        """红框高亮当前执行节点；node_id 空 → 清除高亮"""
        self.clear_highlight()
        if not node_id:
            return
        try:
            node = self._node_by_id(node_id)
            if node is None:
                return
            self._hl_orig_color = node.color()
            node.set_color(255, 70, 70)   # 红框提示：当前执行节点
            self._hl_node_id = node_id
            try:
                self._graph.center_on([node])
            except Exception:
                pass
        except Exception:
            pass

    def clear_highlight(self) -> None:
        """恢复高亮节点的原颜色"""
        if self._hl_node_id:
            try:
                node = self._node_by_id(self._hl_node_id)
                if node is not None and self._hl_orig_color is not None:
                    node.set_color(*self._hl_orig_color)
            except Exception:
                pass
        self._hl_node_id = ""
        self._hl_orig_color = None

    def set_node_preview(self, node_id: str, data: bytes) -> None:
        """把截图器截到的帧显示到对应截图器节点上（PNG bytes）"""
        from loguru import logger as _lg
        try:
            node = self._node_by_id(node_id)
            if node is None:
                _lg.warning(f"[预览] 画布未找到节点: {node_id} "
                            f"（映射 {len(self._task_to_node)} 个节点）")
                return
            if not hasattr(node, "_preview"):
                _lg.warning(f"[预览] 节点无内嵌预览: {node.type_}")
                return
            img = QImage.fromData(bytes(data))
            if img.isNull():
                _lg.warning(f"[预览] PNG 解码失败: {len(data)} bytes")
                return
            node._preview.set_image(img)
            _lg.info(f"[预览] 节点预览已更新: {node_id} "
                     f"({img.width()}x{img.height()})")
        except Exception as e:
            _lg.error(f"[预览] set_node_preview 异常: {e}")

    def encapsulate_selected(self) -> str | None:
        """把当前选中节点封装为复合节点（JSON 层封装后重建画布）"""
        selected = self.selected_nodes()
        if len(selected) < 1:
            QMessageBox.information(
                self, "封装", "请先框选要封装的节点（Ctrl 点选或框选）")
            return None
        task = self.export_task(self._task)   # 先导出（登记稳定任务 id）
        ids = [self._node_to_task.get(n, n.id) for n in selected]
        cid, err = vs.encapsulate_nodes(task, ids)
        if cid is None:
            QMessageBox.warning(self, "封装失败", err)
            return None
        self._task = task
        self.load_task(task)
        return cid

    def save_compound_as_node(self, node_id: str) -> bool:
        """把复合节点保存为节点组合（存入节点组合库）"""
        if self._compound_loader is None:
            QMessageBox.information(self, "保存节点组合", "节点组合库不可用")
            return False
        task = self.export_task(self._task)
        comp = vs.find_compound_node(task.get("graph", {}), node_id)
        if comp is None or not comp.get("subgraph"):
            QMessageBox.warning(self, "保存节点组合", "该节点不是有效复合节点")
            return False
        name, ok = QInputDialog.getText(
            self, "保存节点组合", "节点名（英文，如 attack_first）:")
        if not ok or not name.strip():
            return False
        name = name.strip()
        display, ok2 = QInputDialog.getText(
            self, "保存节点组合", "显示名（如 攻击首个目标）:", text=name)
        if not ok2:
            return False
        # 通过画布 save_compound 回调（bridge.save_compound）落库
        self._save_compound_cb = getattr(self, "_save_compound_cb", None)
        if self._save_compound_cb is None:
            QMessageBox.information(self, "保存节点组合", "未配置保存接口")
            return False
        try:
            self._save_compound_cb({
                "name": name,
                "display_name": display.strip() or name,
                "subgraph": comp["subgraph"],
            })
        except Exception as e:
            QMessageBox.warning(self, "保存节点组合", f"保存失败: {e}")
            return False
        # 回填节点参数（来源名）
        comp["params"]["source"] = name
        comp["name"] = display.strip() or name
        self._task = task
        self.load_task(task)
        self.refresh_compound_list()
        QMessageBox.information(self, "已保存", f"节点组合「{name}」已保存")
        return True

    def save_progress_group(self, node_item=None) -> bool:
        """把当前选中节点保存为一个进度点（2026-08-16）。

        一个框选 = 一个 o；循环 = 循环节点 + 循环体一起框选。
        组数据经 progress_group_added 信号交给父级（面板）并入任务定义。
        """
        selected = self.selected_nodes()
        if not selected and node_item is not None:
            node = self._graph.get_node_by_id(node_item.id)
            selected = [node] if node is not None else []
        if not selected:
            QMessageBox.information(
                self, "保存进度节点", "请先框选节点（循环请连同循环体一起框选）")
            return False
        ids = [self._node_to_task.get(n, n.id) for n in selected]
        name, ok = QInputDialog.getText(
            self, "保存进度节点", "进度点名称（显示在 o 下方，如 进入战斗）:")
        if not ok or not name.strip():
            return False
        self.progress_group_added.emit({"name": name.strip(), "nodes": ids})
        return True

    # ── 删除 ──────────────────────────────────────────────
    def _on_selection_changed(self, *args) -> None:
        """NodeGraphQt 选中变化 → 转发给父级"""
        self.selection_changed.emit()

    def selected_nodes(self) -> list:
        """当前选中的节点列表"""
        return self._graph.selected_nodes()

    def set_node_scene(self, node_id: str, scene_id: str) -> bool:
        """把识别素材 id 填到节点 scene 参数 + widget 下拉（示教回填用）"""
        if not node_id or not scene_id:
            return False
        for node in self._graph.all_nodes():
            # 任务 id（稳定）或画布 id（内存地址）都可匹配
            if node_id not in (getattr(node, "id", ""),
                               self._node_to_task.get(node, "")):
                continue
            if not hasattr(node, "get_widget"):
                return False
            w = node.get_widget("scene")
            if w is not None:
                try:
                    w.set_value(scene_id)
                except Exception:
                    pass
            return True
        return False

    def set_node_element(self, node_id: str, template: str, region: str) -> bool:
        """把图标素材路径 + 搜索区域回填到节点 widget（示教回填用）"""
        if not node_id or not template:
            return False
        for node in self._graph.all_nodes():
            # 任务 id（稳定）或画布 id（内存地址）都可匹配
            if node_id not in (getattr(node, "id", ""),
                               self._node_to_task.get(node, "")):
                continue
            if not hasattr(node, "get_widget"):
                return False
            w = node.get_widget("template")
            if w is not None:
                try:
                    w.set_value(template)   # 自绘控件 findData 选中完整路径
                except Exception:
                    pass
            if region:
                w = node.get_widget("region")
                if w is not None:
                    try:
                        w.set_value(region)
                    except Exception:
                        pass
            return True
        return False

    def _on_context_action(self, action: str, item) -> None:
        """右键菜单动作：示教 / 封装 / 保存通用节点 / 标签 / 删除"""
        if action == "teach_node":
            try:
                ntype = item.type_.split(".")[-1] if hasattr(item, "type_") else ""
                # 发稳定任务 id（回填/素材目录用），无则画布 id
                self.teach_node_requested.emit(
                    self._node_to_task.get(item, item.id), ntype)
            except Exception:
                pass
        elif action == "encapsulate":
            self.encapsulate_selected()
        elif action == "save_compound":
            try:
                self.save_compound_as_node(item.id)
            except Exception:
                pass
        elif action == "save_progress":
            try:
                self.save_progress_group(item)
            except Exception:
                pass
        elif action == "tag_selected":
            self.tag_selected_nodes()
        elif action == "tag_rename":
            self.tag_rename(item)
        elif action == "tag_set_stage":
            self.tag_set_stage(item)
        elif action == "tag_save_compound":
            self.tag_save_compound(item)
        elif action == "tag_delete":
            self.tag_delete(item)
        elif action == "delete_node":
            try:
                node = self._graph.get_node_by_id(item.id)
                if node is not None:
                    ntype = node.type_.split(".")[-1] if hasattr(node, "type_") else ""
                    if ntype == "BackdropNode":
                        self.tag_delete(node)
                        return
                    self._graph.delete_node(node)
                    self.graph_changed.emit()
            except Exception:
                pass
        elif action == "delete_pipe":
            try:
                item.delete()
            except Exception:
                pass

    # ── 标签框（2026-08-16）：框选封装为标签 / 设为阶段 / 保存通用节点 ──

    def tag_selected_nodes(self) -> str | None:
        """把当前框选的节点装进一个新标签框（可命名，内部节点不能移出标签）。"""
        selected = self.selected_nodes()
        if not selected:
            QMessageBox.information(
                self, "封装为标签", "请先框选要装进标签的节点")
            return None
        name, ok = QInputDialog.getText(
            self, "封装为标签", "标签名（如 进入战斗）:")
        if not ok:
            return None
        name = name.strip() or "标签"
        # 先导出登记稳定任务 id（标签成员 id 必须与任务 JSON 节点 id 一致）
        self.export_task(self._task)
        try:
            b = self._graph.create_node(
                "nodeGraphQt.nodes.BackdropNode", name=name,
                selected=False, push_undo=False)
            b.set_text(name)
            b.wrap_nodes(selected)
            try:
                b.view.setZValue(-100)   # 标签置底，不遮挡内部节点交互
            except Exception:
                pass
        except Exception as e:
            QMessageBox.warning(self, "封装为标签", f"创建标签失败: {e}")
            return None
        tid = uuid.uuid4().hex[:12]
        self._tag_map[tid] = {
            "node": b, "name": name,
            "nodes": set(selected),   # 画布节点对象（导出时转任务 id）
            "stage": False,
        }
        self.graph_changed.emit()
        return tid

    def _tag_by_backdrop(self, item) -> str | None:
        """backdrop item → tag id（按节点对象匹配）"""
        node = item
        try:
            if hasattr(item, "node") and item.node is not None:
                node = item.node
        except Exception:
            pass
        for tid, t in self._tag_map.items():
            if getattr(t["node"], "id", None) == getattr(node, "id", None):
                return tid
            if t["node"] is node:
                return tid
        # 由 item 反查 graph 节点对象
        try:
            n = self._graph.get_node_by_id(item.id)
            for tid, t in self._tag_map.items():
                if t["node"] is n:
                    return tid
        except Exception:
            pass
        return None

    # 阶段标签浅绿色（2026-08-16），普通标签 backdrop 默认深青色
    _TAG_STAGE_COLOR = (167, 222, 160)
    _TAG_DEFAULT_COLOR = (5, 129, 138)

    def _tag_is_stage(self, item) -> bool:
        """backdrop item → 是否已设为阶段（右键菜单区分用）"""
        tid = self._tag_by_backdrop(item)
        if tid is None:
            return False
        return bool(self._tag_map[tid].get("stage"))

    def _apply_tag_color(self, t: dict) -> None:
        """阶段标签 → 浅绿色；普通标签 → 默认深青色"""
        try:
            if t.get("stage"):
                t["node"].set_color(*self._TAG_STAGE_COLOR)
            else:
                t["node"].set_color(*self._TAG_DEFAULT_COLOR)
        except Exception:
            pass

    def tag_rename(self, item) -> None:
        tid = self._tag_by_backdrop(item)
        if tid is None:
            return
        t = self._tag_map[tid]
        name, ok = QInputDialog.getText(
            self, "重命名标签", "标签名:", text=t["name"])
        if not ok or not name.strip():
            return
        t["name"] = name.strip()
        try:
            t["node"].set_text(t["name"])
        except Exception:
            pass
        self.graph_changed.emit()

    def tag_set_stage(self, item) -> None:
        """设为阶段 / 取消阶段（流程示图按设为阶段的标签排 o-o-o）。

        设为阶段 → 标签变浅绿色；取消 → 恢复默认深青色。
        """
        tid = self._tag_by_backdrop(item)
        if tid is None:
            return
        t = self._tag_map[tid]
        t["stage"] = not bool(t["stage"])
        self._apply_tag_color(t)
        self.graph_changed.emit()

    def tag_save_compound(self, item) -> None:
        """把标签整体保存为节点组合（2026-08-16 放宽限制）。

        - 允许包含开始/结束节点，不要求单入口单出口
        - 标签内部节点与节点间连线原样保留；外部节点与标签内节点的连线不保留
        - 布置通用节点 = 把该标签复制到另一个任务中（画布本身不改变）
        - 入口：标签内 start 节点 > 无入边节点 > 第一个节点
        """
        tid = self._tag_by_backdrop(item)
        if tid is None:
            return
        t = self._tag_map[tid]
        ids = {self._node_to_task.get(n, n.id) for n in t["nodes"]}
        if not ids:
            QMessageBox.warning(self, "保存节点组合", "标签内没有有效节点")
            return
        task = self.export_task(self._task)
        graph = task.get("graph", {})
        nodes = [n for n in graph.get("nodes", []) if n.get("id") in ids]
        if not nodes:
            QMessageBox.warning(self, "保存节点组合", "标签内没有有效节点")
            return
        # 仅保留标签内部连线（外部进/出连线不保存）
        conns = [c for c in graph.get("connections", [])
                 if c.get("out_node") in ids and c.get("in_node") in ids]
        # 确定入口
        starts = [n["id"] for n in nodes if n.get("type") == "start"]
        if starts:
            entry_id = starts[0]
        else:
            has_in = {c["in_node"] for c in conns}
            no_in = [n["id"] for n in nodes if n["id"] not in has_in]
            entry_id = no_in[0] if no_in else nodes[0]["id"]
        name, ok = QInputDialog.getText(
            self, "保存节点组合", "节点名（英文，如 attack_first）:",
            text=t["name"])
        if not ok or not name.strip():
            return
        name = name.strip()
        display, ok2 = QInputDialog.getText(
            self, "保存节点组合", "显示名:", text=t["name"])
        if not ok2:
            return
        if self._save_compound_cb is None:
            QMessageBox.information(self, "保存节点组合", "未配置保存接口")
            return
        try:
            self._save_compound_cb({
                "name": name,
                "display_name": display.strip() or name,
                "subgraph": {"nodes": nodes, "connections": conns,
                             "entry_id": entry_id},
            })
        except Exception as e:
            QMessageBox.warning(self, "保存节点组合", f"保存失败: {e}")
            return
        self.refresh_compound_list()
        QMessageBox.information(self, "已保存",
                                f"节点组合「{name}」已保存（标签不变，"
                                "可在其他任务拖动部署）")

    def tag_delete(self, item) -> None:
        """删除标签框（内部节点保留）"""
        tid = self._tag_by_backdrop(item)
        if tid is None:
            return
        t = self._tag_map.pop(tid, None)
        if t is None:
            return
        try:
            self._graph.delete_node(t["node"])
        except Exception:
            pass
        self.graph_changed.emit()

    def _on_nodes_moved(self, moved) -> None:
        """节点移动 → 标签内节点钳制在标签范围内（2026-08-16）。

        moved = {AbstractNodeItem: [x, y]}（NodeViewer.moved_nodes 载荷）。
        """
        if self._move_guard or not self._tag_map:
            return
        for it in (moved or {}):
            # backdrop 自己移动不钳制
            try:
                ntype = it.type_.split(".")[-1] if hasattr(it, "type_") else ""
            except Exception:
                ntype = ""
            if ntype == "BackdropNode":
                continue
            # 该节点属于哪个标签（成员为画布节点对象，比对 view item）
            tag = None
            for t in self._tag_map.values():
                for member in t["nodes"]:
                    try:
                        if getattr(member, "view", None) is it:
                            tag = t
                            break
                    except Exception:
                        continue
                if tag is not None:
                    break
            if tag is None:
                continue
            b = tag["node"]
            try:
                bx, by = list(b.pos())[:2]
                bw, bh = list(b.size())[:2]
                nw = it.boundingRect().width()
                nh = it.boundingRect().height()
                x, y = it.xy_pos
            except Exception:
                continue
            top = by + 26   # 顶部留标签标题条
            nx = min(max(x, bx + 8), max(bx + 8, bx + bw - nw - 8))
            ny = min(max(y, top), max(top, by + bh - nh - 8))
            if abs(nx - x) < 0.5 and abs(ny - y) < 0.5:
                continue
            self._move_guard = True
            try:
                it.xy_pos = [nx, ny]
            finally:
                self._move_guard = False

    def delete_selected(self) -> int:
        """删除选中的节点（及其连线）与选中的连线；返回删除节点数"""
        self.delete_selected_pipes()
        nodes = self._graph.selected_nodes()
        if nodes:
            try:
                self._graph.delete_nodes(nodes)
            except Exception:
                for n in list(nodes):
                    try:
                        self._graph.delete_node(n)
                    except Exception:
                        pass
        if nodes:
            self.graph_changed.emit()
        return len(nodes)

    def delete_selected_pipes(self) -> int:
        """删除选中的连线；返回删除数量"""
        pipes = self._graph.selected_pipes()
        count = 0
        for p1, p2 in pipes:
            try:
                p1.clear_connections()
                count += 1
            except Exception:
                pass
        return count

    def delete_node(self, node) -> bool:
        """按节点对象删除"""
        try:
            self._graph.delete_node(node)
            return True
        except Exception:
            return False

    # ── 键盘事件（Delete/Backspace 删除选中）──────────────
    def eventFilter(self, obj, event) -> bool:
        from PyQt5.QtCore import QEvent, Qt as _Qt
        if obj is self._viewer and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (_Qt.Key_Delete, _Qt.Key_Backspace):
                self.delete_selected()
                return True
        return super().eventFilter(obj, event)

    # ── 下拉刷新（示教产物 → 节点参数）───────────────────
    def refresh_combos(self) -> None:
        """把示教产物（场景/点击点/OCR区域/素材元素）填入各节点下拉。

        场景/点击点/OCR 优先从 provider 实时拉取（示教视图添加后立即可见），
        fallback 当前任务 teach 副本。
        """
        teach = self._task.get("teach", {}) or {}

        def _items(provider, from_task):
            if provider is not None:
                try:
                    got = list(provider() or [])
                    if got:
                        return got
                except Exception:
                    pass
            return list(from_task)

        scene_items = _items(self._scene_provider,
                             [s.get("id", "") for s in teach.get("scenes", [])])
        point_items = _items(self._point_provider,
                             [p.get("id", "") for p in teach.get("points", [])])
        ocr_items = _items(self._ocr_provider,
                           [r.get("id", "") for r in teach.get("ocr_regions", [])])
        element_items = []
        if self._element_provider is not None:
            try:
                element_items = list(self._element_provider() or [])
            except Exception:
                element_items = []
        signal_items = []
        if self._signal_provider is not None:
            try:
                signal_items = list(self._signal_provider() or [])
            except Exception:
                signal_items = []
        ocr_material_items = []
        if self._ocr_material_provider is not None:
            try:
                ocr_material_items = list(self._ocr_material_provider() or [])
            except Exception:
                ocr_material_items = []

        for node in self._graph.all_nodes():
            d = NODE_DEFS.get(node.type_.split(".")[-1])
            if not d:
                continue
            if not hasattr(node, "get_widget"):
                continue  # backdrop 等 NodeObject 无内嵌 widget
            for p in d.get("params", []):
                kind = p.get("widget")
                items = None
                if kind == "combo_scene":
                    items = scene_items
                elif kind == "combo_point":
                    items = point_items
                elif kind == "combo_ocr_region":
                    items = ocr_items
                elif kind == "combo_element":
                    items = element_items   # 自绘控件内部显示条目名、值存路径
                elif kind == "combo_signal":
                    items = signal_items    # 任务素材库各场景对应的信号名
                elif kind == "combo_ocr":
                    items = ocr_material_items   # 任务素材库的 OCR 识别素材
                if items is not None:
                    w = node.get_widget(p["name"])
                    if w is not None:
                        try:
                            if kind in ("combo_scene", "combo_point",
                                        "combo_ocr_region", "combo_element",
                                        "combo_signal", "combo_ocr"):
                                # 自绘控件：优先 property，其次任务参数
                                # （加载任务时下拉为空，set_value 无法回填，
                                #   必须记住任务 JSON 里的原值，重填后恢复选中）
                                cur = ((node.properties() or {})
                                       .get("custom") or {}).get(p["name"], "")
                                if not cur:
                                    cur = (getattr(node, "_task_params", {})
                                           or {}).get(p["name"], "")
                            else:
                                cur = w.get_value()   # 保留已选值（重填不丢失）
                            w.set_value(list(items))
                            if cur and cur in items:
                                w.set_value(cur)
                        except Exception:
                            pass

    # ── 通用节点保存回调 ───────────────────────────
    def set_save_compound_cb(self, cb) -> None:
        self._save_compound_cb = cb
