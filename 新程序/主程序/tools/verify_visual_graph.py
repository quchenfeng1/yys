"""临时验证：可视化节点图执行器核心逻辑（控制流/分支/循环）。"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visual import VisualTaskStore, visual_schema as vs
from visual.graph_runner import run_graph
from visual.nodes import GraphContext


def test_loop_branch():
    tmp = Path(tempfile.mkdtemp(prefix="visual_test_"))
    store = VisualTaskStore(tmp)
    task = store.create("test_flow", "流程测试", "daily")

    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    sv = vs.new_node("set_var", name="初始化")
    sv["params"] = {"var_name": "loop_count", "var_value": "0"}
    loop = vs.new_node("loop", name="循环")
    loop["params"] = {"mode": "固定次数", "count": 3}
    cnt = vs.new_node("counter", name="计数")
    cnt["params"] = {"var_name": "loop_count", "delta": 1}
    br = vs.new_node("branch", name="是否完成")
    br["params"] = {"data_source": "loop_count", "op": ">=", "value": "3"}
    end = vs.new_node("end", name="结束")

    graph["nodes"] = [start, sv, loop, cnt, br, end]
    graph["connections"] = [
        vs.new_connection(sv["id"], "in", start["id"], "out"),
        vs.new_connection(loop["id"], "in", sv["id"], "out"),
        vs.new_connection(cnt["id"], "in", loop["id"], "out"),
        vs.new_connection(br["id"], "in", cnt["id"], "out"),
        vs.new_connection(loop["id"], "loop_back", br["id"], "false"),
        vs.new_connection(end["id"], "in", br["id"], "true"),
    ]
    store.save(task)

    ctx = GraphContext(task=task)
    result = run_graph(task["graph"], ctx)
    print(f"loop_branch: status={result.status} vars={ctx.vars}")
    assert result.status == "success", result.error_message
    assert ctx.vars["loop_count"] == 3, f"loop_count={ctx.vars['loop_count']}"
    print("  ✅ 固定次数循环 3 轮正确")


def test_branch_comparison():
    tmp = Path(tempfile.mkdtemp(prefix="visual_test_"))
    store = VisualTaskStore(tmp)
    task = store.create("test_comp", "比较", "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    sv = vs.new_node("set_var", name="体力")
    sv["params"] = {"var_name": "stamina", "var_value": "25"}
    br = vs.new_node("branch", name="体力不足?")
    br["params"] = {"data_source": "stamina", "op": "<", "value": "30"}
    end = vs.new_node("end", name="结束")
    graph["nodes"] = [start, sv, br, end]
    graph["connections"] = [
        vs.new_connection(sv["id"], "in", start["id"], "out"),
        vs.new_connection(br["id"], "in", sv["id"], "out"),
        vs.new_connection(end["id"], "in", br["id"], "true"),
    ]
    store.save(task)
    ctx = GraphContext(task=task)
    result = run_graph(task["graph"], ctx)
    print(f"branch_compare: status={result.status} vars={ctx.vars}")
    assert result.status == "success"
    print("  ✅ 数值比较分支正确")


def test_missing_start():
    tmp = Path(tempfile.mkdtemp(prefix="visual_test_"))
    store = VisualTaskStore(tmp)
    task = store.create("test_nostart", "无开始", "daily")
    task["graph"]["nodes"] = [vs.new_node("end", name="结束")]
    ctx = GraphContext(task=task)
    result = run_graph(task["graph"], ctx)
    print(f"missing_start: status={result.status}")
    assert result.status == "error"
    print("  ✅ 缺 Start 报错")


def test_interrupt():
    import threading
    tmp = Path(tempfile.mkdtemp(prefix="visual_test_"))
    store = VisualTaskStore(tmp)
    task = store.create("test_int", "中断", "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    loop = vs.new_node("loop", name="死循环")
    loop["params"] = {"mode": "固定次数", "count": 99999}
    wait = vs.new_node("wait", name="等待")
    wait["params"] = {"seconds": 1}
    end = vs.new_node("end", name="结束")
    graph["nodes"] = [start, loop, wait, end]
    graph["connections"] = [
        vs.new_connection(loop["id"], "in", start["id"], "out"),
        vs.new_connection(wait["id"], "in", loop["id"], "out"),
        vs.new_connection(loop["id"], "loop_back", wait["id"], "out"),
        vs.new_connection(end["id"], "in", loop["id"], "done"),
    ]
    store.save(task)
    stop = threading.Event()
    ctx = GraphContext(task=task, stop_event=stop)
    import threading as th
    def _stop():
        th.Event().wait(0.3)
        stop.set()
    th.Thread(target=_stop, daemon=True).start()
    result = run_graph(task["graph"], ctx)
    print(f"interrupt: status={result.status}")
    assert result.status == "interrupted"
    print("  ✅ 中断机制正确")


class _FakeExecutor:
    """记录点击/滑动的假执行器"""
    def __init__(self):
        self.clicks = []
        self.swipes = []

    def click_position(self, x, y):
        self.clicks.append((int(x), int(y)))

    def swipe(self, *a, **k):
        self.swipes.append(k)


def _mk_login_task(store):
    task = store.create("login_flow", "登录流程", "daily")
    vs.add_scene(task, {"id": "login", "name": "登录界面",
                        "judgements": [{"primitive": "color_block"}], "logic": "and"})
    return task


def test_scene_probe_output_var():
    """场景判定输出变量：命中写 1 / 未命中写 0"""
    import visual.nodes as vn
    tmp = Path(tempfile.mkdtemp(prefix="visual_test_"))
    store = VisualTaskStore(tmp)
    task = _mk_login_task(store)
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    sp = vs.new_node("scene_probe", name="识别登录")
    sp["params"] = {"scene": "login", "timeout": 0.2, "output_var": "login"}
    end = vs.new_node("end", name="结束")
    graph["nodes"] = [start, sp, end]
    graph["connections"] = [
        vs.new_connection(sp["id"], "in", start["id"], "out"),
        vs.new_connection(end["id"], "in", sp["id"], "out"),
    ]
    store.save(task)
    # 未命中 → 变量 0
    vn._judge_scene = lambda scene, ctx: False
    ctx = GraphContext(task=task, executor=_FakeExecutor(), screen_size=(1080, 1920))
    r = run_graph(task["graph"], ctx)
    print(f"scene_probe 未命中: status={r.status} login={ctx.vars.get('login')}")
    assert r.status == "success" and ctx.vars.get("login") == "0"
    # 命中 → 变量 1
    vn._judge_scene = lambda scene, ctx: True
    ctx2 = GraphContext(task=task, executor=_FakeExecutor(), screen_size=(1080, 1920))
    r2 = run_graph(task["graph"], ctx2)
    print(f"scene_probe 命中: status={r2.status} login={ctx2.vars.get('login')}")
    assert r2.status == "success" and ctx2.vars.get("login") == "1"
    print("  ✅ 场景判定输出变量 0/1 正确")


def test_login_loop_random_click():
    """开始→识别登录界面→没识别到(动画)→随机点击→再识别→命中→往下走"""
    import visual.nodes as vn
    tmp = Path(tempfile.mkdtemp(prefix="visual_test_"))
    store = VisualTaskStore(tmp)
    task = _mk_login_task(store)
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    loop = vs.new_node("loop", name="直到登录")
    loop["params"] = {"mode": "直到条件", "count": 60, "condition": "login == 1"}
    sp = vs.new_node("scene_probe", name="识别登录")
    sp["params"] = {"scene": "login", "timeout": 0.2, "output_var": "login"}
    cl = vs.new_node("clicker", name="随机点击")
    cl["params"] = {"mode": "随机点", "point": "", "offset": 0}
    end = vs.new_node("end", name="结束")
    graph["nodes"] = [start, loop, sp, cl, end]
    graph["connections"] = [
        vs.new_connection(loop["id"], "in", start["id"], "out"),
        vs.new_connection(sp["id"], "in", loop["id"], "out"),
        vs.new_connection(loop["id"], "loop_back", sp["id"], "out"),
        vs.new_connection(cl["id"], "in", sp["id"], "not_found"),
        vs.new_connection(loop["id"], "loop_back", cl["id"], "out"),
        vs.new_connection(end["id"], "in", loop["id"], "done"),
    ]
    store.save(task)
    state = {"n": 0}

    def fake_judge(scene, ctx):
        state["n"] += 1
        # scene_probe 每次调用（timeout=0.2）内会判定 2 次；前 2 次调用都未命中
        # （动画中，判定 1~4 次均 False → 点击 2 次），第 3 次调用命中登录界面
        return state["n"] >= 5

    vn._judge_scene = fake_judge
    ex = _FakeExecutor()
    ctx = GraphContext(task=task, executor=ex, screen_size=(1080, 1920))
    r = run_graph(task["graph"], ctx)
    print(f"登录循环: status={r.status} login={ctx.vars.get('login')} "
          f"随机点击={len(ex.clicks)}次 判定={state['n']}次")
    assert r.status == "success", r.error_message
    assert ctx.vars.get("login") == "1"
    assert len(ex.clicks) == 2, f"应随机点击 2 次，实际 {len(ex.clicks)}"
    for (x, y) in ex.clicks:
        assert 0 <= x < 1080 and 0 <= y < 1920, f"随机点越界: {x},{y}"
    print("  ✅ 动画期间随机点击直到登录界面出现，命中后继续往下")


if __name__ == "__main__":
    test_loop_branch()
    test_branch_comparison()
    test_scene_probe_output_var()
    test_login_loop_random_click()
    test_missing_start()
    test_interrupt()
    print("\n🎉 节点图执行器核心逻辑全部通过")
