"""临时验证：可视化构建 UI 冒烟（offscreen 画布 + 面板 + 保存往返）。"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)

from visual.rule_store import VisualTaskStore
from ui.param_bridge.visual_bridge import VisualBridge
from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
from ui.visual_builder.graph_canvas import GraphCanvas


def main():
    tmp = Path(tempfile.mkdtemp(prefix="visual_ui_"))
    store = VisualTaskStore(tmp)
    bridge = VisualBridge(store=store, assets_dir=str(tmp))

    # 1. 新建任务
    task = bridge.create_task("smoke_flow", "冒烟流程", "daily")
    print("[1] 新建任务 OK:", task["name"])

    # 2. 面板创建 + 加载
    panel = VisualBuilderPanel(visual_bridge=bridge)
    assert panel.open_visual("yys", "task", "smoke_flow", store)
    print("[2] 面板加载任务 OK, 画布节点数:", len(panel._canvas._graph.all_nodes()))

    # 3. 画布添加节点（默认任务已有 Start）
    c = panel._canvas
    start = c._graph.all_nodes()[0]   # 已有 Start
    clicker = c.add_node("clicker")
    scene = c.add_node("scene_probe")
    branch = c.add_node("branch")
    loop = c.add_node("loop")
    end = c.add_node("end")
    print("[3] 添加节点 OK:", [n.type_.split('.')[-1] for n in c._graph.all_nodes()])
    assert len(c._graph.all_nodes()) == 6

    # 4. 连线：start.out → clicker.in；clicker.out → scene.in
    start.get_output("out").connect_to(clicker.get_input("in"))
    clicker.get_output("out").connect_to(scene.get_input("in"))
    scene.get_output("out").connect_to(branch.get_input("in"))
    branch.get_output("true").connect_to(end.get_input("in"))
    print("[4] 连线 OK:", c.connection_count())

    # 5. 设置参数
    cw = clicker.get_widget("template")   # 点击器：仅图标素材参数
    if cw is not None:
        cw.set_value(["visual/t1/a.png", "visual/t1/b.png"])   # 刷新下拉
        cw.set_value("visual/t1/a.png")
    branch.get_widget("data_source").set_value("stamina")
    branch.get_widget("op").set_value(">=")
    branch.get_widget("value").set_value("30")
    print("[5] 参数设置 OK")

    # 6. 导出 → 保存 → 重新加载（往返）
    exported = c.export_task(panel._current_task)
    assert len(exported["graph"]["nodes"]) == 6, exported["graph"]["nodes"]
    assert len(exported["graph"]["connections"]) == 4
    store.save(exported)
    reloaded = store.load("smoke_flow")
    assert panel.open_visual("yys", "task", "smoke_flow", store)
    n2 = len(panel._canvas._graph.all_nodes())
    c2 = panel._canvas.connection_count()
    print(f"[6] 保存→重载往返 OK: {n2} 节点 / {c2} 连线")
    assert n2 == 6 and c2 == 4, (n2, c2)

    # 6.5 任务 id ↔ 画布节点映射（运行期高亮/截图预览按任务 id 查找）
    for nd in exported["graph"]["nodes"]:
        node = panel._canvas._node_by_id(nd["id"])
        assert node is not None, f"任务 id {nd['id']} 应能映射到画布节点"
        assert nd["type"] == node.type_.split(".")[-1]
    print("[6.5] 任务 id ↔ 画布节点映射 OK")

    # 7. 场景判定（教一个场景给 scene_probe 下拉）
    bridge._teach = None
    panel._current_task["teach"]["scenes"].append(
        {"id": "scene_main", "name": "主界面",
         "judgements": [], "logic": "and"})
    panel._canvas.load_task(panel._current_task)
    w = panel._canvas._graph.all_nodes()[2].get_widget("scene")
    print("[7] 场景下拉项:", w.get_value())
    w.set_value(list(["scene_main"]))
    w.set_value("scene_main")
    print("[7] 场景下拉选中:", w.get_value())

    # 8. 示教控制台
    tc = panel._teach_console
    print("[8] 示教控制台 OK, 有截图画布:", tc._canvas is not None)

    # 9. 删除节点/连线（选中节点删除 → 连线自动断开；键盘 Delete）
    c2 = GraphCanvas()
    c2.load_task({"graph": {"nodes": [], "connections": []}, "teach": {}})
    a = c2.add_node("clicker")
    b = c2.add_node("scene_probe")
    d = c2.add_node("end")
    a.get_output("out").connect_to(b.get_input("in"))
    b.get_output("out").connect_to(d.get_input("in"))
    assert c2.connection_count() == 2
    for n in c2._graph.all_nodes():
        n.set_selected(False)
    b.set_selected(True)
    app.processEvents()
    n_del = c2.delete_selected()
    assert n_del == 1 and len(c2._graph.all_nodes()) == 2 and c2.connection_count() == 0
    print("[9] 删除选中节点 OK（连线自动断开）")

    # 键盘 Delete 删除
    a2 = c2.add_node("clicker")
    e2 = c2.add_node("end")
    a2.get_output("out").connect_to(e2.get_input("in"))
    for n in c2._graph.all_nodes():
        n.set_selected(False)
    a2.set_selected(True)
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QKeyEvent
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
    c2.eventFilter(c2._viewer, ev)
    assert len(c2._graph.all_nodes()) == 3 and c2.connection_count() == 0
    print("[9] 键盘 Delete 删除 OK")

    print("\n🎉 可视化构建 UI 冒烟全部通过")


if __name__ == "__main__":
    main()
