"""验证：节点下拉控件（2026-08-15 重构）。

覆盖三个真实环境 bug：
1. 弹出列表被平台/主题压缩成单行（"列表很短、选项只能显示一个"）
   → _NodeCombo.showPopup 强制 条目数×行高，即使 sizeHintForRow 异常也要满高
2. 场景下拉（scene）加载任务后选中值丢失（重载后总显示第一项）
   → refresh_combos 从 property/_task_params 恢复原选中
3. 固定选项下拉（如 end 节点 finish_mode）走自绘控件后读写正常
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
from visual.rule_store import VisualTaskStore
from visual.scene_store import SceneStore
from ui.param_bridge.visual_bridge import VisualBridge
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel

tmp = Path(tempfile.mkdtemp(prefix="combo_popup_"))
store = VisualTaskStore(tmp / "vt")
scene_store = SceneStore([tmp / "scenes"])
# 场景库：两个场景各带信号（模拟器界面→模拟器、模拟器界面4→模拟器4）
scene_store.save({"id": "模拟器界面", "name": "模拟器界面", "signal": "模拟器",
                  "judgements": [], "logic": "and"})
scene_store.save({"id": "模拟器界面4", "name": "模拟器界面4", "signal": "模拟器4",
                  "judgements": [], "logic": "and"})
bridge = VisualBridge(store=store, assets_dir=str(tmp),
                      scene_store=scene_store)
bridge.create_task("t1", "任务", "daily")
panel = VisualBuilderPanel(visual_bridge=bridge)
panel.open_visual("yys", "task", "t1", store)
panel.resize(1000, 700)
panel.show()
app.processEvents()
c = panel._canvas

print("[1] 场景下拉：任务保存 模拟器界面4 → 重载后恢复该选中（非第一项）")
mats = panel._current_task.setdefault("materials", {})
mats["scenes"] = ["模拟器界面", "模拟器界面4"]
store.save(panel._current_task)
sp = c.add_node("scene_probe")
w = sp.get_widget("scene")
w.set_value("模拟器界面4")
app.processEvents()
# 模拟重载：把任务原值挂到 _task_params（load_task 的真实行为）
sp._task_params = {"scene": "模拟器界面4"}
c.refresh_combos()
w2 = sp.get_widget("scene")
combo = w2.get_custom_widget()
print("  下拉项:", [combo.itemText(i) for i in range(combo.count())])
print("  选中:", combo.currentText())
assert combo.currentText() == "模拟器界面4", "场景选中值未恢复"
print("  ✅ 场景选中值正确恢复")

print("[2] 弹出列表高度强制：即使 sizeHintForRow 被算成 4px")
combo.view().sizeHintForRow = lambda row, _v=combo.view(): 4
combo.showPopup()
app.processEvents()
v = combo.view()
print("  行数:", combo.count(), "弹出视图高:", v.height())
assert v.height() >= 28 * combo.count(), "弹出列表被压缩！"
# 弹出容器不得塌缩（真实平台曾把容器压成 2px 宽 → 列表不可见）
cont = v.parentWidget()
print("  弹出容器:", cont.width(), "x", cont.height())
assert cont.width() > 100, "弹出容器宽度塌缩！"
combo.hidePopup()
print("  ✅ 弹出列表满高且容器完整")

print("[3] 图标素材下拉：显示条目名、值存路径")
mats["elements"] = ["visual/t1/icons/模板图标3.json",
                    "visual/t1/icons/attack_btn.json"]
store.save(panel._current_task)
mt = c.add_node("clicker")
c.refresh_combos()
wm = mt.get_widget("template")
wm.set_value("visual/t1/icons/模板图标3.json")
app.processEvents()
mc = wm.get_custom_widget()
print("  显示:", [mc.itemText(i) for i in range(mc.count())],
      "| 值:", mc.currentData())
assert set(mc.itemText(i) for i in range(mc.count())) == {"attack_btn", "模板图标3"}
assert mc.currentData() == "visual/t1/icons/模板图标3.json"
print("  ✅ 显示名/路径分离正常")

print("[4] 固定选项下拉（end.finish_mode）读写")
en = c.add_node("end")
we = en.get_widget("finish_mode")
ec = we.get_custom_widget()
print("  默认:", ec.currentText())
assert ec.currentText() == "结束任务"
we.set_value("返回主菜单")
app.processEvents()
assert ec.currentText() == "返回主菜单"
task = c.export_task(panel._current_task)
end_nodes = [x for x in task["graph"]["nodes"] if x["type"] == "end"
             and x["params"].get("finish_mode") == "返回主菜单"]
assert end_nodes, "固定下拉导出失败"
print("  ✅ 固定下拉导出:", end_nodes[0]["params"]["finish_mode"])

print("[5] 信号触发器下拉：任务素材库场景→信号映射")
trig = c.add_node("scene_trigger")
c.refresh_combos()
wt = trig.get_widget("scene")
tc = wt.get_custom_widget()
print("  信号项:", [tc.itemText(i) for i in range(tc.count())])
assert [tc.itemText(i) for i in range(tc.count())] == ["模拟器", "模拟器4"]
wt.set_value("模拟器4")
app.processEvents()
assert tc.currentText() == "模拟器4"
task2 = c.export_task(panel._current_task)
trig_node = next(x for x in task2["graph"]["nodes"]
                 if x["type"] == "scene_trigger")
print("  导出监听信号:", trig_node["params"].get("scene"))
assert trig_node["params"].get("scene") == "模拟器4"
# 信号恢复（重载场景）：任务参数 → 重填后选中保持
trig._task_params = {"scene": "模拟器4"}
c.refresh_combos()
assert trig.get_widget("scene").get_custom_widget().currentText() == "模拟器4"
print("  ✅ 信号下拉：场景→信号、选中、导出、恢复全部正常")

print("\n🎉 节点下拉控件全部验证通过")
