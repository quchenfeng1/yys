"""临时验证：通用操作（4.26）+ 参数上浮（4.27）核心逻辑。"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visual.operation_store import OperationStore
from visual import visual_schema as vs
from visual.graph_runner import run_graph
from visual.nodes import GraphContext


def _make_op_graph():
    """子图：start → set_var(ran_op=1) → end"""
    start = vs.new_node("start", name="开始")
    sv = vs.new_node("set_var", name="标记")
    sv["params"] = {"var_name": "ran_op", "var_value": "1"}
    end = vs.new_node("end", name="结束")
    return {
        "nodes": [start, sv, end],
        "connections": [
            vs.new_connection(sv["id"], "in", start["id"], "out"),
            vs.new_connection(end["id"], "in", sv["id"], "out"),
        ],
    }


def test_operation_store():
    tmp = Path(tempfile.mkdtemp(prefix="op_test_"))
    store = OperationStore([tmp / "shared", tmp / "game"])
    op = store.create("configure_team", "配置阵容")
    op["inputs"] = [
        {"name": "team", "type": "text", "hoist": True, "label": "队伍",
         "default": "主力"},
        {"name": "difficulty", "type": "combo", "hoist": True,
         "options": ["普通", "困难"], "default": "困难"},
    ]
    op["graph"] = _make_op_graph()
    store.save(op)
    loaded = store.load("configure_team")
    print("[1] 操作存储 OK:", loaded["name"],
          "| inputs:", [i["name"] for i in loaded["inputs"]])
    assert loaded["name"] == "configure_team"
    assert len(loaded["inputs"]) == 2
    assert store.exists("configure_team")
    # 参数上浮辅助
    hoisted = store.hoisted_params(loaded)
    assert len(hoisted) == 2, hoisted
    print("[1] hoisted_params OK:", [h["name"] for h in hoisted])


def test_operation_execution():
    tmp = Path(tempfile.mkdtemp(prefix="op_exec_"))
    store = OperationStore([tmp])
    op = store.create("configure_team", "配置阵容")
    op["inputs"] = [
        {"name": "team", "type": "text", "hoist": True, "label": "队伍",
         "default": "主力"},
    ]
    op["graph"] = _make_op_graph()
    store.save(op)

    # 任务图：start → operation(configure_team) → end
    task = vs.default_task("刷御魂", "刷御魂", "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    opn = vs.new_node("operation", name="操作")
    opn["params"] = {"operation": "configure_team"}
    end = vs.new_node("end", name="结束")
    graph["nodes"] = [start, opn, end]
    graph["connections"] = [
        vs.new_connection(opn["id"], "in", start["id"], "out"),
        vs.new_connection(end["id"], "in", opn["id"], "out"),
    ]

    # ① 无参数上浮 → 用操作默认值
    ctx = GraphContext(task=task, get_operation=store.load)
    result = run_graph(graph, ctx)
    print("[2] 操作执行:", result.status, "| vars:", ctx.vars)
    assert result.status == "success", result.error_message
    assert ctx.vars.get("op.configure_team.team") == "主力"
    assert ctx.vars.get("ran_op") == 1, "子图应已执行"
    print("[2] ① 操作子图执行 + 默认参数 OK")

    # ② 参数上浮（4.27）：param_values 覆盖默认
    ctx2 = GraphContext(task=task, get_operation=store.load,
                        param_values={"ops.configure_team.team": "高配"})
    result2 = run_graph(graph, ctx2)
    assert result2.status == "success"
    assert ctx2.vars.get("op.configure_team.team") == "高配"
    print("[2] ② 参数上浮覆盖 OK:", ctx2.vars.get("op.configure_team.team"))

    # ③ 任务缺 Start 的操作子图缺 start → 报错传递
    bad = store.create("bad_op", "坏操作")
    bad["graph"] = {"nodes": [vs.new_node("end", name="结束")], "connections": []}
    store.save(bad)
    task2 = vs.default_task("t2", "t2", "daily")
    g2 = task2["graph"]
    s2 = vs.find_node_by_type(g2, "start")
    opb = vs.new_node("operation", name="坏操作")
    opb["params"] = {"operation": "bad_op"}
    e2 = vs.new_node("end", name="结束")
    g2["nodes"] = [s2, opb, e2]
    g2["connections"] = [
        vs.new_connection(opb["id"], "in", s2["id"], "out"),
        vs.new_connection(e2["id"], "in", opb["id"], "out"),
    ]
    ctx3 = GraphContext(task=task2, get_operation=store.load)
    result3 = run_graph(g2, ctx3)
    print("[2] ③ 子图缺Start:", result3.status)
    assert result3.status == "error"
    print("[2] ③ 错误传递 OK")


def test_collect_params():
    tmp = Path(tempfile.mkdtemp(prefix="op_collect_"))
    store = OperationStore([tmp])
    op = store.create("configure_team", "配置阵容")
    op["inputs"] = [
        {"name": "team", "type": "text", "hoist": True, "label": "队伍",
         "default": "主力"},
        {"name": "difficulty", "type": "combo", "hoist": True,
         "options": ["普通", "困难"], "default": "困难"},
    ]
    op["graph"] = _make_op_graph()
    store.save(op)

    task = vs.default_task("刷御魂", "刷御魂", "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    opn = vs.new_node("operation", name="操作")
    opn["params"] = {"operation": "configure_team"}
    end = vs.new_node("end", name="结束")
    graph["nodes"] = [start, opn, end]
    graph["connections"] = [
        vs.new_connection(opn["id"], "in", start["id"], "out"),
        vs.new_connection(end["id"], "in", opn["id"], "out"),
    ]

    from visual.visual_schema import collect_task_params
    params = collect_task_params(task, store.load)
    print("[3] 收集参数:", [(p["path"], p["type"]) for p in params])
    assert len(params) == 2
    assert params[0]["path"] == "ops.configure_team.team"
    assert params[1]["path"] == "ops.configure_team.difficulty"
    assert params[1]["options"] == ["普通", "困难"]
    # 多个操作节点引用同一操作 → 去重
    opn2 = vs.new_node("operation", name="操作2")
    opn2["params"] = {"operation": "configure_team"}
    graph["nodes"].append(opn2)
    params2 = collect_task_params(task, store.load)
    assert len(params2) == 2, len(params2)
    print("[3] 去重 OK")


if __name__ == "__main__":
    test_operation_store()
    test_operation_execution()
    test_collect_params()
    print("\n🎉 通用操作 + 参数上浮核心逻辑全部通过")
