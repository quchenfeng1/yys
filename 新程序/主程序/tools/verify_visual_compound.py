"""验证：复合节点封装 + 通用节点库（2026-08-15 重构，取代通用操作体系）。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from visual import VisualTaskStore, visual_schema as vs
from visual.compound_store import CompoundStore
from visual.graph_runner import run_graph
from visual.nodes import GraphContext


def _ctx(task, tmp):
    ctx = GraphContext(task=task, assets_dir=tmp, screen_size=(300, 200))
    ctx._screenshot = np.zeros((200, 300, 3), dtype=np.uint8)
    return ctx


def test_encapsulate_schema():
    """数据层封装：单入单出 / 多入多出 / start/end 排除"""
    tmp = Path(tempfile.mkdtemp(prefix="encap_"))
    store = VisualTaskStore(tmp)
    task = store.create("enc", "封装", "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    a = vs.new_node("set_var")
    a["params"] = {"var_name": "x", "var_value": "1"}
    b = vs.new_node("set_var")
    b["params"] = {"var_name": "y", "var_value": "2"}
    end = vs.new_node("end")
    graph["nodes"] = [start, a, b, end]
    graph["connections"] = [
        vs.new_connection(a["id"], "in", start["id"], "out"),
        vs.new_connection(b["id"], "in", a["id"], "out"),
        vs.new_connection(end["id"], "in", b["id"], "out"),
    ]

    # 封装 a（单入单出）
    cid, err = vs.encapsulate_nodes(task, [a["id"]])
    print(f"encap_single: id={cid} err={err!r}")
    assert cid and not err
    comp = vs.find_compound_node(graph, cid)
    assert comp["subgraph"]["entry_id"] == a["id"]
    assert len(graph["nodes"]) == 4  # start + b + end + compound
    # 3 条外部连线：start→comp、comp→b、b→end
    assert len(graph["connections"]) == 3
    print("  ✅ 单入单出封装 + 外部连线重接")

    # 多入多出 → 失败
    task2 = store.create("enc2", "封装2", "daily")
    g2 = task2["graph"]
    s2 = vs.find_node_by_type(g2, "start")
    x1 = vs.new_node("set_var")
    x2 = vs.new_node("set_var")
    x3 = vs.new_node("set_var")
    g2["nodes"] = [s2, x1, x2, x3]
    g2["connections"] = [
        vs.new_connection(x1["id"], "in", s2["id"], "out"),
        vs.new_connection(x2["id"], "in", s2["id"], "out"),  # 第二个入口
        vs.new_connection(x3["id"], "in", x1["id"], "out"),
    ]
    cid2, err2 = vs.encapsulate_nodes(task2, [x1["id"], x2["id"], x3["id"]])
    assert cid2 is None and "入口" in err2
    print(f"  ✅ 多入口拒绝: {err2}")

    # start 不可封装
    cid3, err3 = vs.encapsulate_nodes(task, [start["id"]])
    assert cid3 is None and "开始" in err3
    print(f"  ✅ start/end 排除: {err3}")


def test_compound_execution():
    """复合节点执行：start → compound(内部 set_var) → end"""
    tmp = Path(tempfile.mkdtemp(prefix="enc_exe_"))
    store = VisualTaskStore(tmp)
    task = store.create("exe", "执行", "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    inner = vs.new_node("set_var")
    inner["params"] = {"var_name": "did_inner", "var_value": "1"}
    end = vs.new_node("end")
    graph["nodes"] = [start, inner, end]
    graph["connections"] = [
        vs.new_connection(inner["id"], "in", start["id"], "out"),
        vs.new_connection(end["id"], "in", inner["id"], "out"),
    ]
    cid, err = vs.encapsulate_nodes(task, [inner["id"]])
    assert cid, err
    store.save(task)

    ctx = _ctx(task, tmp)
    result = run_graph(task["graph"], ctx)
    print(f"compound_exec: status={result.status} vars={ctx.vars}")
    assert result.status == "success", result.error_message
    assert ctx.vars.get("did_inner") == 1, "复合子图内部逻辑未执行"
    print("  ✅ 复合节点内联执行（子图 set_var 生效）")


def test_compound_store_and_load():
    """通用节点库：保存 → 列表 → 加载执行（params.name 引用库）"""
    tmp = Path(tempfile.mkdtemp(prefix="enc_lib_"))
    store = VisualTaskStore(tmp)
    lib = CompoundStore([tmp / "nodes"])

    # 造一个通用节点：set_var 片段
    node_name = "mark_done"
    inner = vs.new_node("set_var")
    inner["params"] = {"var_name": "mark", "var_value": "done"}
    lib.save({"name": node_name, "display_name": "标记完成",
              "subgraph": {"nodes": [inner], "connections": [],
                           "entry_id": inner["id"]}})
    metas = lib.list()
    print(f"lib_list: {metas}")
    assert metas and metas[0]["name"] == node_name
    assert lib.load(node_name)["subgraph"]["entry_id"] == inner["id"]

    # 任务图：start → compound(params.name=mark_done) → end
    task = store.create("use_lib", "用库", "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    comp = vs.new_node("compound", name="标记完成")
    comp["params"] = {"source": node_name}
    end = vs.new_node("end")
    graph["nodes"] = [start, comp, end]
    graph["connections"] = [
        vs.new_connection(comp["id"], "in", start["id"], "out"),
        vs.new_connection(end["id"], "in", comp["id"], "out"),
    ]
    ctx = _ctx(task, tmp)
    ctx.get_compound = lib.load
    result = run_graph(task["graph"], ctx)
    print(f"lib_exec: status={result.status} vars={ctx.vars}")
    assert result.status == "success"
    assert ctx.vars.get("mark") == "done", "通用节点库加载执行失败"
    print("  ✅ 通用节点库：保存→列表→按名字加载执行")

    # 子图缺失 → 报错
    task3 = store.create("use_missing", "缺失", "daily")
    g3 = task3["graph"]
    s3 = vs.find_node_by_type(g3, "start")
    comp2 = vs.new_node("compound")
    comp2["params"] = {"source": "no_such_node"}
    e3 = vs.new_node("end")
    g3["nodes"] = [s3, comp2, e3]
    g3["connections"] = [
        vs.new_connection(comp2["id"], "in", s3["id"], "out"),
        vs.new_connection(e3["id"], "in", comp2["id"], "out"),
    ]
    ctx2 = _ctx(task3, tmp)
    ctx2.get_compound = lib.load
    r = run_graph(g3, ctx2)
    assert r.status == "error" and "缺失" in r.error_message, r.error_message
    print("  ✅ 缺库名子图 → 报错")


if __name__ == "__main__":
    test_encapsulate_schema()
    test_compound_execution()
    test_compound_store_and_load()
    print("\n🎉 verify_visual_compound 全部通过")
