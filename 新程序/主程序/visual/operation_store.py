"""
17-可视化构建模块：通用操作存储（P2，4.26 Operation）。

操作 = 可复用、参数化的子图（一组节点 + 输入参数 + 输出），
可被任务图中的「操作节点」引用、内联执行、嵌套引用其他操作。

存储（4.26 分层）：
- 跨游戏通用操作：games/_shared/operations/{name}.json
- 游戏内共享操作：games/{game}/operations/{name}.json

操作定义结构：
{
  "name": "configure_team",
  "display_name": "配置阵容",
  "inputs": [
    {"name": "team", "type": "text", "hoist": true, "label": "队伍", "default": "主力"}
  ],
  "graph": { "nodes": [...], "connections": [...] }   # 子图（含 start/end）
}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from visual import visual_schema as vs


class OperationStore:
    """通用操作存储（多目录：共享 + 游戏内）"""

    def __init__(self, dirs: list[str | Path] | None = None):
        """dirs: 按优先级排列的存储目录（后写先读）"""
        self._dirs: list[Path] = [Path(d) for d in (dirs or [])]
        for d in self._dirs:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def dirs(self) -> list[Path]:
        return self._dirs

    # ── 枚举 / 定位 ──────────────────────────────────────
    def _path_of(self, name: str) -> Path | None:
        safe = "".join(c for c in str(name) if c.isalnum() or c in "_-.")
        for d in self._dirs:
            p = d / f"{safe}.json"
            if p.exists():
                return p
        return None

    def _write_path(self, name: str) -> Path:
        safe = "".join(c for c in str(name) if c.isalnum() or c in "_-.")
        # 写到第一个（优先级最高）目录；无目录时回退当前目录
        base = self._dirs[0] if self._dirs else Path(".")
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{safe}.json"

    def list(self) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        for d in self._dirs:
            if not d.exists():
                continue
            for p in sorted(d.glob("*.json")):
                if p.name.startswith("."):
                    continue
                try:
                    op = vs.load_task(p)  # 复用任务 JSON 加载
                except Exception:
                    continue
                name = op.get("name", p.stem)
                if name in seen:
                    continue  # 高优先级目录已收录
                seen.add(name)
                out.append({
                    "name": name,
                    "display_name": op.get("display_name", name),
                    "input_count": len(op.get("inputs", [])),
                    "node_count": len(op.get("graph", {}).get("nodes", [])),
                })
        return out

    def names(self) -> list[str]:
        return [o["name"] for o in self.list()]

    def load(self, name: str) -> dict:
        p = self._path_of(name)
        if p is None:
            raise FileNotFoundError(f"操作不存在: {name}")
        op = vs.load_task(p)
        op.setdefault("inputs", [])
        op.setdefault("display_name", name)
        return op

    def save(self, operation: dict) -> None:
        name = operation.get("name", "")
        if not name:
            raise ValueError("操作缺少 name")
        operation = vs.normalize_task(operation)
        operation.setdefault("inputs", [])
        p = self._write_path(name)
        vs.save_task(p, operation)

    def delete(self, name: str) -> bool:
        p = self._path_of(name)
        if p is not None:
            p.unlink()
            return True
        return False

    def exists(self, name: str) -> bool:
        return self._path_of(name) is not None

    def create(self, name: str, display_name: str = "") -> dict:
        """新建默认操作（空子图：Start→End）"""
        if self.exists(name):
            raise FileExistsError(f"操作已存在: {name}")
        graph = {"nodes": [], "connections": []}
        start = vs.new_node("start", name="开始")
        end = vs.new_node("end", name="结束")
        graph["nodes"] = [start, end]
        graph["connections"] = [
            vs.new_connection(end["id"], "in", start["id"], "out"),
        ]
        op = vs.default_task(name, display_name or name, "operation")
        op["inputs"] = []
        op["graph"] = graph
        self.save(op)
        return op

    # ── 参数上浮辅助（4.27）──────────────────────────────
    def hoisted_params(self, operation: dict) -> list[dict]:
        """返回操作中标注 hoist 的输入参数（供任务参数收集）"""
        out: list[dict] = []
        for inp in operation.get("inputs", []):
            if inp.get("hoist"):
                out.append(dict(inp))
        return out
