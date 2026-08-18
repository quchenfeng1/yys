# -*- coding: utf-8 -*-
"""
验证：标签体系 + 流程示图（2026-08-16）。

A. GraphCanvas 标签：框选封装为标签 / 导出-重载往返 / 设为阶段 /
   移动钳制（标签内节点不移出标签）/ 删除标签 / 保存为通用节点
B. visual_schema.stage_tags：阶段标签提取
C. build_progress_layout ordered：不依赖连线按顺序排 o-o-o
D. TaskManagerPanel：通用模块区已移除 + 「🖼 流程示图」Tab + 静态示图
"""
import os
import sys
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import (QApplication, QMessageBox, QInputDialog)
app = QApplication.instance() or QApplication(sys.argv)

# offscreen 下 QMessageBox 弹窗可能崩溃 → 替换为无操作
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL: {label}  {detail}"
    PASS += 1
    print(f"PASS {label}")


def main():
    from ui.visual_builder.graph_canvas import GraphCanvas

    # ═══ A. GraphCanvas 标签 ═══
    # 可控的 QInputDialog 返回值序列
    dialogs = ["进入战斗", "atk_first", "显示名A"]

    def _fake_gettext(parent, title, prompt, text=""):
        return dialogs.pop(0), True

    orig_gettext = QInputDialog.getText
    QInputDialog.getText = staticmethod(_fake_gettext)
    try:
        saved = {}
        c = GraphCanvas(save_compound_cb=lambda d: saved.update(d))
        n1 = c.add_node("clicker")
        n2 = c.add_node("clicker")
        n3 = c.add_node("end")
        # 选中两个点击器 → 封装为标签
        n3.set_selected(False)
        n1.set_selected(True)
        n2.set_selected(True)
        tid = c.tag_selected_nodes()
        check("A1 创建标签", tid is not None and tid in c._tag_map,
              str(tid))
        t = c._tag_map[tid]
        check("A2 标签成员", len(t["nodes"]) == 2, str(t["nodes"]))
        # 导出 → tags 序列化
        task = c.export_task(c._task)
        tags = task["graph"].get("tags", [])
        check("A3 导出 tags", len(tags) == 1 and tags[0]["id"] == tid
              and tags[0]["stage"] is False, str(tags))
        # 设为阶段 → 标签变浅绿色
        c.tag_set_stage(t["node"])
        task2 = c.export_task(c._task)
        check("A4 设为阶段", task2["graph"]["tags"][0]["stage"] is True)
        col = tuple(t["node"].get_property("color") or ())[:3]
        check("A4.5 阶段标签浅绿色", col == (167, 222, 160), str(col))
        check("A4.6 阶段状态查询", c._tag_is_stage(t["node"]) is True)
        # 取消阶段 → 恢复默认深青色
        c.tag_set_stage(t["node"])
        task2b = c.export_task(c._task)
        col2 = tuple(t["node"].get_property("color") or ())[:3]
        check("A4.7 取消阶段恢复默认色",
              task2b["graph"]["tags"][0]["stage"] is False
              and col2 == (5, 129, 138), str(col2))
        # 重新设为阶段 → 供重载测试
        c.tag_set_stage(t["node"])
        task2 = c.export_task(c._task)
        # 重载往返
        c2 = GraphCanvas(save_compound_cb=lambda d: saved.update(d))
        c2.load_task(task2)
        check("A5 重载标签", len(c2._tag_map) == 1
              and list(c2._tag_map.values())[0]["stage"] is True,
              str(c2._tag_map))
        tb = list(c2._tag_map.values())[0]["node"]
        col_r = tuple(tb.get_property("color") or ())[:3]
        check("A5.5 重载后阶段标签仍浅绿", col_r == (167, 222, 160),
              str(col_r))
        # 移动钳制：把成员节点甩到标签外
        t2 = list(c2._tag_map.values())[0]
        b = t2["node"]
        bx, by = list(b.pos())[:2]
        bw, bh = list(b.size())[:2]
        member_item = None
        for n in c2._graph.all_nodes():
            if n.type_.split(".")[-1] == "clicker":
                member_item = n.view
                break
        assert member_item is not None
        member_item.xy_pos = [bx + bw + 400, by + bh + 400]   # 甩出标签
        c2._on_nodes_moved({member_item: [bx + bw + 400, by + bh + 400]})
        x, y = member_item.xy_pos
        check("A6 节点钳制在标签内",
              bx + 8 <= x <= bx + bw and by + 26 <= y <= by + bh,
              f"pos=({x:.0f},{y:.0f}) box=({bx:.0f},{by:.0f},{bw:.0f},{bh:.0f})")
        # 删除标签
        c2.tag_delete(t2["node"])
        check("A7 删除标签", not c2._tag_map
              and not c2.export_task(c2._task)["graph"]["tags"])
    finally:
        QInputDialog.getText = orig_gettext

    # 保存为通用节点（2026-08-16 放宽限制）：标签可含开始/结束、多出入；
    # 仅保留内部连线；画布不重建
    dialogs = ["阶段1", "atk_first", "显示名A"]
    QInputDialog.getText = staticmethod(_fake_gettext)
    try:
        saved = {}
        c3 = GraphCanvas(save_compound_cb=lambda d: saved.update(d))
        s = c3.add_node("start")
        k = c3.add_node("clicker")
        e = c3.add_node("end")
        x = c3.add_node("clicker")   # 标签外节点（外部连线不保留）
        s.get_output("out").connect_to(k.get_input("in"))
        k.get_output("out").connect_to(e.get_input("in"))
        k.get_output("not_found").connect_to(x.get_input("in"))  # 内部→外部
        x.set_selected(False)
        s.set_selected(True)
        k.set_selected(True)
        e.set_selected(True)
        tid3 = c3.tag_selected_nodes()
        node_count_before = len(c3._graph.all_nodes())
        c3.tag_save_compound(c3._tag_map[tid3]["node"])
        sub = saved.get("subgraph") or {}
        sub_ids = {n["id"] for n in sub.get("nodes", [])}
        check("A8 保存通用节点（含开始/结束）",
              saved.get("name") == "atk_first" and len(sub.get("nodes", [])) == 3
              and any(n["type"] == "start" for n in sub["nodes"]), str(saved))
        check("A8.5 仅内部连线保留",
              all(c["out_node"] in sub_ids and c["in_node"] in sub_ids
                  for c in sub.get("connections", []))
              and len(sub.get("connections", [])) == 2, str(sub))
        entry = sub.get("entry_id")
        check("A8.6 入口为 start", entry and
              next(n for n in sub["nodes"] if n["id"] == entry)["type"] == "start",
              str(entry))
        check("A8.7 画布不重建（标签保留）",
              len(c3._tag_map) == 1 and tid3 in c3._tag_map
              and len(c3._graph.all_nodes()) == node_count_before)
    finally:
        QInputDialog.getText = orig_gettext

    # ═══ B/C. stage_tags + ordered 布局 ═══
    from visual import visual_schema as vs
    from visual.progress_tracker import build_progress_layout
    task_b = {"graph": {
        "nodes": [{"id": "n1", "type": "start", "name": "开始",
                   "pos": [0, 0], "params": {}},
                  {"id": "n2", "type": "clicker", "name": "点1",
                   "pos": [0, 0], "params": {}},
                  {"id": "n3", "type": "end", "name": "结束",
                   "pos": [0, 0], "params": {}}],
        "connections": [],
        "tags": [
            {"id": "t1", "name": "进战斗", "nodes": ["n1"], "stage": True},
            {"id": "t2", "name": "领奖", "nodes": ["n3"], "stage": True},
            {"id": "t3", "name": "非阶段", "nodes": ["n2"], "stage": False},
        ],
    }}
    groups = vs.stage_tags(task_b)
    check("B1 stage_tags 只取阶段标签", [g["name"] for g in groups] ==
          ["进战斗", "领奖"], str(groups))
    lay = build_progress_layout(task_b["graph"], groups, ordered=True)
    check("C1 有序布局不依赖连线",
          [p["name"] for p in lay["points"]] == ["进战斗", "领奖"]
          and len(lay["edges"]) == 1, str(lay))

    # ═══ D. TaskManagerPanel：通用模块移除 + 流程示图 ═══
    from ui.panels.task_manager_panel import TaskManagerPanel

    class FakeBridge:
        def load_task(self, name):
            tags = ([{"id": "t1", "name": "进战斗", "nodes": ["n1"],
                      "stage": True}] if name == "t1" else [])
            return {"name": name, "graph": {
                "nodes": [{"id": "n1", "type": "start", "name": "开始",
                           "pos": [0, 0], "params": {}}],
                "connections": [],
                "tags": tags}}

    panel = TaskManagerPanel(param_bridge=None, visual_bridge=FakeBridge())
    check("D1 通用模块区已移除", not hasattr(panel, "generic_list"),
          str([a for a in dir(panel) if "generic" in a]))
    texts = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    check("D2 流程示图 Tab", panel.tabs.count() >= 2
          and "流程示图" in panel.tabs.tabText(1),
          str(texts))
    panel._refresh_flow_view("t1")
    snap = panel._flow_view._snapshot
    check("D3 静态示图点位", snap is not None
          and [p["name"] for p in snap["points"]] == ["进战斗"], str(snap))
    # 无阶段标签任务 → 提示
    panel._refresh_flow_view("t2")
    check("D4 无标签提示", "没有阶段标签" in panel._flow_hint.text()
          or "暂无阶段标签" in panel._flow_hint.text(),
          panel._flow_hint.text())

    # ═══ E. 通用节点部署为标签（2026-08-16：像基础节点一样拖出） ═══
    from PyQt5.QtWidgets import QListWidgetItem as _QI

    sub_def = {
        "name": "atk_first", "display_name": "攻击首个",
        "subgraph": {
            "nodes": [
                {"id": "s1", "type": "start", "name": "开始",
                 "pos": [10, 10], "params": {}},
                {"id": "k1", "type": "clicker", "name": "点1",
                 "pos": [10, 200], "params": {}},
                {"id": "e1", "type": "end", "name": "结束",
                 "pos": [300, 200], "params": {}},
            ],
            "connections": [
                {"out_node": "s1", "out_port": "out", "in_node": "k1", "in_port": "in"},
                {"out_node": "k1", "out_port": "out", "in_node": "e1", "in_port": "in"},
            ],
            "entry_id": "s1",
        },
    }

    def _fake_loader(name):
        return dict(sub_def) if name == "atk_first" else None

    c4 = GraphCanvas(compound_loader=_fake_loader,
                     compound_list_provider=lambda: [{
                         "name": "atk_first", "display_name": "攻击首个",
                         "node_count": 3}])
    from PyQt5.QtWidgets import QListWidget as _QLW
    check("E1 列表样式同基础节点（IconMode 网格、无图标）",
          c4._compound_list.viewMode() == _QLW.IconMode
          and c4._compound_list.item(0).icon().isNull(),
          str(c4._compound_list.viewMode()))
    tid_e1 = c4.place_compound_tag("atk_first", [50, 50])
    check("E2 部署为标签", tid_e1 is not None and tid_e1 in c4._tag_map
          and len(c4._tag_map[tid_e1]["nodes"]) == 3, str(c4._tag_map))
    node_task_ids = [c4._node_to_task[n] for n in c4._graph.all_nodes()
                     if n.type_.split(".")[-1] != "BackdropNode"]
    check("E3 子图节点复制入画布", len(node_task_ids) == 3, str(node_task_ids))
    # 再次部署 → id 互不冲突（6 个任务 id）
    tid_e2 = c4.place_compound_tag("atk_first", [600, 50])
    node_task_ids2 = [c4._node_to_task[n] for n in c4._graph.all_nodes()
                      if n.type_.split(".")[-1] != "BackdropNode"]
    check("E4 重复部署不冲突", tid_e2 is not None
          and len(node_task_ids2) == 6 and len(set(node_task_ids2)) == 6,
          str(node_task_ids2))
    # 双击部署（与拖放一致）
    item = _QI("攻击首个（atk_first）")
    item.setData(0x0100, "atk_first")   # Qt.UserRole
    c4._on_compound_double_clicked(item)
    check("E5 双击同样部署标签", len(c4._tag_map) == 3, str(len(c4._tag_map)))

    # ═══ F. 更名「节点组合」+ 删除按钮（2026-08-16） ═══
    lib = {"atk_first": True}
    deleted = []

    def _provider():
        return [{"name": n, "display_name": "攻击首个", "node_count": 3}
                for n in lib]

    c5 = GraphCanvas(compound_loader=_fake_loader,
                     compound_list_provider=_provider,
                     delete_compound_cb=lambda n: deleted.append(n) or lib.pop(n, None) is not None)
    check("F1 列表仅显示名（像基础节点）",
          c5._compound_list.item(0).text() == "攻击首个",
          str(c5._compound_list.item(0).text()))
    check("F2 删除按钮存在", hasattr(c5, "_compound_del_btn")
          and "删除" in c5._compound_del_btn.text())
    c5._compound_list.setCurrentRow(0)
    orig_q = __import__("PyQt5.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    try:
        c5._on_compound_delete()
    finally:
        QMessageBox.question = orig_q
    check("F3 删除回调被调", deleted == ["atk_first"], str(deleted))
    check("F4 删除后列表刷新为空提示", c5._compound_list.count() == 1
          and not c5._compound_list.isEnabled(), str(c5._compound_list.count()))

    # ═══ G. 手动拖拽（2026-08-16 重写：grabMouse 手动拖放，跨控件 DnD 不可靠） ═══
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtCore import QPointF, QEvent, Qt
    drops = []
    c6 = GraphCanvas(compound_loader=_fake_loader,
                     compound_list_provider=lambda: [
                         {"name": "atk_first", "display_name": "攻击首个",
                          "node_count": 3}])
    c6._compound_list.compound_drop_requested.connect(lambda n: drops.append(n))
    lw = c6._compound_list
    item0 = lw.item(0)
    rect = lw.visualItemRect(item0)
    p0 = QPointF(rect.center())
    p1 = QPointF(rect.center().x() + 40, rect.center().y() + 40)
    lw.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p0,
                                   Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    lw.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p1,
                                  Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    lw.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, p1,
                                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    check("G1 手动拖拽释放信号", drops == ["atk_first"], str(drops))
    # 轮询兜底：release 事件丢失时（grab 冲突场景），定时器检测左键释放也能完成
    lw.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p0,
                                   Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    lw.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p1,
                                  Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    # 不调 mouseReleaseEvent，直接模拟轮询检测到左键已释放
    lw._watch_drag()
    check("G1.5 轮询兜底拖拽完成", drops == ["atk_first", "atk_first"],
          str(drops))
    tid_g = c6._on_compound_manual_drop("atk_first")
    check("G2 手动拖放 handler 部署标签",
          tid_g is not None and len(c6._tag_map) >= 1, str(tid_g))

    # ═══ H. 撤销部署（2026-08-16：一次撤销直接回到部署前） ═══
    c7 = GraphCanvas(compound_loader=_fake_loader,
                     compound_list_provider=lambda: [
                         {"name": "atk_first", "display_name": "攻击首个",
                          "node_count": 3}])
    base_nodes = len(c7._graph.all_nodes())
    tid_h = c7.place_compound_tag("atk_first", [50, 50])
    check("H1 部署后节点增加", tid_h is not None
          and len(c7._graph.all_nodes()) > base_nodes,
          str((tid_h, base_nodes, len(c7._graph.all_nodes()))))
    c7._graph._undo_stack.undo()
    check("H2 撤销一次回到部署前",
          len(c7._graph.all_nodes()) == base_nodes,
          str((base_nodes, len(c7._graph.all_nodes()))))
    task_h = c7.export_task(c7._task)
    check("H3 撤销后导出无幽灵标签",
          not task_h["graph"].get("tags"), str(task_h["graph"].get("tags")))

    print(f"\n🎉 标签体系 + 流程示图验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
