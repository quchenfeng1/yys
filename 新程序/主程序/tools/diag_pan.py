"""诊断：PanNodeViewer 左键空白平移 + 节点拖动 + 中键平移。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt5.QtGui import QMouseEvent

app = QApplication(sys.argv)
from ui.visual_builder.graph_canvas import GraphCanvas


def _events(view, p, m, r):
    QApplication.sendEvent(view.viewport(), p)
    QApplication.sendEvent(view.viewport(), m)
    QApplication.sendEvent(view.viewport(), r)
    app.processEvents()


def pan_center(view):
    return view.mapToScene(view.viewport().rect().center())


print("[1] GraphCanvas 左键空白平移")
c = GraphCanvas()
c.resize(800, 600)
c.show()
app.processEvents()
view = c._graph.viewer()
init = pan_center(view)
# 空白处（无节点）左键拖动
p = QMouseEvent(QEvent.MouseButtonPress, QPoint(400, 300), Qt.LeftButton,
                Qt.LeftButton, Qt.NoModifier)
m = QMouseEvent(QEvent.MouseMove, QPoint(300, 250), Qt.NoButton,
                Qt.LeftButton, Qt.NoModifier)
r = QMouseEvent(QEvent.MouseButtonRelease, QPoint(300, 250), Qt.LeftButton,
                Qt.NoButton, Qt.NoModifier)
_events(view, p, m, r)
after = pan_center(view)
moved = not (init == after)
print(f"  左键空白拖动: {'OK 可平移' if moved else 'X 未平移'} "
      f"(delta={after.x()-init.x():.0f},{after.y()-init.y():.0f})")
assert moved, "左键空白平移失败"

print("[2] 中键平移仍可用")
init2 = pan_center(view)
p2 = QMouseEvent(QEvent.MouseButtonPress, QPoint(400, 300), Qt.MiddleButton,
                 Qt.MiddleButton, Qt.NoModifier)
m2 = QMouseEvent(QEvent.MouseMove, QPoint(320, 280), Qt.NoButton,
                 Qt.MiddleButton, Qt.NoModifier)
r2 = QMouseEvent(QEvent.MouseButtonRelease, QPoint(320, 280), Qt.MiddleButton,
                 Qt.NoButton, Qt.NoModifier)
_events(view, p2, m2, r2)
after2 = pan_center(view)
print(f"  中键拖动: {'OK 可平移' if not (init2 == after2) else 'X 未平移'}")
assert not (init2 == after2), "中键平移失效"

print("[3] 节点拖动（按节点左键拖）")
c2 = GraphCanvas()
c2.resize(800, 600)
c2.show()
node = c2.add_node("clicker")
app.processEvents()
view2 = c2._graph.viewer()
sp = node.pos()
vp = view2.mapFromScene(sp[0], sp[1])
# 按住节点拖动（节点中心命中）
pn = QMouseEvent(QEvent.MouseButtonPress, vp, Qt.LeftButton, Qt.LeftButton,
                 Qt.NoModifier)
mn = QMouseEvent(QEvent.MouseMove, vp + QPoint(60, 40), Qt.NoButton,
                 Qt.LeftButton, Qt.NoModifier)
rn = QMouseEvent(QEvent.MouseButtonRelease, vp + QPoint(60, 40), Qt.LeftButton,
                 Qt.NoButton, Qt.NoModifier)
_events(view2, pn, mn, rn)
new_sp = node.pos()
node_moved = (new_sp[0] - sp[0]) ** 2 + (new_sp[1] - sp[1]) ** 2 > 1
print(f"  节点拖动: {'OK 可拖动' if node_moved else 'X 未移动'} "
      f"(from {sp} to {new_sp})")

print("\n✅ 画布平移诊断完成")
