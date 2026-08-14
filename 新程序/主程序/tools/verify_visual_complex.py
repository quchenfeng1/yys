"""端到端验证：带循环+判断的复杂任务，及循环次数按任务配置驱动。

覆盖：
1. 嵌套循环（外层固定次数 + 内层固定次数）+ 分支判断 + 场景判定输出变量
2. 循环次数严格按任务 JSON 配置（画布上配的 count）执行
3. "直到条件"模式用变量驱动动态次数（可对接任务配置/参数上浮）
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visual import VisualTaskStore, visual_schema as vs
from visual.graph_runner import run_graph
from visual.nodes import GraphContext


class _FakeExecutor:
    def __init__(self):
        self.clicks = []

    def click_position(self, x, y):
        self.clicks.append((int(x), int(y)))

    def swipe(self, *a, **k):
        pass


def _mk_task(store, name, judge=True):
    task = store.create(name, "复杂任务", "daily")
    vs.add_scene(task, {"id": "login", "name": "登录界面",
                        "judgements": [{"primitive": "color_block"}], "logic": "and"})
    import visual.nodes as vn
    vn._judge_scene = lambda scene, ctx: judge
    return task


def test_nested_loop_branch_scene():
    """嵌套循环 + 分支 + 场景判定（输出变量）组合执行"""
    import visual.nodes as vn
    tmp = Path(tempfile.mkdtemp(prefix="visual_test_"))
    store = VisualTaskStore(tmp)
    task = _mk_task(store, "complex1")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    sv_turn = vs.new_node("set_var"); sv_turn["params"] = {"var_name": "turn", "var_value": "0"}
    sv_total = vs.new_node("set_var"); sv_total["params"] = {"var_name": "total", "var_value": "0"}
    loopA = vs.new_node("loop"); loopA["params"] = {"mode": "固定次数", "count": 3}
    sp = vs.new_node("scene_probe")
    sp["params"] = {"scene": "login", "timeout": 1, "output_var": "hit"}
    br = vs.new_node("branch")
    br["params"] = {"data_source": "hit", "op": "==", "value": "1"}
    cnt_total = vs.new_node("counter"); cnt_total["params"] = {"var_name": "total", "delta": 1}
    sv_miss = vs.new_node("set_var"); sv_miss["params"] = {"var_name": "miss", "var_value": "S"}
    loopB = vs.new_node("loop"); loopB["params"] = {"mode": "固定次数", "count": 2}
    cnt_turn = vs.new_node("counter"); cnt_turn["params"] = {"var_name": "turn", "delta": 1}
    end = vs.new_node("end")
    graph["nodes"] = [start, sv_turn, sv_total, loopA, sp, br,
                      cnt_total, sv_miss, loopB, cnt_turn, end]
    graph["connections"] = [
        vs.new_connection(sv_turn["id"], "in", start["id"], "out"),
        vs.new_connection(sv_total["id"], "in", sv_turn["id"], "out"),
        vs.new_connection(loopA["id"], "in", sv_total["id"], "out"),
        vs.new_connection(sp["id"], "in", loopA["id"], "out"),
        vs.new_connection(br["id"], "in", sp["id"], "out"),
        vs.new_connection(cnt_total["id"], "in", br["id"], "true"),
        vs.new_connection(sv_miss["id"], "in", br["id"], "false"),
        vs.new_connection(loopB["id"], "in", cnt_total["id"], "out"),
        vs.new_connection(loopB["id"], "in", sv_miss["id"], "out"),
        vs.new_connection(cnt_turn["id"], "in", loopB["id"], "out"),
        vs.new_connection(loopB["id"], "loop_back", cnt_turn["id"], "out"),
        vs.new_connection(loopA["id"], "loop_back", loopB["id"], "done"),
        vs.new_connection(end["id"], "in", loopA["id"], "done"),
    ]
    store.save(task)
    ctx = GraphContext(task=task, executor=_FakeExecutor(), screen_size=(1080, 1920))
    r = run_graph(task["graph"], ctx)
    print(f"嵌套循环+分支+场景: status={r.status} "
          f"turn={ctx.vars.get('turn')} total={ctx.vars.get('total')} "
          f"hit={ctx.vars.get('hit')} miss={ctx.vars.get('miss', '(未走false)')}")
    assert r.status == "success", r.error_message
    assert ctx.vars.get("turn") == 6, f"内层应 3*2=6 次，实际 {ctx.vars.get('turn')}"
    assert ctx.vars.get("total") == 3, f"外层应 3 次，实际 {ctx.vars.get('total')}"
    assert ctx.vars.get("hit") == "1", "场景判定输出变量应为 1"
    assert ctx.vars.get("miss") is None, "judge 恒命中，不应走 false 分支设置 miss"
    print("  ✅ 嵌套循环(3×2)、分支、场景判定输出变量全部正确")


def test_count_from_config():
    """循环次数严格按任务 JSON 配置走（画布配置 count → 执行）"""
    import visual.nodes as vn
    tmp = Path(tempfile.mkdtemp(prefix="visual_test_"))
    store = VisualTaskStore(tmp)
    task = _mk_task(store, "cnt_cfg")

    def build(count):
        graph = task["graph"]
        graph["nodes"] = []
        graph["connections"] = []
        start = vs.new_node("start")
        sv = vs.new_node("set_var"); sv["params"] = {"var_name": "n", "var_value": "0"}
        loop = vs.new_node("loop"); loop["params"] = {"mode": "固定次数", "count": count}
        cnt = vs.new_node("counter"); cnt["params"] = {"var_name": "n", "delta": 1}
        end = vs.new_node("end")
        graph["nodes"] = [start, sv, loop, cnt, end]
        graph["connections"] = [
            vs.new_connection(sv["id"], "in", start["id"], "out"),
            vs.new_connection(loop["id"], "in", sv["id"], "out"),
            vs.new_connection(cnt["id"], "in", loop["id"], "out"),
            vs.new_connection(loop["id"], "loop_back", cnt["id"], "out"),
            vs.new_connection(end["id"], "in", loop["id"], "done"),
        ]
        store.save(task)

    def run():
        ctx = GraphContext(task=task, executor=_FakeExecutor(), screen_size=(1080, 1920))
        r = run_graph(task["graph"], ctx)
        return r, ctx

    build(4)
    r1, ctx1 = run()
    print(f"配置 count=4 → 执行次数 n={ctx1.vars.get('n')}")
    assert r1.status == "success" and ctx1.vars.get("n") == 4, ctx1.vars

    build(2)  # 改配置：count 2
    r2, ctx2 = run()
    print(f"配置 count=2 → 执行次数 n={ctx2.vars.get('n')}")
    assert r2.status == "success" and ctx2.vars.get("n") == 2, ctx2.vars
    print("  ✅ 循环次数随任务配置(count)变化，完全按配置走")


def test_until_condition_var():
    """直到条件：循环次数由变量/配置驱动（动态次数）"""
    import visual.nodes as vn
    tmp = Path(tempfile.mkdtemp(prefix="visual_test_"))
    store = VisualTaskStore(tmp)
    task = _mk_task(store, "until_var")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    sv_t = vs.new_node("set_var"); sv_t["params"] = {"var_name": "target", "var_value": "2"}
    sv_n = vs.new_node("set_var"); sv_n["params"] = {"var_name": "n", "var_value": "0"}
    loop = vs.new_node("loop")
    loop["params"] = {"mode": "直到条件", "count": 999, "condition": "n >= target"}
    cnt = vs.new_node("counter"); cnt["params"] = {"var_name": "n", "delta": 1}
    end = vs.new_node("end")
    graph["nodes"] = [start, sv_t, sv_n, loop, cnt, end]
    graph["connections"] = [
        vs.new_connection(sv_t["id"], "in", start["id"], "out"),
        vs.new_connection(sv_n["id"], "in", sv_t["id"], "out"),
        vs.new_connection(loop["id"], "in", sv_n["id"], "out"),
        vs.new_connection(cnt["id"], "in", loop["id"], "out"),
        vs.new_connection(loop["id"], "loop_back", cnt["id"], "out"),
        vs.new_connection(end["id"], "in", loop["id"], "done"),
    ]
    store.save(task)
    ctx = GraphContext(task=task, executor=_FakeExecutor(), screen_size=(1080, 1920))
    r = run_graph(task["graph"], ctx)
    print(f"直到条件(target=2): status={r.status} n={ctx.vars.get('n')}")
    assert r.status == "success" and ctx.vars.get("n") == 2, ctx.vars
    print("  ✅ 直到条件模式按变量(配置)动态控制循环次数")


if __name__ == "__main__":
    test_nested_loop_branch_scene()
    test_count_from_config()
    test_until_condition_var()
    print("\n🎉 复杂任务（循环+判断）端到端验证通过")
