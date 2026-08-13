"""验证：顶部游戏下拉 —— 通用节点列表/操作下拉按所选游戏切换。"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

app = QApplication(sys.argv)
from core.game_profile import GameProfile
from visual.rule_store import VisualTaskStore
from visual.operation_store import OperationStore
from ui.param_bridge.visual_bridge import VisualBridge
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel

# 构造两个游戏：yys（阴阳师）+ demo（演示游戏），各带不同操作
tmp = Path(tempfile.mkdtemp(prefix="game_switch_"))
for gid, gname in [("yys", "阴阳师"), ("demo", "演示游戏")]:
    gdir = tmp / "games" / gid
    gdir.mkdir(parents=True)
    (gdir / "profile.yaml").write_text(
        f"game_id: {gid}\nname: {gname}\n", encoding="utf-8")
# 共享操作 + 各游戏内操作
shared = tmp / "games" / "_shared" / "operations"
shared.mkdir(parents=True)
sop = OperationStore([shared]).create("restart_game", "重启游戏")
OperationStore([shared]).save(sop)
op_yys = OperationStore([tmp / "games" / "yys" / "operations"])
o1 = op_yys.create("soul_configure", "御魂调整")
op_yys.save(o1)
op_demo = OperationStore([tmp / "games" / "demo" / "operations"])
o2 = op_demo.create("demo_action", "演示动作")
op_demo.save(o2)

profile = GameProfile(root=tmp, game_id="yys")
store = VisualTaskStore(tmp / "vt")
bridge = VisualBridge(store=store, game_profile=profile, assets_dir=str(tmp))

print("[1] 游戏列表 + 顶部下拉")
games = bridge.game_list()
print("  游戏列表:", games)
assert ("yys", "阴阳师") in games and ("demo", "演示游戏") in games
panel = VisualBuilderPanel(visual_bridge=bridge)
combo_items = [panel._game_combo.itemText(i)
               for i in range(panel._game_combo.count())]
print("  顶部下拉:", combo_items)
assert panel._game_combo.count() == 2

print("[2] 默认 yys：通用节点列表含 御魂调整+重启游戏（共享）")
op_list = [panel._canvas._op_list.item(i).data(Qt.UserRole)
           for i in range(panel._canvas._op_list.count())]
print("  通用节点:", sorted(op_list))
assert sorted(op_list) == ["restart_game", "soul_configure"]

print("[3] 切换到 demo：通用节点列表变为 演示动作+重启游戏")
# 按游戏名选择（排序不可靠）
for i in range(panel._game_combo.count()):
    if panel._game_combo.itemData(i) == "demo":
        panel._game_combo.setCurrentIndex(i)
        break
app.processEvents()
op_list2 = [panel._canvas._op_list.item(i).data(Qt.UserRole)
            for i in range(panel._canvas._op_list.count())]
print("  通用节点:", sorted(op_list2))
assert sorted(op_list2) == ["demo_action", "restart_game"]
assert bridge.current_game == "demo"

print("[4] operation 节点下拉也随游戏切换")
# 添加 operation 节点 → 下拉应含 demo 操作
node = panel._canvas.add_node("operation")
w = node.get_widget("operation")
cb = w.get_custom_widget()
items = [cb.itemText(i) for i in range(cb.count())]
print("  operation 下拉:", items)
assert "demo_action" in items and "soul_configure" not in items

print("[5] 通用节点 Tab 无按钮行（仅列表）")
assert not hasattr(panel._canvas, "_op_new_btn"), "新建按钮应已移除"
assert not hasattr(panel._canvas, "_op_add_btn"), "添加按钮应已移除"
print("  ✅ 无新建/添加按钮")

print("\n🎉 游戏下拉切换验证通过")
