"""17-可视化构建模块：进度组布局 + 运行时进度跟踪（2026-08-16）。

进度组 = 画布框选右键「保存为进度节点」的节点集合（任务中有几个框选 → UI 几个 o）。
循环 = 循环节点 + 循环体整体框选为一个 o（不显示 n/m 圈数）。

- build_progress_layout：图 → 缩略图布局（主行横排、分支下挂，线性树形）
- ProgressTracker：执行事件驱动状态机
    o 状态：执行中=蓝 / 完成=绿 / 失败=红 / 未执行=灰
    边状态：执行游标位于两组之间（未框住节点在执行）→ 蓝色箭头，其余灰线
- 每次 TASK_STARTED 重置全灰（由调用方 reset）
"""
from __future__ import annotations

from typing import Any, Callable

from visual import visual_schema as vs

# 分支端口（布局时从主路径分叉出子行；loop_back 参与循环组，不单独分叉）
_BRANCH_PORTS = ("true", "false", "not_found", "miss", "triggered", "done")


def build_progress_layout(graph: dict, groups: list[dict],
                          ordered: bool = False) -> dict:
    """图 + 进度组 → 缩略图布局。

    ordered=True（2026-08-16 阶段标签）：不依赖连线，直接按组顺序排
    o-o-o（信号接收器导致节点不连贯时也能展示）。

    返回 {
      points: [{id, name, row, col}]      行=主行 0，分支行递增；列=行内序号
      edges:  [{from, to, nodes, branch}]  nodes=两点之间未框住的节点
    }
    """
    if ordered:
        pts = [{"id": g["id"], "name": g.get("name") or g["id"],
                "row": 0, "col": i} for i, g in enumerate(groups)]
        edges = [{"from": groups[i]["id"], "to": groups[i + 1]["id"],
                  "nodes": [], "branch": False}
                 for i in range(len(groups) - 1)]
        return {"points": pts, "edges": edges}
    gmap: dict[str, str] = {}
    for g in groups:
        for nid in g.get("nodes") or []:
            gmap[str(nid)] = g["id"]
    conns = graph.get("connections", [])
    outs: dict[tuple[str, str], tuple[str, str]] = {}
    for c in conns:
        outs[(c["out_node"], c.get("out_port", "out"))] = (
            c["in_node"], c.get("in_port", "in"))
    members = {g["id"]: {str(n) for n in (g.get("nodes") or [])} for g in groups}

    def group_exit(gid: str) -> str | None:
        """组内节点 → 组外节点的第一条出边（含 done 等分支端口；loop_back 在组内忽略）"""
        ms = members.get(gid, set())
        for c in conns:
            if c["out_node"] in ms and c["in_node"] not in ms:
                return c["in_node"]
        return None

    rows: list[list[str]] = [[]]
    points: list[dict] = []
    edges: list[dict] = []
    visited: set[str] = set()
    placed: set[str] = set()

    def add_point(gid: str, row: int) -> bool:
        if gid in placed:
            return False
        if rows[row] and rows[row][-1] == gid:
            return False
        rows[row].append(gid)
        points.append({"id": gid, "row": row, "col": len(rows[row]) - 1})
        placed.add(gid)
        return True

    def walk(nid: str, row: int, last_point: str | None):
        """沿 out 主路径走；遇进度组记录点；未框住节点上的分支端口递归生成子行"""
        cur: str | None = nid
        path: list[str] = []
        while cur is not None and cur not in visited:
            visited.add(cur)
            gid = gmap.get(cur)
            if gid is not None:
                if last_point is not None and last_point != gid:
                    edges.append({"from": last_point, "to": gid,
                                  "nodes": list(path), "branch": False})
                if add_point(gid, row):
                    last_point = gid
                else:
                    # 已布局过的点（汇聚）→ 加回边后停止继续走
                    if last_point is not None and last_point != gid:
                        edges.append({"from": last_point, "to": gid,
                                      "nodes": list(path), "branch": True})
                    return
                path = []
                cur = group_exit(gid)
                continue
            path.append(cur)
            # 分支端口 → 子行
            for port in _BRANCH_PORTS:
                tgt = outs.get((cur, port))
                if tgt and tgt[0] not in visited:
                    new_row = len(rows)
                    rows.append([])
                    walk(tgt[0], new_row, None)
                    if last_point is not None and rows[new_row]:
                        edges.append({"from": last_point, "to": rows[new_row][0],
                                      "nodes": [cur], "branch": True})
            nxt = outs.get((cur, "out"))
            if nxt is None:
                break
            cur = nxt[0]

    start = vs.find_node_by_type(graph, "start")
    if start is not None:
        walk(start["id"], 0, None)
    # 兜底：未连入主流程的组（最下一行）
    for g in groups:
        if g["id"] not in placed:
            new_row = len(rows)
            rows.append([])
            add_point(g["id"], new_row)

    # 回填 name
    names = {g["id"]: g.get("name") or g["id"] for g in groups}
    for p in points:
        p["name"] = names.get(p["id"], p["id"])
    return {"points": points, "edges": edges}


class ProgressTracker:
    """单任务执行进度状态机（2026-08-16）。"""

    def __init__(self, task_id: str, graph: dict, groups: list[dict],
                 publish: Callable | None = None, ordered: bool = False):
        self.task_id = task_id
        self.groups = {g["id"]: g for g in groups}
        self.layout = build_progress_layout(graph, groups, ordered=ordered)
        self._publish = publish
        self._node_group: dict[str, str] = {}
        for g in groups:
            for nid in g.get("nodes") or []:
                self._node_group[str(nid)] = g["id"]
        self._node_edge: dict[str, list] = {}
        for e in self.layout["edges"]:
            for nid in e.get("nodes", []):
                self._node_edge.setdefault(nid, []).append(e)
        self._last_snapshot = ""
        self.reset(publish_initial=True)

    # ── 状态机 ─────────────────────────────────────────
    def reset(self, publish_initial: bool = False) -> None:
        self._states = {p["id"]: "gray" for p in self.layout["points"]}
        self._active_edge_ids: set[int] = set()
        self._last_group: str | None = None
        if publish_initial:
            self._emit()

    def node_started(self, node_id: str) -> None:
        changed = False
        gid = self._node_group.get(node_id)
        if gid is not None:
            if (self._last_group and self._last_group != gid
                    and self._states.get(self._last_group) == "blue"):
                self._states[self._last_group] = "green"
                changed = True
            self._last_group = gid
            if self._states.get(gid) != "red" and self._states.get(gid) != "blue":
                self._states[gid] = "blue"
                changed = True
            if self._active_edge_ids:
                self._active_edge_ids = set()
                changed = True
        else:
            if (self._last_group
                    and self._states.get(self._last_group) == "blue"):
                self._states[self._last_group] = "green"
                changed = True
            self._last_group = None
            es = self._node_edge.get(node_id)
            new_act = {id(e) for e in (es or [])}
            if new_act != self._active_edge_ids:
                self._active_edge_ids = new_act
                changed = True
        if changed:
            self._emit()

    def node_finished(self, node_id: str, status: str) -> None:
        if status == "error":
            gid = self._node_group.get(node_id)
            if gid and self._states.get(gid) != "red":
                self._states[gid] = "red"
                self._last_group = None
                self._active_edge_ids = set()
                self._emit()

    def task_done(self) -> None:
        """任务正常结束：最后一个执行中的组 → 绿"""
        if (self._last_group
                and self._states.get(self._last_group) == "blue"):
            self._states[self._last_group] = "green"
            self._active_edge_ids = set()
            self._emit()

    # ── 快照 ───────────────────────────────────────────
    def _current_name(self) -> str:
        """当前步骤名：蓝点 > 红点(失败) > 游标边指向的下一个点"""
        names = {p["id"]: p.get("name", p["id"]) for p in self.layout["points"]}
        for p in self.layout["points"]:
            if self._states.get(p["id"]) == "blue":
                return names[p["id"]]
        for p in self.layout["points"]:
            if self._states.get(p["id"]) == "red":
                return names[p["id"]] + "（失败）"
        for e in self.layout["edges"]:
            if id(e) in self._active_edge_ids:
                return "→ " + names.get(e["to"], e["to"])
        return ""

    def snapshot(self) -> dict:
        return {
            "task_id": self.task_id,
            "current": self._current_name(),
            "points": [dict(p) for p in self.layout["points"]],
            "states": dict(self._states),
            "edges": [{
                "from": e["from"],
                "to": e["to"],
                "branch": bool(e.get("branch")),
                "active": id(e) in self._active_edge_ids,
            } for e in self.layout["edges"]],
        }

    def _emit(self) -> None:
        if self._publish is None:
            return
        import json
        snap = self.snapshot()
        key = json.dumps(snap, sort_keys=True, ensure_ascii=False)
        if key == self._last_snapshot:
            return
        self._last_snapshot = key
        try:
            self._publish(snap)
        except Exception:
            pass
