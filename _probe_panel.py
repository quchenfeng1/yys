
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"d:\yys\新程序\主程序")
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
print("imported", flush=True)
p = VisualBuilderPanel(None)
print("panel none ok, tabs=", p._right_tabs.count(), flush=True)
