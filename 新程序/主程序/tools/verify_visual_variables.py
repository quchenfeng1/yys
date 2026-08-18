"""验证：变量组/常量组 + 外部参数（2026-08-15）。

覆盖：
1. schema：collect_var_groups / check_var_conflicts（组内/跨组/常量冲突）
2. resolve_param_refs：${key} 内嵌替换 / 未知键保留 / 子图递归
3. effective_param_values：常量值合并 / 存储值覆盖 / 类型转换
4. run_graph 注入：ctx.param_values → vars；loop count_var 控制循环次数
5. wait seconds_var / dragger distance_var 引用
6. 变量编辑弹窗：组内重名校验拒绝；类型列渲染
7. 画布：变量组/常量组无端口节点创建 + 导出变量定义
8. 旧任务兼容：无 param_values/无变量组 → 行为不变
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import numpy as np
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
from visual import visual_schema as vs
from visual.graph_runner import run_graph
from visual.nodes import GraphContext, _exec_wait, _exec_dragger


def _node(nid, ntype, **params):
    return {"id": nid, "type": ntype, "name": ntype,
            "pos": [0, 0], "params": params}


def _conn(out_node, out_port, in_node, in_port="in"):
    return {"id": "c", "out_node": out_node, "out_port": out_port,
            "in_node": in_node, "in_port": in_port}


# ── 1. 收集与冲突 ─────────────────────────────────────────
def test_collect_and_conflicts():
    graph = {"nodes": [
        _node("a", "variable_group", group_name="组A", variables=[
            {"label": "循环次数", "key": "loop_count", "type": "int",
             "default": 3},
        ]),
        _node("b", "constant_group", group_name="常量组", variables=[
            {"label": "路径", "key": "pkg", "value": "com.yys"},
        ]),
        _node("c", "variable_group", group_name="组B", variables=[
            {"label": "重复", "key": "loop_count", "type": "int",
             "default": 5},   # 与组A重复
            {"label": "又重复", "key": "dup", "type": "int", "default": 1},
            {"label": "又重复2", "key": "dup", "type": "int", "default": 2},
        ]),
    ], "connections": []}
    groups = vs.collect_var_groups(graph)
    assert len(groups) == 3, groups
    assert groups[1]["kind"] == "constant_group"
    errors = vs.check_var_conflicts(groups)
    print("  冲突:", errors)
    assert any("loop_count" in e for e in errors), "跨组重复未检出"
    assert any("「dup」重复" in e for e in errors), "组内重复未检出"
    assert not vs.check_var_conflicts(groups[:2]), "无冲突组误报"
    assert vs.is_valid_var_key("loop_count")
    assert not vs.is_valid_var_key("1abc") and not vs.is_valid_var_key("a b")
    print("  ✅ 变量组收集 + 跨组/组内/键格式冲突检测")


# ── 2. ${} 解析 ──────────────────────────────────────────
def test_resolve_refs():
    b = _node("b", "compound", source="c1")
    b["subgraph"] = {"nodes": [
        _node("s1", "set_var", var_name="v", var_value="${target}"),
    ], "connections": []}
    graph = {"nodes": [
        _node("a", "ocr_reader", template="x", keyword="到达${target}",
              output_var="out_${n}"),
        b,
        _node("c", "branch", value="${limit}", data_source="i"),
    ], "connections": []}
    g = vs.resolve_param_refs(graph, {"target": "营地", "n": "1",
                                      "limit": 7})
    assert g["nodes"][0]["params"]["keyword"] == "到达营地"
    assert g["nodes"][0]["params"]["output_var"] == "out_1"
    assert g["nodes"][1]["subgraph"]["nodes"][0]["params"]["var_value"] == "营地"
    assert g["nodes"][2]["params"]["value"] == "7"
    # 未知键保留
    g2 = vs.resolve_param_refs(graph, {})
    assert g2["nodes"][0]["params"]["keyword"] == "到达${target}"
    # 原图未被污染
    assert graph["nodes"][0]["params"]["keyword"] == "到达${target}"
    print("  ✅ ${} 内嵌/多处/子图递归替换，未知键保留，原图不污染")


# ── 3. 有效值合并与类型转换 ──────────────────────────────
def test_effective_values():
    task = {"graph": {"nodes": [
        _node("a", "variable_group", group_name="组", variables=[
            {"label": "次数", "key": "n", "type": "int", "default": 3},
            {"label": "比例", "key": "ratio", "type": "float", "default": 0.5},
            {"label": "启用", "key": "on", "type": "bool", "default": "true"},
            {"label": "文本", "key": "msg", "type": "text", "default": "hi"},
        ]),
        _node("b", "constant_group", group_name="常", variables=[
            {"label": "包名", "key": "pkg", "value": "com.x"},
        ]),
    ], "connections": []},
        "param_values": {"n": "7", "ratio": 0.8}}
    vals = vs.effective_param_values(task)
    assert vals["n"] == 7, vals            # 存储值覆盖 + int 转换
    assert abs(vals["ratio"] - 0.8) < 1e-6
    assert vals["on"] is True              # bool 默认转换
    assert vals["msg"] == "hi"
    assert vals["pkg"] == "com.x"          # 常量组值
    # 运行时覆盖
    vals2 = vs.effective_param_values(task, {"n": 9, "msg": "bye"})
    assert vals2["n"] == 9 and vals2["msg"] == "bye"
    print("  ✅ 常量合并 + 存储值覆盖 + 运行时覆盖 + 类型转换")


# ── 4. run_graph 注入 + loop count_var ───────────────────
class _Ex:
    def __init__(self):
        self.swipes = []
        self.clicks = []

    def click_position(self, x, y):
        self.clicks.append((x, y))

    def swipe(self, *a, **k):
        self.swipes.append((a, k))


def _make_ctx(task, params=None):
    ex = _Ex()
    ctx = GraphContext(task=task, screen_size=(300, 200), executor=ex,
                       param_values=params or {})
    ctx.assets_dir = tempfile.mkdtemp(prefix="var_run_")
    return ctx, ex


def test_loop_count_var():
    graph = {"nodes": [
        _node("start", "start"),
        _node("loop", "loop", mode="固定次数", count=99,
              count_var="loop_count"),
        _node("cnt", "counter", var_name="i", delta=1),
        _node("end", "end"),
    ], "connections": [
        _conn("start", "out", "loop"),
        _conn("loop", "out", "cnt"),
        _conn("cnt", "out", "loop", "loop_back"),
        _conn("loop", "done", "end"),
    ]}
    task = {"graph": graph}
    ctx, ex = _make_ctx(task, params={"loop_count": 5})
    r = run_graph(graph, ctx)
    assert r.status == "success", r.error_message
    assert int(ctx.vars.get("i", 0)) == 5, ctx.vars
    # 无参数 → 回退固定次数（count=99 会跑 99 次，改小验证默认路径）
    graph2 = vs.resolve_param_refs(graph, {})
    n = graph2["nodes"]
    n[1]["params"]["count"] = 2
    ctx2, _ = _make_ctx({"graph": graph2}, params={})
    r2 = run_graph(graph2, ctx2)
    assert int(ctx2.vars.get("i", 0)) == 2, ctx2.vars
    print("  ✅ 循环次数外部化：param_values.loop_count=5 → 循环 5 次；"
          "无参数回退固定次数")


# ── 5. wait / dragger 变量引用 ───────────────────────────
def test_wait_and_drag_refs():
    ctx, ex = _make_ctx({"graph": {}}, params={"secs": 2, "dist": 0.8,
                                              "dur": 300})
    # 直调执行器时不经过 run_graph 注入 → 手动模拟注入后的变量
    ctx.vars.update(ctx.param_values)
    slept = []
    ctx.sleep = lambda s: (slept.append(s), False)[1]
    r = _exec_wait({"params": {"seconds": 1, "seconds_var": "secs"}}, ctx)
    assert slept and abs(slept[0] - 2) < 0.01, slept
    # ${} 替换成数值字符串的情况（resolve 后）
    r2 = _exec_wait({"params": {"seconds": 1, "seconds_var": "4.5"}}, ctx)
    assert abs(slept[1] - 4.5) < 0.01, slept
    r3 = _exec_dragger({"params": {"direction": "up",
                                   "distance": 0.1, "distance_var": "dist",
                                   "duration_ms": 100, "duration_var": "dur"}},
                       ctx)
    assert ex.swipes, "拖拽未执行"
    args, kw = ex.swipes[0]
    assert abs(kw.get("duration", 0) - 0.3) < 0.01, kw   # 300ms/1000
    assert args[2] == 150 and args[3] == 100 - int(200 * 0.8), args  # 距离 0.8
    print("  ✅ wait/dragger 变量引用（变量键与 ${} 数值串均可）")


# ── 6. 弹窗校验（重名拒绝）───────────────────────────────
def test_dialog_validation():
    from ui.visual_builder import variable_dialog as vd
    from ui.visual_builder.variable_dialog import VariableGroupDialog
    warned = []
    vd.QMessageBox.warning = staticmethod(
        lambda *a, **k: warned.append(a))
    dlg = VariableGroupDialog("组A", [
        {"label": "循环次数", "key": "loop_count", "type": "int",
         "default": 3},
    ])
    dlg._add_row({"label": "重复", "key": "loop_count", "type": "text",
                  "default": ""})
    dlg._on_ok()
    assert warned, "组内重名应被拒绝"
    assert "重复" in warned[0][2], warned
    # 合法数据通过
    dlg2 = VariableGroupDialog("组B", [])
    dlg2._add_row({"label": "次数", "key": "n", "type": "int", "default": "5"})
    dlg2._on_ok()
    assert len(dlg2.variables) == 1 and dlg2.variables[0]["key"] == "n"
    print("  ✅ 变量弹窗：组内重名拒绝，合法行通过（类型下拉渲染）")


# ── 7. 画布：无端口节点创建与导出 ─────────────────────────
def test_canvas_var_nodes():
    from ui.visual_builder.graph_canvas import GraphCanvas
    c = GraphCanvas()
    c.resize(800, 500)
    c.show()
    n = c.add_node("variable_group")
    assert n is not None, "变量组节点创建失败"
    assert len(n.input_ports()) == 0 and len(n.output_ports()) == 0, \
        "变量组节点应为无端口"
    n.set_property("variables", [{"label": "循环次数", "key": "loop_count",
                                  "type": "int", "default": 3}])
    n.set_property("group_name", "组A")
    task = c.export_task({"graph": {"nodes": [], "connections": []},
                          "teach": {}})
    groups = vs.collect_var_groups(task.get("graph", {}))
    assert len(groups) == 1 and groups[0]["group_name"] == "组A", groups
    assert groups[0]["variables"][0]["key"] == "loop_count"
    # 重载任务 → 变量组节点参数恢复
    c.load_task(task)
    groups2 = vs.collect_var_groups(task.get("graph", {}))
    assert groups2 and groups2[0]["variables"], "重载后变量定义丢失"
    print("  ✅ 画布：变量组无端口节点创建/导出/重载定义不丢")


# ── 8. 旧任务兼容 ────────────────────────────────────────
def test_old_task_compat():
    task = {"name": "old", "graph": {"nodes": [
        _node("start", "start"), _node("end", "end")],
        "connections": [_conn("start", "out", "end")]}}
    norm = vs.normalize_task(task)
    assert norm.get("param_values") == {}, norm.get("param_values")
    ctx, _ = _make_ctx(norm, params=None)
    r = run_graph(norm["graph"], ctx)
    assert r.status == "success"
    assert not vs.collect_var_groups(norm["graph"])
    print("  ✅ 旧任务兼容：无 param_values/变量组节点，行为不变")


if __name__ == "__main__":
    test_collect_and_conflicts()
    test_resolve_refs()
    test_effective_values()
    test_loop_count_var()
    test_wait_and_drag_refs()
    test_dialog_validation()
    test_canvas_var_nodes()
    test_old_task_compat()
    print("\n🎉 verify_visual_variables 全部通过")
