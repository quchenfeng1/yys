"""验证：打开任务弹窗（游戏列表 / 通用操作+游戏任务 Tab / 打开返回）+ 面板 open_visual。"""
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
from ui.visual_builder.open_task_dialog import OpenTaskDialog
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel

# 构造临时游戏结构 games/yys/
tmp = Path(tempfile.mkdtemp(prefix="open_dlg_"))
gdir = tmp / "games" / "yys"
gdir.mkdir(parents=True)
(gdir / "profile.yaml").write_text("game_id: yys\nname: 阴阳师\n", encoding="utf-8")
shared = tmp / "games" / "_shared" / "operations"
shared.mkdir(parents=True)

# 造数据
tstore = VisualTaskStore(gdir / "visual_tasks")
tstore.create("farm_soul", "刷御魂", "daily")
tstore.create("explore", "探索", "daily")
ostore = OperationStore([shared, gdir / "operations"])
op = ostore.create("configure_team", "配置阵容")
op["graph"] = {"nodes": [], "connections": []}
ostore.save(op)
op2 = ostore.create("restart_game", "重启游戏")
op2["graph"] = {"nodes": [], "connections": []}
ostore.save(op2)

profile = GameProfile(root=tmp, game_id="yys")

print("[1] 弹窗：双 Tab（无游戏列表，直接走外部游戏选择 yys）")
dlg = OpenTaskDialog(profile, "yys")
assert not hasattr(dlg, "_game_list"), "游戏列表应已移除"
tabs = [dlg._tabs.tabText(i) for i in range(dlg._tabs.count())]
print("  Tab:", tabs)
assert tabs == ["通用操作", "游戏任务"]

print("[2] 通用操作 Tab 列表（共享+游戏内）")
dlg._tabs.setCurrentIndex(0)  # 通用操作
dlg._refresh_current()
op_names = [dlg._op_list.item(i).data(Qt.UserRole)
            for i in range(dlg._op_list.count())]
print("  通用操作:", op_names)
assert sorted(op_names) == ["configure_team", "restart_game"]

print("[3] 游戏任务 Tab 列表")
dlg._tabs.setCurrentIndex(1)  # 游戏任务
dlg._refresh_current()
task_names = [dlg._task_list.item(i).data(Qt.UserRole)
              for i in range(dlg._task_list.count())]
print("  游戏任务:", task_names)
assert sorted(task_names) == ["explore", "farm_soul"]

print("[4] 打开返回 (game, kind, name)")
dlg._task_list.setCurrentRow(0)
dlg._open()
sel = dlg.selected()
print("  选中:", sel)
assert sel == ("yys", "task", "explore") or sel[2] in task_names

print("[5] 面板 open_visual 打开操作子图")
store_bridge = VisualTaskStore(tmp / "vt2")
bridge = VisualBridge(store=store_bridge, assets_dir=str(tmp),
                      operation_store=ostore)
panel = VisualBuilderPanel(visual_bridge=bridge)
ok = panel.open_visual("yys", "operation", "configure_team", ostore)
print("  打开操作:", ok, "| 标签:", panel._open_label.text())
assert ok
assert panel._open_key == {"game": "yys", "kind": "operation",
                           "name": "configure_team"}
assert "通用操作" in panel._open_label.text()

print("[6] 打开任务到画布 + 保存往返")
ok2 = panel.open_visual("yys", "task", "farm_soul", tstore)
print("  打开任务:", ok2)
assert ok2
node = panel._canvas.add_node("clicker")
assert node is not None
# 保存（mock 掉 QMessageBox 弹窗，避免阻塞）
from unittest.mock import patch
with patch("PyQt5.QtWidgets.QMessageBox.information", return_value=None):
    panel._save()
reloaded = tstore.load("farm_soul")
print("  保存后节点数:", len(reloaded["graph"]["nodes"]))
assert len(reloaded["graph"]["nodes"]) >= 2

print("\n🎉 打开任务弹窗 + 面板重构验证通过")
