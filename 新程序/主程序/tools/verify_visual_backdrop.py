"""验证：Backdrop 标签体系（2026-08-16 改写）。

- 内置 BackdropNode 已重新注册（标签框由右键创建）
- 节点库不显示 backdrop 分组（不可拖放）
- add_node('backdrop') 返回 None（不进任务节点体系）
- 旧任务 JSON（含 type=backdrop 的节点）加载不崩、被跳过
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

app = QApplication(sys.argv)
from visual.rule_store import VisualTaskStore
from ui.param_bridge.visual_bridge import VisualBridge
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
from ui.visual_builder.graph_canvas import GraphCanvas

print("[1] 基础节点单层显示（无嵌套 visual 子 Tab）；backdrop 已注册但不进节点库")
c = GraphCanvas()
ptabs = [c._palette._tab_widget.tabText(i)
         for i in range(c._palette._tab_widget.count())]
print("  palette 内部分组:", ptabs)
assert len(ptabs) == 1, f"应有 1 个分组（visual.nodes）: {ptabs}"
assert c._palette._tab_widget.tabBar().isVisible() is False, \
    "单分组时内部 Tab 栏应自动隐藏"
f = c._graph.node_factory
assert "nodeGraphQt.nodes.BackdropNode" in f.nodes, \
    "BackdropNode 应已注册（标签体系）"
print("  ✅ 单层显示 + backdrop 已注册（标签由右键创建，节点库无入口）")

print("[2] add_node('backdrop') 返回 None")
assert c.add_node("backdrop") is None
print("  ✅ 无法通过 add_node 添加 backdrop")

print("[3] 旧任务 JSON（含 backdrop）加载不崩、backdrop 被跳过")
tmp = Path(tempfile.mkdtemp(prefix="bd_rm_"))
store = VisualTaskStore(tmp)
bridge = VisualBridge(store=store, assets_dir=str(tmp))
bridge.create_task("旧任务", "旧任务", "daily")
old = store.load("旧任务")
old["graph"]["nodes"].append({
    "id": "bd1", "type": "backdrop", "name": "注释",
    "pos": [0, 0], "params": {"backdrop_text": "x", "width": 200, "height": 200},
})
store.save(old)
panel = VisualBuilderPanel(visual_bridge=bridge)
assert panel.open_visual("yys", "task", "旧任务", store)
print("  加载后节点数:", len(panel._canvas._graph.all_nodes()))
assert len(panel._canvas._graph.all_nodes()) == 1  # 仅 start，backdrop 被跳过
print("  ✅ 含 backdrop 的旧任务加载安全（backdrop 被忽略）")

print("\n🎉 Backdrop 标签体系验证通过")
