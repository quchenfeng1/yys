
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"d:\yys\新程序\主程序")
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from ui.visual_builder.graph_canvas import GraphCanvas
c1 = GraphCanvas()
print("c1 ok", flush=True)
c2 = GraphCanvas()
print("c2 ok", flush=True)
