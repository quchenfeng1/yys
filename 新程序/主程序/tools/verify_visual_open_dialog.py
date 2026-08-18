"""验证：打开任务弹窗（游戏任务列表 / 打开返回）+ 面板 open_visual + 封装保存。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

app = QApplication(sys.argv)
from core.game_profile import GameProfile
from visual.rule_store import VisualTaskStore
from ui.param_bridge.visual_bridge import VisualBridge
from ui.visual_builder.open_task_dialog import OpenTaskDialog
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel

# 构造临时游戏结构 games/yys/
tmp = Path(tempfile.mkdtemp(prefix="open_dlg_"))
gdir = tmp / "games" / "yys"
gdir.mkdir(parents=True)
(gdir / "profile.yaml").write_text("game_id: yys\nname: 阴阳师\n",
                                   encoding="utf-8")

# 造数据
tstore = VisualTaskStore(gdir / "visual_tasks")
tstore.create("farm_soul", "刷御魂", "daily")
tstore.create("explore", "探索", "daily")

profile = GameProfile(root=tmp, game_id="yys")

print("[1] 弹窗：单游戏任务列表（通用操作 Tab 已移除）")
dlg = OpenTaskDialog(profile, "yys")
assert not hasattr(dlg, "_game_list"), "游戏列表应已移除"
assert not hasattr(dlg, "_tabs"), "通用操作 Tab 应已移除"
assert dlg.current_kind() == "task"

print("[2] 游戏任务列表")
task_names = [dlg._task_list.item(i).data(Qt.UserRole)
              for i in range(dlg._task_list.count())]
print("  游戏任务:", task_names)
assert sorted(task_names) == ["explore", "farm_soul"]

print("[3] 打开返回 (game, kind, name)")
dlg._task_list.setCurrentRow(0)
dlg._open()
sel = dlg.selected()
print("  选中:", sel)
assert sel[0] == "yys" and sel[1] == "task" and sel[2] in task_names

print("[4] 面板打开任务到画布 + 保存往返")
store_bridge = VisualTaskStore(tmp / "vt2")
bridge = VisualBridge(store=store_bridge, assets_dir=str(tmp))
panel = VisualBuilderPanel(visual_bridge=bridge)
ok = panel.open_visual("yys", "task", "farm_soul", tstore)
print("  打开任务:", ok, "| 标签:", panel._open_label.text())
assert ok
assert panel._open_key == {"game": "yys", "kind": "task",
                           "name": "farm_soul"}
assert "游戏任务" in panel._open_label.text()
node = panel._canvas.add_node("clicker")
assert node is not None
from unittest.mock import patch
with patch("PyQt5.QtWidgets.QMessageBox.information", return_value=None):
    panel._save()
reloaded = tstore.load("farm_soul")
print("  保存后节点数:", len(reloaded["graph"]["nodes"]))
assert len(reloaded["graph"]["nodes"]) >= 2

print("[5] 框选封装 → 复合节点")
# 新建干净任务：start → clicker → end，封装 clicker
tstore.create("encap_test", "封装测试", "daily")
panel.open_visual("yys", "task", "encap_test", tstore)
c = panel._canvas
start = c._graph.all_nodes()[0]
clicker = c.add_node("clicker")
end = c.add_node("end")
start.get_output("out").connect_to(clicker.get_input("in"))
clicker.get_output("out").connect_to(end.get_input("in"))
c._graph.clear_selection()
clicker.set_selected(True)
app.processEvents()
cid = c.encapsulate_selected()
print("  封装结果:", cid)
assert cid is not None
types = [n.type_.split(".")[-1] for n in c._graph.all_nodes()]
print("  封装后节点:", types)
assert "compound" in types
# 导出校验：compound 带 subgraph，且外部连线重接
task = c.export_task(c._task)
comp = next(n for n in task["graph"]["nodes"] if n["type"] == "compound")
assert comp.get("subgraph") and comp["subgraph"]["nodes"]
assert len(task["graph"]["connections"]) == 2

print("\n🎉 打开任务弹窗 + 封装验证通过")
