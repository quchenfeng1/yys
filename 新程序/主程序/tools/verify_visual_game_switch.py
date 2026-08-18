"""验证：顶部游戏下拉 —— 通用节点列表按所选游戏切换。"""
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
from visual.compound_store import CompoundStore
from ui.param_bridge.visual_bridge import VisualBridge
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel

# 构造两个游戏：yys（阴阳师）+ demo（演示游戏），各带不同通用节点
tmp = Path(tempfile.mkdtemp(prefix="game_switch_"))
for gid, gname in [("yys", "阴阳师"), ("demo", "演示游戏")]:
    gdir = tmp / "games" / gid
    gdir.mkdir(parents=True)
    (gdir / "profile.yaml").write_text(
        f"game_id: {gid}\nname: {gname}\n", encoding="utf-8")
# 共享通用节点 + 各游戏内通用节点
CompoundStore([tmp / "games" / "_shared" / "nodes"]).save({
    "name": "restart_game", "display_name": "重启游戏",
    "subgraph": {"nodes": [], "connections": [], "entry_id": ""}})
CompoundStore([tmp / "games" / "yys" / "nodes"]).save({
    "name": "soul_configure", "display_name": "御魂调整",
    "subgraph": {"nodes": [], "connections": [], "entry_id": ""}})
CompoundStore([tmp / "games" / "demo" / "nodes"]).save({
    "name": "demo_action", "display_name": "演示动作",
    "subgraph": {"nodes": [], "connections": [], "entry_id": ""}})

profile = GameProfile(root=tmp, game_id="yys")
store = VisualTaskStore(tmp / "vt")
bridge = VisualBridge(store=store, game_profile=profile, assets_dir=str(tmp))

print("[1] 游戏列表 + 面板内下拉已移除（2026-08-16：顶部控制栏全局选择）")
games = bridge.game_list()
print("  游戏列表:", games)
assert ("yys", "阴阳师") in games and ("demo", "演示游戏") in games
panel = VisualBuilderPanel(visual_bridge=bridge)
assert not hasattr(panel, "_game_combo"), "面板内游戏下拉应已移除"

print("[2] 默认 yys：通用节点列表含 御魂调整+重启游戏（共享）")
node_list = [panel._canvas._compound_list.item(i).data(Qt.UserRole)
             for i in range(panel._canvas._compound_list.count())]
print("  通用节点:", sorted(node_list))
assert sorted(node_list) == ["restart_game", "soul_configure"]

print("[3] 全局切换到 demo → 面板刷新：通用节点变为 演示动作+重启游戏")
bridge.set_current_game("demo")
panel.on_game_switched()
app.processEvents()
node_list2 = [panel._canvas._compound_list.item(i).data(Qt.UserRole)
              for i in range(panel._canvas._compound_list.count())]
print("  通用节点:", sorted(node_list2))
assert sorted(node_list2) == ["demo_action", "restart_game"]
assert bridge.current_game == "demo"

print("[4] 双击列表 → 添加通用节点（compound 节点，子图内嵌）")
node = panel._canvas.add_compound_node("demo_action")
assert node is not None
ntype = node.type_.split(".")[-1]
w = node.get_widget("source")
src = str(w.get_value()) if w is not None else ""
print(f"  添加节点: type={ntype} source={src}")
assert ntype == "compound"
assert getattr(node, "_subgraph", None) is not None

print("\n🎉 游戏下拉切换验证通过")
