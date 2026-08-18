"""验证：进度组布局 + 执行进度状态机（2026-08-16）。

覆盖：
1. build_progress_layout：主行点顺序、分支下挂子行、循环整体=一个点、分支边
2. ProgressTracker 状态机：灰→蓝→绿；失败→红；组间游标边激活（多边分叉）
3. 快照发布：变化才发；reset 发布初始全灰
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
from visual.progress_tracker import build_progress_layout, ProgressTracker


def _node(nid, ntype, **params):
    return {"id": nid, "type": ntype, "name": ntype,
            "pos": [0, 0], "params": params}


def _conn(o, op, i, ip="in"):
    return {"id": "c", "out_node": o, "out_port": op,
            "in_node": i, "in_port": ip}


def _graph():
    """s → [G1: loop+body] → branch → true:[G2 c1] / false:[G3 c2] → end"""
    return {
        "nodes": [
            _node("s", "start"),
            _node("l", "loop"), _node("b", "wait"),
            _node("br", "branch"), _node("c1", "wait"), _node("c2", "wait"),
            _node("e1", "end"), _node("e2", "end"),
        ],
        "connections": [
            _conn("s", "out", "l"),
            _conn("l", "out", "b"),
            _conn("b", "out", "l", "loop_back"),
            _conn("l", "done", "br"),
            _conn("br", "true", "c1"),
            _conn("br", "false", "c2"),
            _conn("c1", "out", "e1"),
            _conn("c2", "out", "e2"),
        ],
    }


_GROUPS = [
    {"id": "g1", "name": "循环战斗", "nodes": ["l", "b"]},
    {"id": "g2", "name": "胜利", "nodes": ["c1"]},
    {"id": "g3", "name": "失败", "nodes": ["c2"]},
]


def test_layout():
    lay = build_progress_layout(_graph(), _GROUPS)
    points = {p["id"]: p for p in lay["points"]}
    assert set(points) == {"g1", "g2", "g3"}, points
    # g1 主行第 0 位；g2/g3 分支子行
    assert points["g1"]["row"] == 0 and points["g1"]["col"] == 0
    assert points["g2"]["row"] == 1 and points["g3"]["row"] == 2, points
    # 分支边：g1 → g2（经 br）、g1 → g3（经 br）
    br_edges = [e for e in lay["edges"] if e.get("branch")]
    assert len(br_edges) == 2, lay["edges"]
    assert {e["from"] for e in br_edges} == {"g1"}
    assert {e["to"] for e in br_edges} == {"g2", "g3"}
    assert all(e["nodes"] == ["br"] for e in br_edges)
    # 名字回填
    assert points["g1"]["name"] == "循环战斗"
    print("  ✅ 布局：主行+分支子行，循环整体=1 点，分支边含游标节点")


def test_tracker():
    published = []
    tr = ProgressTracker("demo", _graph(), _GROUPS,
                         publish=lambda s: published.append(s))
    assert len(published) == 1 and all(
        st == "gray" for st in published[0]["states"].values())
    # s（未分组、无游标边）→ 无变化
    tr.node_started("s")
    assert len(published) == 1
    # 进入 g1 → 蓝
    tr.node_started("l")
    assert published[-1]["states"]["g1"] == "blue"
    tr.node_started("b")   # 循环体内 → 仍蓝，无新快照
    assert published[-1]["states"]["g1"] == "blue"
    # 循环回 loop 节点 → 同组内，仍蓝
    tr.node_started("l")
    assert published[-1]["states"]["g1"] == "blue"
    # br（未分组，分叉点）→ g1 绿 + 两条分支边都激活
    tr.node_started("br")
    snap = published[-1]
    assert snap["states"]["g1"] == "green"
    active = [e for e in snap["edges"] if e["active"]]
    assert len(active) == 2 and {e["to"] for e in active} == {"g2", "g3"}
    # 走 true 路 → g2 蓝、游标边清空
    tr.node_started("c1")
    snap = published[-1]
    assert snap["states"]["g2"] == "blue"
    assert not any(e["active"] for e in snap["edges"])
    # 失败 → g2 红
    tr.node_finished("c1", "error")
    assert published[-1]["states"]["g2"] == "red"
    # 重新模拟成功路径：reset 后 e1 → g2 蓝
    tr.reset()
    tr.node_started("c1")
    assert published[-1]["states"]["g2"] == "blue"
    tr.node_started("e1")
    assert published[-1]["states"]["g2"] == "green"
    # 任务结束：无残留蓝
    tr.task_done()
    assert all(st != "blue" for st in published[-1]["states"].values())
    print("  ✅ 状态机：灰→蓝→绿 / 失败红 / 分叉双蓝箭头 / reset 全灰")


if __name__ == "__main__":
    test_layout()
    test_tracker()
    print("\n🎉 verify_visual_progress 全部通过")
