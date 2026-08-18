"""
17-可视化构建模块：PanNodeViewer（画布平移增强）。

NodeGraphQt 原生平移需中键或 Alt+左键（不直观）。本子类支持：
- **左键拖空白处 = 平移画布**（ComfyUI 风格，最常用）
- 保留原生：中键平移、Alt+左键平移、节点拖动、连线、双击属性
- 空白处左键不再框选（平移优先；框选用途较少，必要时可中键/Alt 平移+Shift 选择）
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QMenu
from NodeGraphQt.qgraphics.node_abstract import AbstractNodeItem
from NodeGraphQt.qgraphics.pipe import PipeItem
from NodeGraphQt.qgraphics.port import PortItem
from NodeGraphQt.widgets.viewer import NodeViewer

# 判定为"画布内容"的 item 类型（命中则不进入平移）
_CONTENT_TYPES = (AbstractNodeItem, PipeItem, PortItem)


class PanNodeViewer(NodeViewer):
    """左键拖空白处平移画布 + 右键节点/连线弹出删除菜单"""

    node_context_action = pyqtSignal(str, object)  # (action, item) 供 GraphCanvas 处理
    # 通用节点拖放到画布（2026-08-16）：(name, 场景坐标 QPointF)
    compound_dropped = pyqtSignal(str, object)

    def __init__(self, parent=None, undo_stack=None):
        super().__init__(parent, undo_stack)
        self._lmb_pan_active = False
        self._lmb_pan_origin = None
        # 标签阶段状态查询（graph_canvas 注入：item → 是否已设为阶段）
        self.stage_checker = None
        self.setAcceptDrops(True)

    def dropEvent(self, event):
        """通用节点拖入画布 → compound_dropped(name, 场景坐标)"""
        md = event.mimeData()
        if md is not None and md.hasFormat("application/x-yys-compound"):
            try:
                name = bytes(md.data("application/x-yys-compound")).decode("utf-8")
            except Exception:
                name = ""
            if name:
                self.compound_dropped.emit(name, self.mapToScene(event.pos()))
                event.accept()
                return
        super().dropEvent(event)

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md is not None and md.hasFormat("application/x-yys-compound"):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def contextMenuEvent(self, event):
        """右键：命中节点/连线/标签框 → 弹对应菜单；空白处不弹菜单（2026-08-16）。"""
        map_pos = self.mapToScene(event.pos())
        items = self._items_near(map_pos, None, 10, 10)
        node_item = next((i for i in items if isinstance(i, AbstractNodeItem)), None)
        pipe_item = None if node_item is not None else \
            next((i for i in items if isinstance(i, PipeItem)), None)
        if node_item is None and pipe_item is None:
            return   # 空白右键：无菜单（封装标签已移至顶部工具栏按钮）
        menu = QMenu(self)
        if node_item is not None:
            ntype = node_item.type_.split(".")[-1] if hasattr(node_item, "type_") else ""
            if ntype == "BackdropNode":
                # 标签框内部右键（2026-08-16）：重命名 / 设为阶段 / 保存通用节点 / 删除
                act = menu.addAction("✏ 重命名标签")
                act.triggered.connect(
                    lambda: self.node_context_action.emit("tag_rename", node_item))
                # 阶段状态可区分：已设为阶段 → 「取消阶段」，且标签呈浅绿色
                is_stage = False
                if self.stage_checker is not None:
                    try:
                        is_stage = bool(self.stage_checker(node_item))
                    except Exception:
                        is_stage = False
                act = menu.addAction("⭐ 取消阶段" if is_stage else "⭐ 设为阶段")
                act.triggered.connect(
                    lambda: self.node_context_action.emit("tag_set_stage", node_item))
                act = menu.addAction("💾 保存为通用节点")
                act.triggered.connect(
                    lambda: self.node_context_action.emit("tag_save_compound", node_item))
                menu.addSeparator()
                act = menu.addAction("🗑 删除标签")
                act.triggered.connect(
                    lambda: self.node_context_action.emit("tag_delete", node_item))
                menu.exec_(event.globalPos())
                return
            # 场景判定节点显示示教项（其它节点不放）
            if ntype in ("scene_probe", "ocr_reader"):
                act = menu.addAction("🎓 示教")
                act.triggered.connect(
                    lambda: self.node_context_action.emit("teach_node", node_item))
                menu.addSeparator()
            if ntype == "compound":
                act = menu.addAction("💾 保存为节点组合")
                act.triggered.connect(
                    lambda: self.node_context_action.emit("save_compound", node_item))
                menu.addSeparator()
            # 进度组（2026-08-16）：把当前选中节点保存为一个进度点（o）
            act = menu.addAction("⭕ 保存为进度节点")
            act.triggered.connect(
                lambda: self.node_context_action.emit("save_progress", node_item))
            menu.addSeparator()
            act = menu.addAction("🗑 删除节点")
            act.triggered.connect(
                lambda: self.node_context_action.emit("delete_node", node_item))
        else:
            act = menu.addAction("🗑 删除连线")
            act.triggered.connect(
                lambda: self.node_context_action.emit("delete_pipe", pipe_item))
        menu.exec_(event.globalPos())

    def mousePressEvent(self, event):
        # 左键 + 未按住 Alt + 空白处（无节点/端口/连线）→ 平移画布
        if (event.button() == Qt.LeftButton and not self.ALT_state
                and not self.SHIFT_state):
            map_pos = self.mapToScene(event.pos())
            items = self._items_near(map_pos, None, 20, 20)
            has_content = any(isinstance(itm, _CONTENT_TYPES) for itm in items)
            if not has_content:
                self._lmb_pan_active = True
                self._lmb_pan_origin = event.pos()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._lmb_pan_active:
            if self._lmb_pan_origin is not None:
                previous = self.mapToScene(self._lmb_pan_origin)
                current = self.mapToScene(event.pos())
                delta = previous - current
                self._set_viewer_pan(delta.x(), delta.y())
                self._lmb_pan_origin = event.pos()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._lmb_pan_active:
            # 空白单击（无拖动）→ 取消所有节点选中；有拖动 = 平移
            if self._lmb_pan_origin is not None:
                moved = (abs(event.pos().x() - self._lmb_pan_origin.x())
                         + abs(event.pos().y() - self._lmb_pan_origin.y()))
                if moved < 4:
                    try:
                        for n in self.selected_nodes():
                            n.setSelected(False)
                    except Exception:
                        pass
            self._lmb_pan_active = False
            self._lmb_pan_origin = None
            return
        super().mouseReleaseEvent(event)
