"""验证：右侧「通用节点」Tab —— 列出已做好的操作，点击/双击添加 operation 节点。"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

app = QApplication(sys.argv)
from visual.rule_store import VisualTaskStore
from visual.operation_store import OperationStore
from ui.param_bridge.visual_bridge import VisualBridge
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
from ui.visual_builder.graph_canvas import GraphCanvas

tmp = Path(tempfile.mkdtemp(prefix="op_tab_"))
store = VisualTaskStore(tmp / "vt")
op_store = OperationStore([tmp / "shared", tmp / "ops"])
bridge = VisualBridge(store=store, assets_dir=str(tmp), operation_store=op_store)

print("[1] 创建两个通用操作（御魂调整 / 阵容选择）")
op1 = op_store.create("soul_configure", "御魂调整")
op1["graph"] = {"nodes": [], "connections": []}
op1["inputs"] = [{"name": "group", "type": "text", "hoist": True,
                  "label": "御魂组", "default": "御魂副本"}]
op_store.save(op1)
op2 = op_store.create("select_team", "阵容选择")
op2["graph"] = {"nodes": [], "connections": []}
op2["inputs"] = [{"name": "team", "type": "text", "hoist": True,
                  "label": "队伍", "default": "主力"}]
op_store.save(op2)
print("  操作列表:", op_store.names())
assert sorted(op_store.names()) == ["select_team", "soul_configure"]

print("[2] 节点库「通用节点」Tab 列出操作")
bridge.create_task("刷御魂", "刷御魂", "daily")
panel = VisualBuilderPanel(visual_bridge=bridge)
assert panel.open_visual("yys", "task", "刷御魂", store)
c = panel._canvas
tabs = [c._side_tabs.tabText(i) for i in range(c._side_tabs.count())]
print("  右侧 Tab:", tabs)
assert "基础节点" in tabs and "通用节点" in tabs
op_list_items = [c._op_list.item(i).data(Qt.UserRole)
                 for i in range(c._op_list.count())]
print("  通用节点列表:", op_list_items)
assert sorted(op_list_items) == ["select_team", "soul_configure"]

print("[3] 双击列表项 → 画布添加 operation 节点且已选中该操作")
before = len(c._graph.all_nodes())
node = c.add_operation_node("soul_configure")
assert node is not None
w = node.get_widget("operation")
print("  添加后节点数:", len(c._graph.all_nodes()),
      "| 操作参数:", w.get_value())
assert w.get_value() == "soul_configure"
assert len(c._graph.all_nodes()) == before + 1

print("[4] 导出验证")
task = c.export_task(panel._current_task)
op_nodes = [n for n in task["graph"]["nodes"] if n["type"] == "operation"]
print("  导出 operation 节点:", [(n["name"], n["params"].get("operation"))
                              for n in op_nodes])
assert len(op_nodes) == 1
assert op_nodes[0]["params"].get("operation") == "soul_configure"

print("[5] 空状态：无操作时列表显示提示")
tmp2 = Path(tempfile.mkdtemp(prefix="op_tab2_"))
store2 = VisualTaskStore(tmp2 / "vt")
op_store2 = OperationStore([tmp2 / "ops"])
bridge2 = VisualBridge(store=store2, assets_dir=str(tmp2),
                       operation_store=op_store2)
c2 = GraphCanvas(
    operation_list_provider=bridge2.operation_list,
    operation_create=None,
)
print("  空列表项:", c2._op_list.item(0).text() if c2._op_list.count() else "无")
assert c2._op_list.count() >= 1

print("\n🎉 通用节点 Tab 验证通过")
