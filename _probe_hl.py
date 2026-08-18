
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"d:\yys\新程序\主程序")
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from ui.visual_builder.graph_canvas import GraphCanvas
c = GraphCanvas()
t = {"name": "t1", "game": "yys", "kind": "task", "nodes": [
    {"id": "n1", "type": "scene_probe", "name": "场景判定", "params": {}, "pos": [0, 0]}], "edges": []}
c.load_task(t)
print("map:", list(c._task_to_node.keys()), flush=True)
node = c._node_by_id("n1")
print("node:", node is not None, flush=True)
try:
    c.highlight_node("n1")
    print("hl_id:", c._hl_node_id, "orig:", c._hl_orig_color, flush=True)
except Exception as e:
    print("ERR", repr(e), flush=True)
