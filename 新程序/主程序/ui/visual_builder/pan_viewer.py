"""
17-可视化构建模块：PanNodeViewer（画布平移增强）。

NodeGraphQt 原生平移需中键或 Alt+左键（不直观）。本子类支持：
- **左键拖空白处 = 平移画布**（ComfyUI 风格，最常用）
- 保留原生：中键平移、Alt+左键平移、节点拖动、连线、双击属性
- 空白处左键不再框选（平移优先；框选用途较少，必要时可中键/Alt 平移+Shift 选择）
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from NodeGraphQt.qgraphics.node_abstract import AbstractNodeItem
from NodeGraphQt.qgraphics.pipe import PipeItem
from NodeGraphQt.qgraphics.port import PortItem
from NodeGraphQt.widgets.viewer import NodeViewer

# 判定为"画布内容"的 item 类型（命中则不进入平移）
_CONTENT_TYPES = (AbstractNodeItem, PipeItem, PortItem)


class PanNodeViewer(NodeViewer):
    """左键拖空白处平移画布"""

    def __init__(self, parent=None, undo_stack=None):
        super().__init__(parent, undo_stack)
        self._lmb_pan_active = False
        self._lmb_pan_origin = None

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
            self._lmb_pan_active = False
            self._lmb_pan_origin = None
            return
        super().mouseReleaseEvent(event)
