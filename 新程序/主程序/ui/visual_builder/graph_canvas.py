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
from typing import Any, Callable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPushButton, QSplitter, QTabWidget,
                             QVBoxLayout, QWidget)

from NodeGraphQt import BaseNode, NodeGraph

from ui.visual_builder.pan_viewer import PanNodeViewer
from visual import visual_schema as vs
from visual.node_defs import NODE_DEFS

NODE_IDENTIFIER = "visual.nodes"


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

    # 输入控件统一深色样式（直接设置在控件上，覆盖 NodeLineEdit/SpinBox/CheckBox
    # 自带的半透明浅色 QSS —— 控件自身 QSS 优先于 group 继承的）
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
    """

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
        INPUT_W = 150

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
        node.add_combo_menu(name, label, items=list(p.get("options", [])))
    elif kind in ("combo_scene", "combo_point", "combo_element",
                  "combo_ocr_region", "combo_operation"):
        node.add_combo_menu(name, label, items=[])   # 动态填充
    elif kind == "spinbox":
        node.add_spinbox(name, label,
                         value=p.get("default", 0),
                         min_value=p.get("min", 0),
                         max_value=p.get("max", 100))
    elif kind == "text":
        node.add_text_input(name, label, text=str(p.get("default", "")))
    elif kind == "checkbox":
        node.add_checkbox(name, label, state=bool(p.get("default", False)))


def _build_node_class(node_type: str) -> type:
    """动态生成 BaseNode 子类（类名 = 节点类型 → type_ = visual.nodes.{type}）"""
    d = NODE_DEFS[node_type]

    def __init__(self):
        BaseNode.__init__(self)
        for inp in d.get("inputs", []):
            self.add_input(inp["name"], color=_port_color(inp.get("port_type", "control")))
        for out in d.get("outputs", []):
            self.add_output(out["name"], color=_port_color(out.get("port_type", "control")))
        for p in d.get("params", []):
            _add_param_widget(self, p)

    return type(node_type, (BaseNode,), {
        "__identifier__": NODE_IDENTIFIER,
        "NODE_NAME": d.get("label", node_type),  # 节点库显示名（中文），类型识别用 type_
        "__init__": __init__,
    })


def _apply_params(node, params: dict) -> None:
    """把 JSON 参数填入节点（widget 优先，fallback set_property；
    backdrop 等 NodeObject 无 get_widget 时走 set_property）"""
    has_widget = hasattr(node, "get_widget")
    for name, value in (params or {}).items():
        if has_widget:
            w = node.get_widget(name)
            if w is not None:
                try:
                    w.set_value(value)
                    continue
                except Exception:
                    pass
        try:
            node.set_property(name, value)
        except Exception:
            pass


class GraphCanvas(QWidget):
    """节点画布（编辑视图）"""

    def __init__(self, element_provider: Callable[[], list[str]] | None = None,
                 operation_provider: Callable[[], list[str]] | None = None,
                 operation_loader: Callable[[str], dict | None] | None = None,
                 scene_provider: Callable[[], list[str]] | None = None,
                 point_provider: Callable[[], list[str]] | None = None,
                 ocr_provider: Callable[[], list[str]] | None = None,
                 operation_list_provider: Callable[[], list[dict]] | None = None,
                 operation_create: Callable[[], dict | None] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._element_provider = element_provider  # 素材元素下拉源
        self._operation_provider = operation_provider  # 通用操作下拉源（4.26）
        self._operation_loader = operation_loader      # 操作定义加载器
        self._scene_provider = scene_provider          # 示教场景下拉源（实时）
        self._point_provider = point_provider          # 示教点击点下拉源（实时）
        self._ocr_provider = ocr_provider              # OCR 区域下拉源（实时）
        self._operation_list_provider = operation_list_provider  # 通用节点列表源
        self._operation_create = operation_create      # 新建通用操作回调
        self._task: dict = {}

        # 节点参数控件：label 左 / 输入右（水平布局）
        _patch_horizontal_node_widgets()

        self._graph = NodeGraph(viewer=PanNodeViewer())  # 左键拖空白平移
        self._node_classes: dict[str, type] = {}
        self._register_all()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # 顶部：节点库添加
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("节点库:"))
        self._type_combo = QComboBox()
        for t, d in NODE_DEFS.items():
            self._type_combo.addItem(f"[{d['category']}] {d['label']}", t)
        self._type_combo.setMinimumWidth(180)
        toolbar.addWidget(self._type_combo)
        self._add_btn = QPushButton("＋ 添加节点")
        self._add_btn.clicked.connect(self._on_add_node)
        toolbar.addWidget(self._add_btn)
        self._del_node_btn = QPushButton("🗑 删除选中节点")
        self._del_node_btn.clicked.connect(self.delete_selected)
        toolbar.addWidget(self._del_node_btn)
        self._del_pipe_btn = QPushButton("✂ 删除选中连线")
        self._del_pipe_btn.clicked.connect(self.delete_selected_pipes)
        toolbar.addWidget(self._del_pipe_btn)
        self._undo_btn = QPushButton("↩ 撤销")
        self._undo_btn.clicked.connect(self._graph._undo_stack.undo)
        toolbar.addWidget(self._undo_btn)
        self._redo_btn = QPushButton("↪ 重做")
        self._redo_btn.clicked.connect(self._graph._undo_stack.redo)
        toolbar.addWidget(self._redo_btn)
        toolbar.addStretch(1)
        self._refresh_btn = QPushButton("↻ 刷新下拉")
        self._refresh_btn.clicked.connect(self.refresh_combos)
        toolbar.addWidget(self._refresh_btn)
        lay.addLayout(toolbar)

        # NodeGraphQt 视图（键盘 Delete 删除选中）
        self._viewer = self._graph.widget
        self._viewer.installEventFilter(self)

        # 右侧：节点库（基础节点 + 通用节点）
        # （属性面板 PropertiesBinWidget 已移除：它只显示底层 model 属性，
        #   对我们的自定义节点无实际作用——节点参数已内嵌在节点本体直接编辑）
        from NodeGraphQt import NodesPaletteWidget
        self._palette = NodesPaletteWidget(node_graph=self._graph)
        self._palette.setWindowTitle("节点库")
        # 只有 visual.nodes 一个分组时，隐藏内部 Tab 栏（去掉嵌套的 visual 子 Tab，
        # 节点直接显示在「基础节点」下一层），保留拖放/双击功能
        try:
            self._palette._tab_widget.setTabBarAutoHide(True)
        except Exception:
            pass

        # 通用节点 Tab（所选游戏的通用操作列表，双击添加）
        op_widget = QWidget()
        op_lay = QVBoxLayout(op_widget)
        op_lay.setContentsMargins(2, 2, 2, 2)
        op_lay.setSpacing(3)
        self._op_list = QListWidget()
        self._op_list.setToolTip("双击添加通用操作到画布")
        self._op_list.itemDoubleClicked.connect(self._on_op_list_double_clicked)
        op_lay.addWidget(self._op_list, 1)

        # 节点分类 Tab
        self._side_tabs = QTabWidget()
        self._side_tabs.addTab(self._palette, "基础节点")
        self._side_tabs.addTab(op_widget, "通用节点")

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

        self.refresh_operation_list()

    # ── 节点注册 ──────────────────────────────────────────
    def _register_all(self) -> None:
        # NodeGraphQt 默认注册了内置 Backdrop（分组注释框），与任务语义无关且
        # 曾导致双击崩溃 —— 从工厂移除，节点库不再显示
        try:
            f = self._graph.node_factory
            f.nodes.pop("nodeGraphQt.nodes.BackdropNode", None)
            f.names.pop("Backdrop", None)
            f.aliases.pop("Backdrop", None)
        except Exception:
            pass
        for t in NODE_DEFS:
            cls = _build_node_class(t)
            self._node_classes[t] = cls
            self._graph.register_node(cls)

    def _node_type_path(self, node_type: str) -> str:
        """节点类型 → NodeGraphQt 类型路径"""
        return f"{NODE_IDENTIFIER}.{node_type}"

    # ── 任务加载 / 导出 ───────────────────────────────────
    def load_task(self, task: dict) -> None:
        """任务 JSON → 画布"""
        self._task = vs.normalize_task(task)
        self._graph.clear_session()
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
                node_map[n["id"]] = node
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
        self.refresh_combos()

    def export_task(self, task: dict) -> dict:
        """画布 → 任务 JSON（节点/连线/参数/位置）"""
        task = vs.normalize_task(task)
        nodes: list[dict] = []
        for node in self._graph.all_nodes():
            custom = node.properties().get("custom", {}) or {}
            nodes.append({
                "id": node.id,
                "type": node.type_.split(".")[-1],
                "name": node.name(),
                "pos": list(node.pos()),
                "params": dict(custom),
            })
        conns: list[dict] = []
        for out_port, in_port in self._iter_connections(self._graph):
            conns.append({
                "id": uuid.uuid4().hex[:12],
                "out_node": out_port.node().id,
                "out_port": out_port.name(),
                "in_node": in_port.node().id,
                "in_port": in_port.name(),
            })
        task["graph"]["nodes"] = nodes
        task["graph"]["connections"] = conns
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
    def _on_add_node(self) -> None:
        ntype = self._type_combo.currentData()
        if not ntype:
            return
        self.add_node(ntype)

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
            return node
        except Exception:
            return None

    # ── 通用节点（已做好的通用操作，4.26）────────────────
    def refresh_operation_list(self) -> None:
        """刷新右侧「通用节点」Tab 的操作列表"""
        self._op_list.clear()
        items: list[dict] = []
        if self._operation_list_provider is not None:
            try:
                items = list(self._operation_list_provider() or [])
            except Exception:
                items = []
        for op in items:
            name = op.get("name", "")
            display = op.get("display_name", name)
            item = QListWidgetItem(f"{display}（{name}）")
            item.setData(Qt.UserRole, name)
            item.setToolTip(
                f"节点数:{op.get('node_count', 0)}  输入参数:{op.get('input_count', 0)}")
            self._op_list.addItem(item)
        if not items:
            it = QListWidgetItem("（暂无通用操作 — 点击「＋ 新建」创建）")
            it.setFlags(Qt.NoItemFlags)
            self._op_list.addItem(it)
            self._op_list.setEnabled(False)
        else:
            self._op_list.setEnabled(True)

    def add_operation_node(self, op_name: str):
        """在画布添加一个 operation 节点并选中该通用操作"""
        node = self.add_node("operation")
        if node is None:
            return None
        w = node.get_widget("operation")
        if w is not None:
            try:
                names = list(self._operation_provider() or []) \
                    if self._operation_provider else []
                if names:
                    w.set_value(list(names))
                w.set_value(op_name)
            except Exception:
                pass
        try:
            self._graph.center_on(node.id)
        except Exception:
            pass
        return node

    def _on_op_list_double_clicked(self, item) -> None:
        name = item.data(Qt.UserRole)
        if name:
            self.add_operation_node(name)

    # ── 删除 ──────────────────────────────────────────────
    def selected_nodes(self) -> list:
        """当前选中的节点列表"""
        return self._graph.selected_nodes()

    def delete_selected(self) -> int:
        """删除选中的节点（及其连线）与选中的连线；返回删除节点数"""
        # 先断开选中的连线（选中 pipe）
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
        operation_items = []
        if self._operation_provider is not None:
            try:
                operation_items = list(self._operation_provider() or [])
            except Exception:
                operation_items = []

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
                    items = element_items
                elif kind == "combo_operation":
                    items = operation_items
                if items is not None:
                    w = node.get_widget(p["name"])
                    if w is not None:
                        try:
                            w.set_value(list(items))
                        except Exception:
                            pass

    # ── 操作参数辅助（4.27）─────────────────────────────
    def load_operation(self, name: str) -> dict | None:
        """加载通用操作定义（供参数上浮收集）"""
        if self._operation_loader is not None:
            try:
                return self._operation_loader(name)
            except Exception:
                return None
        return None

    def operation_node_names(self) -> list[tuple[str, str]]:
        """图中所有操作节点 → [(node_id, op_name)]"""
        out = []
        for node in self._graph.all_nodes():
            ntype = node.type_.split(".")[-1]
            if ntype == "operation":
                w = node.get_widget("operation")
                out.append((node.id, w.value() if w else ""))
        return out
