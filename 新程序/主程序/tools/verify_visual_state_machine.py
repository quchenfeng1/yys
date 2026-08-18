"""验证：场景信号表外置配置 + 信号触发器（2026-08-15 重构版）。

架构：场景信号表 = 任务 settings 配置（图外）；识图节点失败且失败端口
无连线 → 自动回查全局信号表 → 命中场景 → 激活对应信号触发器。

覆盖：
1. 自动回查命中：probe 失败(not_found 无连线) → 信号表命中 → 跳触发器执行
2. 信号表关闭：不回查，行为与旧版一致（自然结束）
3. 失败端口有连线：走显式处理，不自动回查
4. 命中场景但图中无监听触发器 → 报错
5. 全无命中 → 接示教回调（signal_table_unknown）后自然结束
6. 连续 N 次同一场景 → 报错（重试保护）
7. 真实模板匹配打分 _judge_scene_score（v2/旧结构）
8. 旧节点迁移：scene_detect 配置并入 settings、scene_entry→scene_trigger
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from visual import VisualTaskStore, visual_schema as vs
from visual.graph_runner import run_graph
from visual.nodes import GraphContext
from visual import nodes as vn


# ── 工具 ─────────────────────────────────────────────────
_ORIGINAL_JUDGE = vn._judge_scene_score


def _make_ctx(tmp: Path, task: dict, scenes: list[str],
              judge=None, on_unknown=None) -> GraphContext:
    """构造带假截图 / 场景库 / 自定义判定的上下文"""
    ctx = GraphContext(
        task=task,
        assets_dir=tmp,
        screen_size=(300, 200),
        on_unknown=on_unknown,
        scene_loader=lambda sid: {"id": sid, "name": sid},
        scene_lister=lambda: [{"id": s, "name": s} for s in scenes],
    )
    ctx._screenshot = np.zeros((200, 300, 3), dtype=np.uint8)
    ctx._shot_time = time.time()
    vn._judge_scene_score = judge if judge is not None else _ORIGINAL_JUDGE
    return ctx


def _judge_probe_fails_signal_a(scene, ctx):
    """probe 场景(probe_scene)永远失败；信号表场景 scene_a 命中 0.95"""
    sid = scene.get("id", "")
    if sid == "scene_a":
        return True, 0.95
    return False, 0.0


def _build_graph(store, name, with_trigger=True, explicit=False,
                 trigger_loopback=False):
    """骨架图：start→probe(失败)；触发器 scene_a → set_var(did_a=1) → end"""
    task = store.create(name, name, "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    probe = vs.new_node("scene_probe", name="期望页检查")
    probe["params"] = {"scene": "probe_scene", "timeout": 1}
    end = vs.new_node("end", name="结束")
    nodes = [start, probe, end]
    conns = [vs.new_connection(probe["id"], "in", start["id"], "out")]
    if with_trigger:
        trig = vs.new_node("scene_trigger", name="触发器A")
        trig["params"] = {"scene": "scene_a"}
        opa = vs.new_node("set_var", name="A操作")
        opa["params"] = {"var_name": "did_a", "var_value": "1"}
        nodes.append(trig)
        nodes.append(opa)
        if trigger_loopback:
            # streak 测试：触发器 out 只回连 probe，形成 probe失败→回查→触发→再probe 循环
            conns.append(vs.new_connection(probe["id"], "in", trig["id"], "out"))
        else:
            conns += [
                vs.new_connection(opa["id"], "in", trig["id"], "out"),
                vs.new_connection(end["id"], "in", opa["id"], "out"),
            ]
    if explicit:
        exp = vs.new_node("set_var", name="显式处理")
        exp["params"] = {"var_name": "did_explicit", "var_value": "1"}
        nodes.append(exp)
        conns += [
            vs.new_connection(exp["id"], "in", probe["id"], "not_found"),
            vs.new_connection(end["id"], "in", exp["id"], "out"),
        ]
    graph["nodes"] = nodes
    graph["connections"] = conns
    store.save(task)
    return task


def _enable_signal_table(task: dict, scenes: list | None = None,
                         retry_limit: int = 5) -> None:
    st = task["settings"]["signal_table"]
    st["enabled"] = True
    st["scenes"] = list(scenes) if scenes is not None else []
    st["retry_limit"] = retry_limit


# ── 测试 ─────────────────────────────────────────────────
def test_auto_route_hit():
    """probe 失败(无 false 连线) → 信号表命中 scene_a → 跳触发器执行"""
    tmp = Path(tempfile.mkdtemp(prefix="sm_hit_"))
    store = VisualTaskStore(tmp)
    task = _build_graph(store, "sm_hit")
    _enable_signal_table(task)
    store.save(task)

    ctx = _make_ctx(tmp, task, ["scene_a"],
                    judge=_judge_probe_fails_signal_a)
    result = run_graph(task["graph"], ctx)
    print(f"auto_hit: status={result.status} vars={ctx.vars} "
          f"signal={ctx.data.get('scene_signal')}")
    assert result.status == "success", result.error_message
    assert ctx.vars.get("did_a") == 1, "触发器后续逻辑未执行"
    assert ctx.data.get("scene_signal") == "scene_a"
    print("  ✅ 识图失败自动回查→命中→激活触发器")


def test_auto_route_disabled():
    """信号表关闭：失败端口无连线 → 自然结束（不回查不跳转）"""
    tmp = Path(tempfile.mkdtemp(prefix="sm_off_"))
    store = VisualTaskStore(tmp)
    task = _build_graph(store, "sm_off")
    # 默认 enabled=False

    ctx = _make_ctx(tmp, task, ["scene_a"],
                    judge=_judge_probe_fails_signal_a)
    result = run_graph(task["graph"], ctx)
    print(f"auto_off: status={result.status} vars={ctx.vars}")
    assert result.status == "success"
    assert "did_a" not in ctx.vars, "信号表关闭时不应激活触发器"
    assert "scene_signal" not in ctx.data
    print("  ✅ 信号表关闭=旧行为不变")


def test_auto_route_explicit():
    """失败端口有连线 → 走显式处理，不自动回查"""
    tmp = Path(tempfile.mkdtemp(prefix="sm_exp_"))
    store = VisualTaskStore(tmp)
    task = _build_graph(store, "sm_exp", with_trigger=True, explicit=True)
    _enable_signal_table(task)
    store.save(task)

    ctx = _make_ctx(tmp, task, ["scene_a"],
                    judge=_judge_probe_fails_signal_a)
    result = run_graph(task["graph"], ctx)
    print(f"auto_explicit: status={result.status} vars={ctx.vars}")
    assert result.status == "success"
    assert ctx.vars.get("did_explicit") == 1, "显式分支未执行"
    assert "did_a" not in ctx.vars, "有显式连线时不应激活触发器"
    assert "scene_signal" not in ctx.data
    print("  ✅ 有 false 连线=尊重显式处理，不回查")


def test_auto_route_no_trigger():
    """命中场景但图中无监听触发器 → 报错"""
    tmp = Path(tempfile.mkdtemp(prefix="sm_notrig_"))
    store = VisualTaskStore(tmp)
    task = _build_graph(store, "sm_notrig", with_trigger=False)
    _enable_signal_table(task)
    store.save(task)

    ctx = _make_ctx(tmp, task, ["scene_a"],
                    judge=_judge_probe_fails_signal_a)
    result = run_graph(task["graph"], ctx)
    print(f"no_trigger: status={result.status} msg={result.error_message}")
    assert result.status == "error"
    assert "无监听该场景" in result.error_message
    print("  ✅ 命中无触发器→报错提示")


def test_auto_route_unknown():
    """全无命中 → 不再阻断等示教，图自然结束（2026-08-15）"""
    tmp = Path(tempfile.mkdtemp(prefix="sm_unknown_"))
    store = VisualTaskStore(tmp)
    task = _build_graph(store, "sm_unknown", with_trigger=False)
    _enable_signal_table(task)
    store.save(task)
    calls: list = []

    def judge_all_fail(scene, ctx):
        return False, 0.0

    ctx = _make_ctx(tmp, task, ["scene_a"], judge=judge_all_fail,
                    on_unknown=lambda screen, info: calls.append(info))
    result = run_graph(task["graph"], ctx)
    print(f"unknown: status={result.status} calls={len(calls)}")
    assert result.status == "success"
    assert not calls, "全无命中不应再回调示教（直接结束）"
    assert ctx.data.get("scene_signal") is None
    print("  ✅ 全无命中→不阻断，图自然结束")


def test_auto_route_streak():
    """连续 N 次识别出同一场景 → 报错"""
    tmp = Path(tempfile.mkdtemp(prefix="sm_streak_"))
    store = VisualTaskStore(tmp)
    task = _build_graph(store, "sm_streak", with_trigger=True,
                        trigger_loopback=True)
    _enable_signal_table(task, retry_limit=3)
    store.save(task)

    ctx = _make_ctx(tmp, task, ["scene_a"],
                    judge=_judge_probe_fails_signal_a)
    result = run_graph(task["graph"], ctx)
    print(f"streak: status={result.status} msg={result.error_message} "
          f"count={ctx.data.get('_streak_count')}")
    assert result.status == "error"
    assert "连续" in result.error_message
    assert ctx.data.get("_streak_count", 0) >= 3
    print("  ✅ 连续 N 次同一场景报错")


def test_judge_scene_score_real_match():
    """真实模板匹配打分：v2 结构（regions+markers）与旧结构（judgements）"""
    tmp = Path(tempfile.mkdtemp(prefix="sm_score_"))
    screen = np.full((200, 300, 3), 127, dtype=np.uint8)
    cv2.rectangle(screen, (30, 30), (70, 70), (0, 0, 255), -1)     # 红块
    cv2.rectangle(screen, (120, 80), (170, 130), (255, 0, 0), -1)  # 蓝块
    cv2.imwrite(str(tmp / "red.png"), screen[30:70, 30:70].copy())
    cv2.imwrite(str(tmp / "blue.png"), screen[80:130, 120:170].copy())

    store = VisualTaskStore(tmp)
    task = store.create("sm_score", "score", "daily")
    ctx = _make_ctx(tmp, task, [])
    ctx._screenshot = screen

    scene_v2 = {"id": "s_v2", "regions": [
        {"region": None, "markers": [{"template": "red.png"}]}]}
    hit, score = vn._judge_scene_score(scene_v2, ctx)
    assert hit and score > 0.9, f"红块应高分命中: {score}"

    scene_v2b = {"id": "s_v2b", "accuracy": 2, "regions": [
        {"region": None, "markers": [
            {"template": "red.png"}, {"template": "blue.png"}]}]}
    hit2, score2 = vn._judge_scene_score(scene_v2b, ctx)
    assert hit2 and score2 > 0.9

    scene_v2c = {"id": "s_v2c", "accuracy": 2, "regions": [
        {"region": None, "markers": [
            {"template": "red.png"}, {"template": "missing.png"}]}]}
    assert not vn._judge_scene_score(scene_v2c, ctx)[0]

    scene_old = {"id": "s_old", "judgements": [
        {"primitive": "template", "template": "red.png", "threshold": 0.9}]}
    hit4, score4 = vn._judge_scene_score(scene_old, ctx)
    assert hit4 and score4 > 0.9

    scene_or = {"id": "s_or", "logic": "or", "judgements": [
        {"primitive": "template", "template": "missing.png", "threshold": 0.9},
        {"primitive": "template", "template": "blue.png", "threshold": 0.9}]}
    assert vn._judge_scene_score(scene_or, ctx)[0]
    print("  ✅ 真实匹配打分（v2/旧结构/accuracy/or）全部正确")


def test_migrate_legacy_nodes():
    """旧节点迁移：scene_detect→settings.signal_table、scene_entry→scene_trigger"""
    tmp = Path(tempfile.mkdtemp(prefix="sm_mig_"))
    store = VisualTaskStore(tmp)
    task = store.create("sm_mig", "迁移", "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    det = vs.new_node("scene_detect")
    det["params"] = {"scene_list": "a, b", "retry_limit": 3}
    ent = vs.new_node("scene_entry")
    ent["params"] = {"scene": "a"}
    graph["nodes"] = [start, det, ent]
    graph["connections"] = [vs.new_connection(ent["id"], "in", det["id"], "out")]

    norm = vs.normalize_task(task)
    st = norm["settings"]["signal_table"]
    print(f"migrate: signal_table={st} types="
          f"{[n['type'] for n in norm['graph']['nodes']]}")
    assert st["enabled"] is True
    assert st["scenes"] == ["a", "b"]
    assert st["retry_limit"] == 3
    types = [n["type"] for n in norm["graph"]["nodes"]]
    assert "scene_detect" not in types
    assert "scene_trigger" in types
    assert norm["graph"]["connections"] == []
    print("  ✅ 旧节点迁移正确（scene_detect 并入配置、scene_entry 改触发器）")


if __name__ == "__main__":
    test_auto_route_hit()
    test_auto_route_disabled()
    test_auto_route_explicit()
    test_auto_route_no_trigger()
    test_auto_route_unknown()
    test_auto_route_streak()
    test_judge_scene_score_real_match()
    test_migrate_legacy_nodes()
    print("\n🎉 verify_visual_state_machine 全部通过")
