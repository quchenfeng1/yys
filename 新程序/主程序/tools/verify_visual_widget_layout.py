"""验证：节点参数控件水平布局（label 左 / 输入右）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QComboBox

app = QApplication(sys.argv)
from ui.visual_builder.graph_canvas import GraphCanvas

c = GraphCanvas()
c.resize(900, 600)
c.show()

print("[1] 添加 clicker 节点，检查参数控件布局")
n = c.add_node("clicker")
w = n.get_widget("template")   # NodeComboBox（操作识别素材）
group = w.widget()
lay = group.layout()
print("  布局:", type(lay).__name__)
assert isinstance(lay, QHBoxLayout), "应为水平布局"
item0 = lay.itemAt(0).widget()
item1 = lay.itemAt(1).widget()
print("  左侧:", type(item0).__name__, "| 右侧:", type(item1).__name__)
assert isinstance(item0, QLabel), "左侧应为 label"
assert isinstance(item1, QComboBox), "右侧应为输入控件"
assert item0.text() == "操作识别素材"
print("  ✅ label 在左、输入在右")

print("[2] 水平布局下参数仍可读写/导出")
w.set_value(list(["visual/t1/a.png", "visual/t1/b.png"]))
w.set_value("visual/t1/a.png")
task = c.export_task({"graph": {"nodes": [], "connections": []}, "teach": {}})
clicker = next(x for x in task["graph"]["nodes"] if x["type"] == "clicker")
print("  导出 template:", clicker["params"].get("template"))
assert clicker["params"].get("template") == "visual/t1/a.png"
print("  ✅ 参数导出正常")

print("[3] 其他 widget 类型同样水平（spinbox/text/checkbox）")
n2 = c.add_node("dragger")
w2 = n2.get_widget("duration_ms")  # spinbox
assert isinstance(w2.widget().layout(), QHBoxLayout)
w3 = n2.get_widget("direction")  # combo
assert isinstance(w3.widget().layout(), QHBoxLayout)
n4 = c.add_node("dragger")
w4 = n4.get_widget("distance")  # float
assert isinstance(w4.widget().layout(), QHBoxLayout)
print("  ✅ 全部水平布局")

print("\n🎉 节点参数水平布局验证通过")
