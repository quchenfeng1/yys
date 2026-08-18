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
    return {"nodes": [start], "connections": [], "tags": []}


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
            # 场景信号表（外置配置，2026-08-15）：识图失败且失败端口无连线时
            # 自动回查全局信号表；命中场景则激活对应信号触发器。
            "signal_table": {
                "enabled": False,       # 启用自动回查（默认关，兼容旧任务）
                "scenes": [],           # 场景 id 列表；空=场景库全部
                "retry_limit": 5,       # 连续 N 次同场景报错；0=不限
            },
        },
        "graph": default_graph(),
        # 任务素材库（2026-08-15）：只有加入的素材才出现在节点下拉
        "materials": {
            "scenes": [],     # 场景素材 id 列表（场景判定下拉）
            "elements": [],   # 图标素材相对路径列表（点击器下拉）
            "ocr": [],        # OCR 识别素材相对路径列表（OCR读取下拉）
        },
        "teach": {
            "scenes": [],      # Scene dicts
            "points": [],      # TeachPoint dicts
            "ocr_regions": [], # OCRRegion dicts
        },
        # 运行时参数值（2026-08-15）：变量组/常量组节点的键 → 实际值。
        # 变量配置 Tab 输入的值存这里；常量组值存节点定义内，运行时合并。
        "param_values": {},
        # 进度组（2026-08-16）：画布框选右键「保存为进度节点」的集合；
        # 任务队列按此渲染 o-o-o 缩略图（执行中蓝/完成绿/失败红/未执行灰）
        "progress_groups": [],
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
    st = base["settings"].setdefault("signal_table", {})
    st.setdefault("enabled", False)
    st.setdefault("scenes", [])
    st.setdefault("retry_limit", 5)
    if "graph" not in base or not base.get("graph"):
        base["graph"] = default_graph()
    base["graph"].setdefault("nodes", [])
    base["graph"].setdefault("connections", [])
    base["graph"].setdefault("tags", [])
    base.setdefault("teach", {"scenes": [], "points": [], "ocr_regions": []})
    base["teach"].setdefault("scenes", [])
    base["teach"].setdefault("points", [])
    base["teach"].setdefault("ocr_regions", [])
    base.setdefault("materials", {"scenes": [], "elements": []})
    base["materials"].setdefault("scenes", [])
    base["materials"].setdefault("elements", [])
    base["materials"].setdefault("ocr", [])
    base.setdefault("param_values", {})
    if not isinstance(base["param_values"], dict):
        base["param_values"] = {}
    base.setdefault("progress_groups", [])
    if not isinstance(base["progress_groups"], list):
        base["progress_groups"] = []
    _migrate_signal_nodes(base)
    return base


def _migrate_signal_nodes(task: dict) -> None:
    """2026-08-15 重构迁移：显式 scene_detect/scene_entry 节点 →
    外置场景信号表 + 信号触发器。

    - scene_detect：参数搬进 settings.signal_table（enabled=True），节点及连线删除
    - scene_entry：节点改名 scene_trigger（保留监听场景参数）
    """
    graph = task.get("graph") or {}
    st = task["settings"].setdefault("signal_table", {})
    nodes = graph.get("nodes", [])
    if not nodes:
        return
    removed: set = set()
    for n in nodes:
        t = n.get("type")
        if t == "scene_detect":
            p = n.get("params", {}) or {}
            st["enabled"] = True
            scenes = [s.strip() for s in str(p.get("scene_list", "") or "")
                      .replace("，", ",").split(",") if s.strip()]
            if scenes:
                st["scenes"] = scenes
            try:
                st["retry_limit"] = int(p.get("retry_limit", 5) or 5)
            except Exception:
                pass
            removed.add(n.get("id"))
        elif t == "scene_entry":
            n["type"] = "scene_trigger"
    if removed:
        graph["nodes"] = [n for n in nodes if n.get("id") not in removed]
        graph["connections"] = [c for c in graph.get("connections", [])
                                if c.get("out_node") not in removed
                                and c.get("in_node") not in removed]


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


# ── 复合节点封装（2026-08-15 重构，取代通用操作体系）────────────
def encapsulate_nodes(task: dict, node_ids: list[str]) -> tuple[str | None, str]:
    """把图中选中的节点封装成「复合节点」（单入口单出口）。

    入口 = 唯一一条 外部节点 out → 内部节点 in 的连线；
    出口 = 唯一一条 内部节点 out → 外部节点 in 的连线。

    返回 (compound_id, "") 成功；(None, 原因) 失败。
    """
    graph = task.get("graph") or {}
    nodes = graph.get("nodes", [])
    conns = graph.get("connections", [])
    ids = set(node_ids)
    inner = [n for n in nodes if n.get("id") in ids]
    if len(inner) != len(ids):
        return None, "部分节点不存在"
    if not inner:
        return None, "未选中任何节点"
    # start/end 节点不可封装（任务级语义，先于入口检查）
    for n in inner:
        if n.get("type") in ("start", "end"):
            return None, "开始/结束节点不能封装进复合节点"

    entries = [c for c in conns
               if c.get("in_node") in ids and c.get("out_node") not in ids]
    exits = [c for c in conns
             if c.get("out_node") in ids and c.get("in_node") not in ids]
    if len(entries) != 1:
        return None, f"封装要求单入口（当前 {len(entries)} 个入口），"
        f"请只保留一条外部进入的连线"
    if len(exits) != 1:
        return None, f"封装要求单出口（当前 {len(exits)} 个出口），"
        f"请只保留一条连向外部的连线"
    entry_c, exit_c = entries[0], exits[0]

    inner_conns = [c for c in conns
                   if c.get("out_node") in ids and c.get("in_node") in ids]
    comp = new_node("compound", name="复合节点")
    comp["params"] = {"source": ""}
    comp["subgraph"] = {
        "nodes": inner,
        "connections": inner_conns,
        "entry_id": entry_c.get("in_node"),
    }
    # 移除内部节点与跨边界连线；外部连线重接到复合节点
    graph["nodes"] = [n for n in nodes if n.get("id") not in ids] + [comp]
    removed = {id(entry_c), id(exit_c)}
    keep = [c for c in conns
            if not (c.get("out_node") in ids or c.get("in_node") in ids)
            and id(c) not in removed]
    keep.append(new_connection(comp["id"], "in",
                               entry_c.get("out_node"),
                               entry_c.get("out_port", "out")))
    keep.append(new_connection(exit_c.get("in_node"),
                               exit_c.get("in_port", "in"),
                               comp["id"], "out"))
    graph["connections"] = keep
    return comp["id"], ""


def find_compound_node(graph: dict, compound_id: str) -> dict | None:
    for n in graph.get("nodes", []):
        if n.get("id") == compound_id and n.get("type") == "compound":
            return n
    return None


# ═══════════════════════════════════════════════════════════════
#  变量组 / 常量组（2026-08-15）：外部参数
# ═══════════════════════════════════════════════════════════════

VAR_GROUP_NODE_TYPES = ("variable_group", "constant_group")

# 变量键合法格式（${} 解析与分支 data_source 引用依赖纯文本键）
import re as _re

_VAR_KEY_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 变量定义允许的类型（弹窗下拉 / 运行时输入控件渲染 / 值转换共用）
VAR_TYPES = ("int", "float", "text", "bool")


def is_valid_var_key(key: str) -> bool:
    return bool(key) and bool(_VAR_KEY_RE.match(key))


def collect_var_groups(graph: dict) -> list[dict]:
    """收集图中所有变量组/常量组节点定义。

    返回 [{kind, group_name, variables}]
      variable_group 变量项: {label, key, type, default}
      constant_group 变量项: {label, key, value}
    """
    out: list[dict] = []
    for n in (graph or {}).get("nodes", []):
        t = n.get("type", "")
        if t not in VAR_GROUP_NODE_TYPES:
            continue
        p = n.get("params", {}) or {}
        vars_list = p.get("variables") or []
        if not isinstance(vars_list, list):
            vars_list = []
        out.append({
            "kind": "constant_group" if t == "constant_group"
                    else "variable_group",
            "group_name": str(p.get("group_name", "") or "").strip()
                          or (n.get("name", "") or "变量组"),
            "variables": [v for v in vars_list if isinstance(v, dict)],
        })
    return out


def stage_tags(task: dict) -> list[dict]:
    """提取「设为阶段」的标签（2026-08-16）：流程示图/进度跟踪数据源。

    从 graph.tags 中取 stage=True 的标签 → [{id, name, nodes}]（按标签顺序）；
    节点 id 过滤无效项。信号接收器导致节点不连贯——阶段间无连线要求，
    展示层按标签顺序排 o-o-o。
    """
    from uuid import uuid4
    graph_ids = {n.get("id") for n in (task.get("graph", {}) or {}).get("nodes", [])}
    out: list[dict] = []
    for t in (task.get("graph", {}) or {}).get("tags", []) or []:
        if not isinstance(t, dict) or not t.get("stage"):
            continue
        nodes = [str(n) for n in (t.get("nodes") or []) if str(n) in graph_ids]
        if not nodes:
            continue
        out.append({
            "id": str(t.get("id", "") or "").strip() or uuid4().hex[:12],
            "name": str(t.get("name", "") or "").strip()
                    or f"阶段{len(out) + 1}",
            "nodes": nodes,
        })
    return out


def normalize_progress_groups(task: dict) -> list[dict]:
    """规范化进度组（2026-08-16）：过滤空组/无效节点，节点只属于一个组（先组优先）。"""
    from uuid import uuid4
    graph_ids = {n.get("id") for n in (task.get("graph", {}) or {}).get("nodes", [])}
    out: list[dict] = []
    seen_nodes: set[str] = set()
    for g in (task.get("progress_groups") or []):
        if not isinstance(g, dict):
            continue
        raw_nodes = g.get("nodes") or []
        nodes = [str(n) for n in raw_nodes if str(n) in graph_ids]
        nodes = [n for n in nodes if n not in seen_nodes]
        if not nodes:
            continue
        seen_nodes.update(nodes)
        out.append({
            "id": str(g.get("id", "") or "") or uuid4().hex[:12],
            "name": str(g.get("name", "") or "").strip()
                    or f"进度{len(out) + 1}",
            "nodes": nodes,
        })
    return out


def callable_var_defs(graph: dict) -> dict[str, dict]:
    """可调用变量定义（2026-08-16）：{变量键: {label, type, default}}。

    变量组定义中勾选「可调用」的变量才会被「参数处理」节点处理；
    其运行值跨运行保留（callable_vars 存储），UI 默认锁编辑。
    """
    out: dict[str, dict] = {}
    for g in collect_var_groups(graph):
        if g.get("kind") != "variable_group":
            continue
        for v in g.get("variables", []):
            if not isinstance(v, dict) or not v.get("callable"):
                continue
            key = str(v.get("key", "") or "").strip()
            if not key:
                continue
            out[key] = {
                "label": str(v.get("label", "") or key),
                "type": str(v.get("type", "text") or "text"),
                "default": v.get("default"),
            }
    return out


def check_var_conflicts(groups: list[dict]) -> list[str]:
    """跨组/组内/常量冲突检测，返回错误描述列表（空=无冲突）。

    - 组名重复
    - 变量键跨组重复（含变量组与常量组之间）
    - 组内键重复
    """
    errors: list[str] = []
    group_names: dict[str, str] = {}
    keys: dict[str, str] = {}
    for g in groups:
        gname = g.get("group_name", "")
        kind = "常量组" if g.get("kind") == "constant_group" else "变量组"
        if gname in group_names:
            errors.append(f"变量组名「{gname}」重复")
        else:
            group_names[gname] = kind
        seen_in_group: set[str] = set()
        for v in g.get("variables", []):
            key = str(v.get("key", "") or "").strip()
            if not key:
                continue
            if key in seen_in_group:
                errors.append(f"{kind}「{gname}」内变量键「{key}」重复")
                continue
            seen_in_group.add(key)
            if key in keys:
                errors.append(
                    f"变量键「{key}」在「{keys[key]}」与「{kind}「{gname}」」"
                    f"中重复")
            else:
                keys[key] = f"{kind}「{gname}」"
    return errors


def _resolve_refs_in(value: Any, values: dict) -> Any:
    """字符串值内的 ${key} → 实际值（未命中保留原样）"""
    if not isinstance(value, str) or "${" not in value:
        return value
    out = value
    for k, v in values.items():
        out = out.replace("${%s}" % k, str(v))
    return out


def resolve_param_refs(graph: dict, values: dict) -> dict:
    """深拷贝图并把所有节点参数（含复合子图）中的 ${key} 替换为实际值。

    运行时入口调用：不污染保存的任务文件。未命中键原样保留。
    """
    import copy
    g = copy.deepcopy(graph or {})
    if not values:
        return g
    for n in g.get("nodes", []):
        p = n.get("params")
        if isinstance(p, dict):
            for k, v in p.items():
                if isinstance(v, str):
                    p[k] = _resolve_refs_in(v, values)
                elif isinstance(v, list):
                    p[k] = [_resolve_refs_in(x, values) for x in v]
        sub = n.get("subgraph")
        if isinstance(sub, dict):
            n["subgraph"] = resolve_param_refs(sub, values)
    return g


def effective_param_values(task: dict, overrides: dict | None = None) -> dict:
    """合并有效参数值：常量组定义值 + 任务 param_values + 运行时覆盖（后者优先）。

    类型转换：按变量定义类型转 int/float/bool/text。
    """
    values: dict = {}
    types: dict[str, str] = {}
    groups = collect_var_groups(task.get("graph", {}))
    for g in groups:
        for v in g.get("variables", []):
            key = str(v.get("key", "") or "").strip()
            if not key:
                continue
            if g.get("kind") == "constant_group":
                values[key] = v.get("value")
            else:
                types[key] = str(v.get("type", "text") or "text")
                if key not in values:
                    values[key] = v.get("default")
    stored = (task.get("param_values") or {})
    if isinstance(stored, dict):
        values.update(stored)
    if overrides:
        values.update(overrides)
    # 类型转换
    for k, t in types.items():
        v = values.get(k)
        try:
            if t == "int":
                values[k] = int(float(v))
            elif t == "float":
                values[k] = float(v)
            elif t == "bool":
                values[k] = str(v).strip().lower() in ("1", "true", "yes", "是")
            else:
                values[k] = "" if v is None else str(v)
        except Exception:
            values[k] = v
    return values
