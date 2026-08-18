"""验证：素材管理弹窗（2026-08-15 双 Tab 重构）。

左=全局库三 Tab（场景/图标/OCR识别素材）右键加入任务；
右=本任务库三 Tab（随左侧联动）移除；
只有任务素材库的素材出现在节点下拉。
"""
import sys
import tempfile
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
from ui.visual_builder.material_dialog import MaterialManagerDialog

tmp = Path(tempfile.mkdtemp(prefix="mat_dlg_"))
store = VisualTaskStore(tmp / "vt")
bridge = VisualBridge(store=store, assets_dir=str(tmp))
bridge.create_task("mattask", "素材任务", "daily")
panel = VisualBuilderPanel(visual_bridge=bridge)
assert panel.open_visual("yys", "task", "mattask", store)

# 全局库：2 图标 + 2 场景 + 2 OCR
glob_elems = ["visual/t1/icon_a.png", "visual/t1/icon_b.png"]
glob_scenes = [{"id": "scene_main", "name": "主界面"},
               {"id": "scene_battle", "name": "战斗界面"}]
glob_ocr = ["visual/t1/ocr/体力数值.json", "visual/t1/ocr/勾玉数量.json"]

print("[1] 弹窗初始：左右双 Tab 结构，任务库为空")
dlg = MaterialManagerDialog(glob_elems, glob_scenes, [], [],
                            global_ocr=glob_ocr, task_ocr=[])
assert dlg._left_tabs.count() == 3 and dlg._right_tabs.count() == 3
assert dlg._task_lists["scene"].count() == 0
assert dlg._task_lists["element"].count() == 0
assert dlg._task_lists["ocr"].count() == 0
assert dlg._global_lists["scene"].count() == 2
assert dlg._global_lists["element"].count() == 2
assert dlg._global_lists["ocr"].count() == 2
print("  ✅ 左右双 Tab（三分类）初始正确")

print("[2] 左 Tab 切换 → 右侧自动跟随")
dlg._left_tabs.setCurrentIndex(2)
assert dlg._right_tabs.currentIndex() == 2
dlg._left_tabs.setCurrentIndex(0)
assert dlg._right_tabs.currentIndex() == 0
print("  ✅ 左右 Tab 联动")

print("[3] 右键加入：三分类都能加入任务库")
dlg._add_to_task("scene", "scene_main")
dlg._add_to_task("element", "visual/t1/icon_a.png")
dlg._add_to_task("ocr", "visual/t1/ocr/体力数值.json")
assert dlg.result_materials() == {
    "scenes": ["scene_main"],
    "elements": ["visual/t1/icon_a.png"],
    "ocr": ["visual/t1/ocr/体力数值.json"]}
assert dlg._task_lists["scene"].count() == 1
assert dlg._task_lists["element"].count() == 1
assert dlg._task_lists["ocr"].count() == 1
print("  ✅ 三分类加入任务素材库")

print("[4] 右侧移除")
for key in ("scene", "element", "ocr"):
    dlg._task_lists[key].setCurrentRow(0)
    dlg._remove_task(key)
assert dlg.result_materials() == {"scenes": [], "elements": [], "ocr": []}
print("  ✅ 移除生效")

print("[5] 任务下拉只显示素材库素材（面板集成）")
mats = panel._current_task.setdefault("materials", {})
mats["scenes"] = ["scene_battle"]
mats["elements"] = ["visual/t1/icon_b.png"]
mats["ocr"] = ["visual/t1/ocr/勾玉数量.json"]
store.save(panel._current_task)
panel._canvas.refresh_combos()
sp = panel._canvas.add_node("scene_probe")
w = sp.get_widget("scene").get_custom_widget()
items = [w.itemText(i) for i in range(w.count())]
print("  场景下拉:", items)
assert items == ["scene_battle"]
mt = panel._canvas.add_node("clicker")
w2 = mt.get_widget("template").get_custom_widget()
items2 = [w2.itemText(i) for i in range(w2.count())]
print("  图标下拉:", items2)
assert items2 == ["icon_b"], items2   # 显示条目名（存储仍是完整路径）
ocr = panel._canvas.add_node("ocr_reader")
w3 = ocr.get_widget("template").get_custom_widget()
items3 = [w3.itemText(i) for i in range(w3.count())]
print("  OCR下拉:", items3)
assert items3 == ["勾玉数量"], items3
print("  ✅ 三类下拉都只显示本任务素材且显示条目名")

print("\n🎉 verify_material_dialog 全部通过")
