"""
17-可视化构建模块：可视化任务数据结构（P0 骨架）。

节点图 = 统一任务形态（4.25）：任务 = 节点图 JSON + 示教产物（场景/点击点/OCR区域）。
所有内容存 games/{game}/visual_tasks/{name}.json（4.24 边界原则：骨架零游戏内容）。

节点图模型（与 NodeGraphQt serialize_session 兼容 + 扩展任务语义）：
{
  "name": "task_name",
  "display_name": "显示名",
  "category": "daily",
  "version": 1,
  "settings": { "match_threshold": 0.85, "unknown_policy": "block" },
  "graph": {
    "nodes": [ {"id": "..", "type": "clicker", "name": "..", "pos": [x,y],
                "params": {...}, "selected": false} ],
    "connections": [ {"id": "..", "in_node": "..", "in_port": "..",
                      "out_node": "..", "out_port": ".."} ]
  },
  "teach": { "scenes": [...], "points": [...], "ocr_regions": [...] }
}
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

# ── 版本 ─────────────────────────────────────────────────────
SCHEMA_VERSION: int = 1


# ── 坐标工具 ─────────────────────────────────────────────────
def rel_to_abs(x: float, y: float, w: int, h: int) -> tuple[int, int]:
    """相对坐标（0~1）→ 绝对像素坐标"""
    return int(x * w), int(y * h)


def abs_to_rel(x: float, y: float, w: int, h: int) -> tuple[float, float]:
    """绝对像素坐标 → 相对坐标（0~1）"""
    if w <= 0 or h <= 0:
        return 0.0, 0.0
    return round(x / w, 4), round(y / h, 4)


def normalize_region(region: list | tuple | None,
                     mode: str = "relative") -> list | None:
    """规范区域为 [x, y, w, h] 列表；relative 模式 0~1，absolute 模式像素。"""
    if not region or len(region) != 4:
        return None
    return [float(region[0]), float(region[1]),
            float(region[2]), float(region[3])]


def region_to_abs(region: list | None, w: int, h: int) -> tuple | None:
    """相对区域 → 绝对像素 (x, y, w, h)；已是绝对或 None 原样返回"""
    if not region or len(region) != 4:
        return None
    if all(0.0 <= v <= 1.0 for v in region[:2]) and region[2] <= 1.0 and region[3] <= 1.0:
        return (int(region[0] * w), int(region[1] * h),
                int(region[2] * w), int(region[3] * h))
    return tuple(int(v) for v in region)


# ── 节点图模型 ───────────────────────────────────────────────
def new_node(node_type: str, name: str = "", pos: list | None = None) -> dict:
    """创建一个节点 dict（id 自动生成）"""
    return {
        "id": uuid.uuid4().hex[:12],
        "type": node_type,
        "name": name or node_type,
        "pos": pos or [0, 0],
        "params": {},
        "selected": False,
    }


def new_connection(in_node: str, in_port: str,
                   out_node: str, out_port: str) -> dict:
    """创建一条连线 dict"""
    return {
        "id": uuid.uuid4().hex[:12],
        "in_node": in_node,
        "in_port": in_port,
        "out_node": out_node,
        "out_port": out_port,
    }


def default_graph() -> dict:
    """空图：仅一个 Start 节点"""
    start = new_node("start", name="开始")
    return {"nodes": [start], "connections": []}


def find_node(graph: dict, node_id: str) -> dict | None:
    for n in graph.get("nodes", []):
        if n.get("id") == node_id:
            return n
    return None


def find_node_by_type(graph: dict, node_type: str) -> dict | None:
    for n in graph.get("nodes", []):
        if n.get("type") == node_type:
            return n
    return None


# ── 任务模型 ─────────────────────────────────────────────────
def default_task(name: str = "new_task",
                 display_name: str = "新任务",
                 category: str = "daily") -> dict:
    return {
        "name": name,
        "display_name": display_name,
        "category": category,
        "version": SCHEMA_VERSION,
        "settings": {
            "match_threshold": 0.85,
            "unknown_policy": "block",   # block / skip / fail
        },
        "graph": default_graph(),
        "teach": {
            "scenes": [],      # Scene dicts
            "points": [],      # TeachPoint dicts
            "ocr_regions": [], # OCRRegion dicts
        },
    }


def load_task(path: str | Path) -> dict:
    """从 JSON 加载可视化任务；缺失字段补默认值"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return normalize_task(data)


def save_task(path: str | Path, task: dict) -> None:
    """原子保存可视化任务 JSON"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def normalize_task(task: dict) -> dict:
    """补全缺失字段，返回规范化的任务 dict"""
    base = default_task()
    base.update(task)
    base.setdefault("version", SCHEMA_VERSION)
    base["settings"] = {**base.get("settings", {}), **task.get("settings", {})}
    if "graph" not in base or not base.get("graph"):
        base["graph"] = default_graph()
    base["graph"].setdefault("nodes", [])
    base["graph"].setdefault("connections", [])
    base.setdefault("teach", {"scenes": [], "points": [], "ocr_regions": []})
    base["teach"].setdefault("scenes", [])
    base["teach"].setdefault("points", [])
    base["teach"].setdefault("ocr_regions", [])
    return base


# ── 示教产物辅助 ─────────────────────────────────────────────
def add_scene(task: dict, scene: dict) -> None:
    task["teach"]["scenes"] = [s for s in task["teach"]["scenes"]
                               if s.get("id") != scene.get("id")]
    task["teach"]["scenes"].append(scene)


def add_point(task: dict, point: dict) -> None:
    task["teach"]["points"] = [p for p in task["teach"]["points"]
                               if p.get("id") != point.get("id")]
    task["teach"]["points"].append(point)


def add_ocr_region(task: dict, region: dict) -> None:
    task["teach"]["ocr_regions"] = [r for r in task["teach"]["ocr_regions"]
                                    if r.get("id") != region.get("id")]
    task["teach"]["ocr_regions"].append(region)


def find_scene(task: dict, scene_id: str) -> dict | None:
    for s in task["teach"].get("scenes", []):
        if s.get("id") == scene_id:
            return s
    return None


def find_point(task: dict, point_id: str) -> dict | None:
    for p in task["teach"].get("points", []):
        if p.get("id") == point_id:
            return p
    return None


def find_ocr_region(task: dict, region_id: str) -> dict | None:
    for r in task["teach"].get("ocr_regions", []):
        if r.get("id") == region_id:
            return r
    return None


# ── 参数上浮（4.27）──────────────────────────────────────────
def collect_task_params(task: dict,
                        operation_provider) -> list[dict]:
    """扫描图中所有 operation 节点，收集 hoist 参数 → 任务 params 列表。

    每个 hoist 输入生成：
      {"path": "ops.<op>.<input>", "label": ..., "type": ...,
       "options": [...], "default": ..., "operation": ..., "input": ...}
    """
    params: list[dict] = []
    seen: set[tuple] = set()
    for node in task.get("graph", {}).get("nodes", []):
        if node.get("type") != "operation":
            continue
        op_name = node.get("params", {}).get("operation", "")
        if not op_name:
            continue
        op = operation_provider(op_name) if operation_provider else None
        if op is None:
            continue
        for inp in op.get("inputs", []):
            if not inp.get("hoist"):
                continue
            key = (op_name, inp["name"])
            if key in seen:
                continue
            seen.add(key)
            params.append({
                "path": f"ops.{op_name}.{inp['name']}",
                "label": inp.get("label", inp["name"]),
                "type": inp.get("type", "text"),
                "options": list(inp.get("options", [])),
                "default": inp.get("default", ""),
                "operation": op_name,
                "input": inp["name"],
            })
    return params
