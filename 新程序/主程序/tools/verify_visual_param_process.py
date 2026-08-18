"""验证：可调用变量 + 参数处理节点（2026-08-16）。

覆盖：
1. callable_var_defs：变量组「可调用」勾选收集
2. param_process：加/减/乘/除以/取余/变化为(text)/取反(bool)
3. 类型校验：非可调用变量拒绝；类型不匹配报错
4. CallableVarStore：update 节流写盘 + flush + 跨实例读回（跨运行保留）
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
from visual import visual_schema as vs
from visual.graph_runner import run_graph
from visual.nodes import GraphContext
from visual.callable_store import CallableVarStore


def _node(nid, ntype, **params):
    return {"id": nid, "type": ntype, "name": ntype,
            "pos": [0, 0], "params": params}


def _conn(out_node, out_port, in_node, in_port="in"):
    return {"id": "c", "out_node": out_node, "out_port": out_port,
            "in_node": in_node, "in_port": in_port}


def _graph(nodes):
    return {"nodes": nodes, "connections": []}


# ── 1. 定义收集 ──────────────────────────────────────────
def test_defs():
    graph = _graph([
        _node("a", "variable_group", group_name="组", variables=[
            {"label": "剩余次数", "key": "remain", "type": "int",
             "default": 100, "callable": True},
            {"label": "状态", "key": "state", "type": "text",
             "default": "充足", "callable": True},
            {"label": "开关", "key": "sw", "type": "bool",
             "default": False, "callable": True},
            {"label": "普通变量", "key": "normal", "type": "int",
             "default": 1},   # 未勾选
        ]),
    ])
    defs = vs.callable_var_defs(graph)
    assert set(defs) == {"remain", "state", "sw"}, defs
    assert defs["remain"]["type"] == "int"
    print("  ✅ callable_var_defs：只收集勾选「可调用」的变量")


# ── 2. 参数处理全运算符 ──────────────────────────────────
def _run_one(node, store, values):
    """单节点图：start → param_process → end"""
    graph = {
        "nodes": [
            _node("v", "variable_group", group_name="组", variables=[
                {"label": "剩余次数", "key": "remain", "type": "int",
                 "default": 100, "callable": True},
                {"label": "比例", "key": "ratio", "type": "float",
                 "default": 10.0, "callable": True},
                {"label": "状态", "key": "state", "type": "text",
                 "default": "充足", "callable": True},
                {"label": "开关", "key": "sw", "type": "bool",
                 "default": False, "callable": True},
            ]),
            _node("s", "start"), node, _node("e", "end"),
        ],
        "connections": [
            _conn("s", "out", node["id"], "in"),
            _conn(node["id"], "out", "e", "in"),
        ],
    }
    ctx = GraphContext(task={"graph": graph}, callable_store=store,
                       vars=dict(values))
    r = run_graph(graph, ctx)
    return r, ctx.vars


def test_ops():
    with tempfile.TemporaryDirectory() as td:
        store = CallableVarStore("demo", td)
        # 减 1：100 → 99
        r, vars_ = _run_one(_node("p", "param_process", var_name="remain",
                                  op="减", value="1"), store,
                            {"remain": 100})
        assert r.status == "success" and vars_["remain"] == 99, vars_
        # 加 1.5（int 截断）→ 100
        r, vars_ = _run_one(_node("p", "param_process", var_name="remain",
                                  op="加", value="1.5"), store, vars_)
        assert vars_["remain"] == 100, vars_
        # 乘 2 → 200
        r, vars_ = _run_one(_node("p", "param_process", var_name="remain",
                                  op="乘", value="2"), store, vars_)
        assert vars_["remain"] == 200, vars_
        # 除以 4 → 50
        r, vars_ = _run_one(_node("p", "param_process", var_name="remain",
                                  op="除以", value="4"), store, vars_)
        assert vars_["remain"] == 50, vars_
        # 取余 7 → 1
        r, vars_ = _run_one(_node("p", "param_process", var_name="remain",
                                  op="取余", value="7"), store, vars_)
        assert vars_["remain"] == 1, vars_
        # float 变化为 1.001
        r, vars_ = _run_one(_node("p", "param_process", var_name="ratio",
                                  op="变化为", value="1.001"), store, vars_)
        assert abs(vars_["ratio"] - 1.001) < 1e-9, vars_
        # text 变化为 '不足'（单引号）
        r, vars_ = _run_one(_node("p", "param_process", var_name="state",
                                  op="变化为", value="'不足'"), store, vars_)
        assert vars_["state"] == "不足", vars_
        # text 变化为 "充足"（双引号）
        r, vars_ = _run_one(_node("p", "param_process", var_name="state",
                                  op="变化为", value='"充足"'), store, vars_)
        assert vars_["state"] == "充足", vars_
        # bool 取反（运算值留空）
        r, vars_ = _run_one(_node("p", "param_process", var_name="sw",
                                  op="取反", value=""), store, vars_)
        assert vars_["sw"] is True, vars_
        r, vars_ = _run_one(_node("p", "param_process", var_name="sw",
                                  op="取反", value=""), store, vars_)
        assert vars_["sw"] is False, vars_
        print("  ✅ 加/减/乘/除以/取余/变化为(int/float/text)/取反(bool)")


# ── 3. 校验拒绝 ──────────────────────────────────────────
def test_reject():
    with tempfile.TemporaryDirectory() as td:
        store = CallableVarStore("demo", td)
        # 非可调用变量 → error
        graph = {
            "nodes": [
                _node("v", "variable_group", group_name="组", variables=[
                    {"label": "普通", "key": "n", "type": "int", "default": 1},
                ]),
                _node("s", "start"),
                _node("p", "param_process", var_name="n", op="加", value="1"),
                _node("e", "end"),
            ],
            "connections": [_conn("s", "out", "p", "in"),
                            _conn("p", "out", "e", "in")],
        }
        ctx = GraphContext(task={"graph": graph}, callable_store=store)
        r = run_graph(graph, ctx)
        assert r.status == "error" and "可调用" in r.error_message, r
        # int 变量变化为文本 → error
        r, _ = _run_one(_node("p", "param_process", var_name="remain",
                              op="变化为", value="'你好'"), store,
                        {"remain": 10})
        assert r.status == "error", r
        # text 变量加数字 → error
        r, _ = _run_one(_node("p", "param_process", var_name="state",
                              op="加", value="1"), store, {"state": "充足"})
        assert r.status == "error", r
        # 除以 0 → error
        r, _ = _run_one(_node("p", "param_process", var_name="remain",
                              op="除以", value="0"), store, {"remain": 10})
        assert r.status == "error", r
        print("  ✅ 非可调用变量/类型不匹配/除零 → error")


# ── 4. 持久化（跨运行保留） ──────────────────────────────
def test_persist():
    with tempfile.TemporaryDirectory() as td:
        published = []
        store = CallableVarStore("demo", td, flush_interval=0.0,
                                 publish=lambda t, k, v: published.append((t, k, v)))
        store.update("remain", 99)
        store.update("state", "不足")
        assert published == [("demo", "remain", 99), ("demo", "state", "不足")]
        # 新实例（模拟下次运行）读回
        store2 = CallableVarStore("demo", td)
        snap = store2.snapshot()
        assert snap.get("remain") == 99 and snap.get("state") == "不足", snap
        print("  ✅ CallableVarStore：更新发布事件 + 落盘 + 跨实例读回")


if __name__ == "__main__":
    test_defs()
    test_ops()
    test_reject()
    test_persist()
    print("\n🎉 verify_visual_param_process 全部通过")
