"""截取真实画布节点区域 PNG，查看内嵌控件对齐效果。"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QRectF
from PyQt5.QtGui import QImage, QPainter

app = QApplication(sys.argv)
from ui.visual_builder.graph_canvas import GraphCanvas

c = GraphCanvas()
c.resize(900, 600)
c.show()
node = c.add_node("clicker")
node.set_selected(False)
app.processEvents()

view = c._graph.viewer()
scene = view.scene()
node_rect = node.view.sceneBoundingRect()
pad = 30
r = node_rect.adjusted(-pad, -pad, pad, pad)
img = QImage(int(r.width()), int(r.height()), QImage.Format_ARGB32)
img.fill(0x00000000)
p = QPainter(img)
scene.render(p, QRectF(img.rect()), r)
p.end()
out = Path(__file__).parent / "shot_align.png"
img.save(str(out))
print("saved:", out)
