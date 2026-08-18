"""验证：场景判定节点 scene 下拉（无场景→空 / 有场景→可选 / 示教后→实时刷新）。"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
from visual.rule_store import VisualTaskStore
from visual.teach_engine import TeachEngine
from ui.param_bridge.visual_bridge import VisualBridge
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel

tmp = Path(tempfile.mkdtemp(prefix="scene_probe_"))
store = VisualTaskStore(tmp / "vt")
teach = TeachEngine(event_bus=None, store=store, assets_dir=str(tmp))
bridge = VisualBridge(store=store, teach_engine=teach, assets_dir=str(tmp))
bridge.create_task("探测任务", "探测任务", "daily")
panel = VisualBuilderPanel(visual_bridge=bridge)
assert panel.open_visual("yys", "task", "探测任务", store)
c = panel._canvas

print("[1] 无示教场景 → scene 下拉为空（正常）")
sp = c.add_node("scene_probe")
w = sp.get_widget("scene")
items = w.get_custom_widget()  # QComboBox
print("  下拉项:", [items.itemText(i) for i in range(items.count())])
assert items.count() == 0
print("  ✅ 无场景时为空（合理：没有可选场景）")

print("[2] 任务素材库有场景 → 下拉有值（只有加入素材库的才出现）")
# 模拟：示教保存场景后自动加入任务素材库
teach._task_name = "探测任务"
teach._task = store.load("探测任务")
teach._task["teach"]["scenes"].append(
    {"id": "scene_main", "name": "主界面", "judgements": [], "logic": "and"})
teach._task.setdefault("materials", {})["scenes"] = ["scene_main"]
teach.save_task()   # 持久化 → 画布 provider 从任务素材库读到
panel._current_task = teach._task
c.refresh_combos()
items2 = sp.get_widget("scene").get_custom_widget()
print("  下拉项:", [items2.itemText(i) for i in range(items2.count())])
assert items2.count() == 1 and items2.itemText(0) == "scene_main"
print("  ✅ 任务素材库场景出现在下拉")

print("[3] 选中场景并导出验证")
w.set_value("scene_main")
exported = c.export_task(panel._current_task)
sp_node = next(n for n in exported["graph"]["nodes"] if n["type"] == "scene_probe")
print("  导出 scene 参数:", sp_node["params"].get("scene"))
assert sp_node["params"].get("scene") == "scene_main"
print("  ✅ 选中值正确导出")

print("\n🎉 场景判定 scene 下拉验证通过")
