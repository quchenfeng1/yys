"""
验证：信号体系基础（2026-08-16）。

覆盖：
  A. 节点定义：6 个新节点 + 信号分类 + wait 升级（timeout 出口）
  B. AnomalyDetector：连续同键 N 次 / 键变化重置 / 窗口滑动 / 跨节点同信号
  C. AnomalyStore：记录 / 履历 / 已处理 / 确认修复 / 未处理计数
  D. SignalRegistry：场景信号 / 任务信号 / 触发信号 / 自定义增删
  E. 节点执行：任务信号输出发布 / 暂停节点（on_wait 恢复 / 超时）/ 调度器分支 / 超时节点
  F. 图执行：未接线出口兑底（跳转场景信号接收 / 异常上抛）
运行：QT_QPA_PLATFORM=offscreen python -X utf8 tools/verify_signal_nodes.py
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results: list[tuple[str, bool]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail and not cond else ""))


# ── A. 节点定义 ─────────────────────────────────────
from visual import node_defs as nd

expect = {"task_signal_out", "task_signal_in", "scene_signal_in",
          "task_signal_trigger", "scheduler_ops", "timeout"}
check("A1 新节点已注册", expect <= set(nd.NODE_DEFS), str(set(nd.NODE_DEFS) - expect))
check("A2 信号分类存在", "信号" in nd.categories(), str(nd.categories()))
wait_def = nd.NODE_DEFS.get("wait", {})
wait_ports = [p.get("name") for p in wait_def.get("outputs", [])]
check("A3 暂停节点有 timeout 出口", "timeout" in wait_ports, str(wait_ports))
sig_param = [p.get("name") for p in wait_def.get("params", [])]
check("A4 暂停节点有等待信号参数", "signal" in sig_param, str(sig_param))
ops_ports = [p.get("name") for p in nd.NODE_DEFS["scheduler_ops"].get("outputs", [])]
check("A5 调度器四出口", ops_ports == ["enqueue_pending", "enqueue_running",
                                        "skip", "invalidate"], str(ops_ports))

# ── B. AnomalyDetector ──────────────────────────────
from visual.anomaly_detector import AnomalyDetector

det = AnomalyDetector(count=3, window=5)
check("B1 连续同键3次异常", [det.check("n1", "庭院") for _ in range(3)][-1] is True)
det2 = AnomalyDetector(count=3, window=5)
r = [det2.check("n1", "庭院"), det2.check("n1", "庭院"),
     det2.check("n2", "战斗")]  # 节点与信号都变化 → 双计数器均重置
check("B2 键变化重置", r == [False, False, False], str(r))
det3 = AnomalyDetector(count=3, window=1)
r3 = [det3.check("n1", "庭院"), det3.check("n2", "庭院")]
time.sleep(1.1)  # 信号窗口过期（节点键计数只看连续、不看窗口 → 用不同节点验证）
r3.append(det3.check("n3", "庭院"))
check("B3 窗口过期重置", r3 == [False, False, False], str(r3))
det4 = AnomalyDetector(count=3, window=5)
r4 = [det4.check("n1", "战斗"), det4.check("n2", "战斗"),
      det4.check("n3", "战斗")]  # 跨节点同信号 3 次
check("B4 窗口内同信号异常", r4[-1] is True, str(r4))

# ── C. AnomalyStore ────────────────────────────────
import tempfile
from core.anomaly_store import AnomalyStore

tmp = Path(tempfile.mkdtemp())
st = AnomalyStore(tmp / "anomalies.json")
a1 = st.record("task_a", "连续同场景", node_id="n1", signal="庭院")
a2 = st.record("task_a", "等待超时", node_id="n2")
check("C1 记录+异常标记", st.is_task_abnormal("task_a")
      and len(st.list("task_a")) == 2)
check("C2 最新在上", st.list("task_a")[0]["id"] == a2["id"])
check("C3 未处理计数", st.unresolved_count("task_a") == 2)
st.mark_handled(a1["id"])
st.mark_handled(a2["id"])
check("C4 处理后计数归零", st.unresolved_count("task_a") == 0)
check("C5 确认修复", st.confirm_fixed("task_a")
      and not st.is_task_abnormal("task_a"))
shutil_rm = __import__("shutil").rmtree
shutil_rm(tmp, ignore_errors=True)

# ── D. SignalRegistry ──────────────────────────────
from core.signal_registry import SignalRegistry


class _FakeSceneStore:
    def __init__(self):
        self.items = [{"id": "scene_1", "signal": "庭院"},
                      {"id": "scene_2", "signal": ""}]

    def list(self):
        return self.items


class _FakeVStore:
    def __init__(self):
        self.items = {"t1": {"name": "t1", "graph": {"nodes": [
            {"type": "task_signal_out", "params": {"signal": "更换阵容"}},
            {"type": "task_signal_trigger", "params": {"signal": "更换阵容"}},
        ]}}}

    def list(self):
        return [{"name": k} for k in self.items]

    def load(self, name):
        return self.items.get(name)


tmp2 = Path(tempfile.mkdtemp())
reg = SignalRegistry(tmp2, scene_store=_FakeSceneStore(),
                     visual_store=_FakeVStore())
check("D1 场景信号", reg.scene_signals() ==
      [{"scene_id": "scene_1", "signal": "庭院"}], str(reg.scene_signals()))
check("D2 任务信号", "更换阵容" in reg.task_signal_names())
check("D3 触发信号", "更换阵容" in reg.trigger_signal_names())
check("D4 自定义增删", reg.add_custom("自定信号")
      and "自定信号" in reg.custom_signals()
      and reg.remove_custom("自定信号")
      and "自定信号" not in reg.custom_signals())
shutil_rm(tmp2, ignore_errors=True)

# ── E. 节点执行 ─────────────────────────────────────
import threading
from visual import nodes
from visual import visual_schema as vs

ctx = nodes.GraphContext(task=vs.default_task("t_e"), task_id="t_e")
sent: list[tuple] = []
ctx.signal_emit = lambda n, p: sent.append((n, p))
r = nodes.dispatch({"type": "task_signal_out", "id": "o1",
                    "params": {"signal": "更换阵容", "payload": ""}}, ctx)
check("E1 任务信号输出发布", r.goto == "out" and sent == [("更换阵容", "")], str(sent))

# 暂停节点：on_wait 注入 → 事件恢复
waits: list[tuple] = []
ctx2 = nodes.GraphContext(task=vs.default_task("t_w"), task_id="t_w")
ctx2.on_wait = lambda tid, sig, e, nid: (waits.append((tid, sig, nid)), e.set())
r2 = nodes.dispatch({"type": "wait", "id": "w1",
                     "params": {"seconds": 5, "signal": "更换完成"}}, ctx2)
check("E2 暂停节点注册+恢复", waits == [("t_w", "更换完成", "w1")]
      and r2.goto == "out", str((waits, r2.goto)))

# 暂停节点：on_wait 注入 → 首次进入挂起（paused 快照），恢复时走 out/timeout
ctx3 = nodes.GraphContext(task=vs.default_task("t_w2"), task_id="t_w2")
ctx3.on_wait = lambda tid, sig, sec, nid: None
r3 = nodes.dispatch({"type": "wait", "id": "w2",
                     "params": {"seconds": 60, "signal": ""}}, ctx3)
check("E3 首次进入挂起", r3.status == "paused"
      and ctx3.data.get("_pause_node_id") == "w2", str((r3.status, r3.goto)))
ctx3.resume_wait = True
ctx3.data["wait_outcome"] = "timeout"
r3b = nodes.dispatch({"type": "wait", "id": "w2",
                      "params": {"seconds": 60, "signal": ""}}, ctx3)
check("E3b 超时恢复走 timeout", r3b.goto == "timeout", str(r3b.goto))
ctx3.data["wait_outcome"] = "resume"
r3c = nodes.dispatch({"type": "wait", "id": "w2",
                      "params": {"seconds": 60, "signal": ""}}, ctx3)
check("E3c 信号恢复走 out", r3c.goto == "out", str(r3c.goto))

# 调度器分支
ops: list[tuple] = []
ctx4 = nodes.GraphContext(task=vs.default_task("t_s"), task_id="t_s")
ctx4.task["graph"]["nodes"] = [{"id": "s1", "type": "scheduler_ops"}]
ctx4.task["graph"]["connections"] = [
    {"out_node": "s1", "out_port": "enqueue_running",
     "in_node": "x", "in_port": "in"}]
ctx4.scheduler_op = lambda op, tid: ops.append((op, tid))
r4 = nodes.dispatch({"type": "scheduler_ops", "id": "s1", "params": {}}, ctx4)
check("E4 调度器分支", ops == [("running", "t_s")] and r4.goto == "enqueue_running",
      str((ops, r4.goto)))

# 超时节点
r5 = nodes.dispatch({"type": "timeout", "id": "to1", "params": {}}, ctx4)
check("E5 超时节点判异常", r5.status == "abnormal", str(r5.status))

# ── F. 图执行：未接线出口兑底 ─────────────────────────
from visual.graph_runner import run_graph

graph = vs.default_graph()
# start → set_var（out 未接线 → 兑底）→ 跳转 scene_signal_in → end
sn = vs.find_node_by_type(graph, "start")
sv = vs.new_node("set_var", "置数")
sv["params"] = {"var_name": "v", "var_value": "1"}
si = vs.new_node("scene_signal_in", "场景接收")
si["params"] = {"scene": "scene_x"}
en = vs.new_node("end", "结束")
graph["nodes"] += [sv, si, en]
graph["connections"] = [
    {"out_node": sn["id"], "out_port": "out", "in_node": sv["id"], "in_port": "in"},
    # set_var.out 故意不接 → 兑底
    {"out_node": si["id"], "out_port": "out", "in_node": en["id"], "in_port": "in"},
]

calls: list[tuple] = []


def fake_fb(node_id, goto):
    calls.append((node_id, goto))
    if node_id == sv["id"]:
        return {"jump_to": si["id"]}
    return None


ctxF = nodes.GraphContext(task=vs.default_task("t_f"), task_id="t_f",
                          scene_fallback=fake_fb)
res = run_graph(graph, ctxF)
check("F1 未接线出口跳转场景接收", res.status == "success"
      and (sv["id"], "out") in calls, str((res.status, calls)))


def fake_fb_abn(node_id, goto):
    return {"abnormal": True, "reason": "连续识别到同一场景信号达上限"}


ctxG = nodes.GraphContext(task=vs.default_task("t_g"), task_id="t_g",
                          scene_fallback=fake_fb_abn)
res2 = run_graph(graph, ctxG)
check("F2 异常上抛", res2.status == "abnormal"
      and "达上限" in (res2.reason or ""), str(res2.status))

# ── G. 调度器四功能 + 触发索引 + 信号分发编排 ───────────
from core.run_controller import RunController
from core.event_bus import EventBus
from core.events import Events


class _FakeSched:
    def __init__(self):
        self.calls: list[tuple] = []
        self.trigger_checker = None
        self.anomaly_checker = None

    def set_trigger_checker(self, fn):
        self.trigger_checker = fn

    def set_anomaly_checker(self, fn):
        self.anomaly_checker = fn

    def enqueue_pending(self, name):
        self.calls.append(("pending", name))

    def skip_cycle(self, name):
        self.calls.append(("skip", name))

    def invalidate(self, name):
        self.calls.append(("invalidate", name))

    def get_priority(self, name):
        return 5 if name == "task_b" else 10


def _def_with_ops(port: str, entry_after: bool = False) -> dict:
    nodes = [
        {"id": "trig", "type": "task_signal_trigger",
         "params": {"signal": "更换阵容"}},
        {"id": "ops", "type": "scheduler_ops", "params": {}},
    ]
    conns = [{"out_node": "trig", "out_port": "out",
              "in_node": "ops", "in_port": "in"},
             {"out_node": "ops", "out_port": port,
              "in_node": "w1" if entry_after else "x", "in_port": "in"}]
    if entry_after:
        nodes.append({"id": "w1", "type": "wait",
                      "params": {"seconds": 60, "signal": "更换完成"}})
    return {"name": "task_b", "graph": {"nodes": nodes, "connections": conns}}


class _FakeCls:
    def __init__(self, defn):
        self._definition = defn

    def trigger_signal_names(self):
        return ["更换阵容"]


class _FakeRegistry:
    def __init__(self, defs):
        self._registry = {n: _FakeCls(d) for n, d in defs.items()}


bus = EventBus()
rc = RunController(scheduler=_FakeSched(), connection=None, config=None,
                  state_mgr=None, registry=_FakeRegistry(
                      {"task_b": _def_with_ops("enqueue_running", True)}),
                  executor=None, recognizer=None, event_bus=bus,
                  monitor=None, account_mgr=None)
rc._rebuild_trigger_index()
check("G1 触发索引", rc._trigger_index.get("更换阵容") == ["task_b"],
      str(rc._trigger_index))
bus.publish(Events.TASK_SIGNAL, signal="更换阵容", payload="")
time.sleep(0.2)  # EventBus 异步分发
check("G2 信号激活入执行队列",
      "task_b" in rc._executing and rc._executing["task_b"]["entry"] == "w1",
      str(rc._executing.get("task_b")))
# 唤醒：task_b 等待「更换完成」
rc._task_pause = {"pause_node": "w1", "vars": {"v": 1},
                  "graph_data": {"k": 2}, "pause_signal": "更换完成",
                  "pause_seconds": 60}
rc._store_pause_record("task_b")
check("G3 暂停快照留存", rc._executing["task_b"]["signal"] == "更换完成"
      and rc._executing["task_b"]["vars"] == {"v": 1},
      str(rc._executing["task_b"]))
bus.publish(Events.TASK_SIGNAL, signal="更换完成", payload="")
time.sleep(0.2)
kind, rec = rc._pick_next_task()
check("G4 信号唤醒挑选", kind == "resume" and rec["name"] == "task_b"
      and rec["data"].get("wait_outcome") == "resume",
      str((kind, rec.get("data") if isinstance(rec, dict) else None)))
rc._executing.pop("task_b", None)
# 超时唤醒
rc._task_pause = {"pause_node": "w1", "vars": {}, "graph_data": {},
                  "pause_signal": "", "pause_seconds": 0}
rc._store_pause_record("task_b")
rc._check_paused_timeouts()
kind2, rec2 = rc._pick_next_task()
check("G5 超时唤醒走 timeout", kind2 == "resume"
      and rec2["data"].get("wait_outcome") == "timeout",
      str(rec2.get("data") if isinstance(rec2, dict) else None))
rc._executing.pop("task_b", None)

# 调度器分支：enqueue_pending 激活
sched2 = _FakeSched()
rc2 = RunController(scheduler=sched2, connection=None, config=None,
                    state_mgr=None, registry=_FakeRegistry(
                        {"task_c": _def_with_ops("enqueue_pending")}),
                    executor=None, recognizer=None, event_bus=EventBus(),
                    monitor=None, account_mgr=None)
rc2._rebuild_trigger_index()
rc2._on_task_signal(signal="更换阵容", payload="")
check("G6 pending 激活入待执行", sched2.calls[:1] == [("pending", "task_c")],
      str(sched2.calls))

# ── 收尾 ────────────────────────────────────────────
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QEvent
for w in QApplication.topLevelWidgets():
    try:
        w.hide()
        w.deleteLater()
    except Exception:
        pass
QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
QApplication.processEvents()

passed = sum(1 for _, ok in results if ok)
print(f"TOTAL {passed}/{len(results)}")
sys.stdout.flush()
os._exit(0 if passed == len(results) else 1)
