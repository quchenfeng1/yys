"""
17-可视化构建模块：通用节点库（CompoundStore，2026-08-15 重构）。

取代旧的「通用任务/操作」（Operation）体系：在画布上框选部分节点
封装成「复合节点」后，可保存为「通用节点」，供同游戏任务复用。

存储：
- 跨游戏共享：games/_shared/nodes/{name}.json
- 游戏内：games/{game}/nodes/{name}.json

节点结构：
{ "name", "display_name", "category", "subgraph": {nodes, connections, entry_id} }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from visual import visual_schema as vs


class CompoundStore:
    """通用节点库（多目录：共享 + 游戏内）"""

    def __init__(self, dirs: list[str | Path] | None = None):
        self._dirs: list[Path] = [Path(d) for d in (dirs or [])]
        for d in self._dirs:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def dirs(self) -> list[Path]:
        return self._dirs

    # ── 路径 ────────────────────────────────────────────
    @staticmethod
    def _safe(name: str) -> str:
        return "".join(c for c in str(name) if c.isalnum() or c in "_-.")

    def _path_of(self, name: str) -> Path | None:
        safe = self._safe(name)
        for d in self._dirs:
            p = d / f"{safe}.json"
            if p.exists():
                return p
        return None

    def _write_path(self, name: str) -> Path:
        safe = self._safe(name)
        base = self._dirs[0] if self._dirs else Path(".")
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{safe}.json"

    # ── 枚举 / 读取 ─────────────────────────────────────
    def list(self) -> list[dict]:
        """全部通用节点 [{name, display_name, node_count}]"""
        out: list[dict] = []
        seen: set[str] = set()
        for d in self._dirs:
            if not d.exists():
                continue
            for p in sorted(d.glob("*.json")):
                if p.name.startswith("."):
                    continue
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                name = data.get("name") or p.stem
                if name in seen:
                    continue
                seen.add(name)
                out.append({
                    "name": name,
                    "display_name": data.get("display_name", name),
                    "node_count": len(data.get("subgraph", {})
                                      .get("nodes", [])),
                })
        return out

    def names(self) -> list[str]:
        return [n["name"] for n in self.list()]

    def load(self, name: str) -> dict | None:
        p = self._path_of(name)
        if p is None:
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data.setdefault("name", p.stem)
            data.setdefault("display_name", p.stem)
            data.setdefault("subgraph", {"nodes": [], "connections": [],
                                         "entry_id": ""})
            return data
        except Exception:
            return None

    def exists(self, name: str) -> bool:
        return self._path_of(name) is not None

    # ── 写 / 删 ─────────────────────────────────────────
    def save(self, node_def: dict) -> None:
        name = node_def.get("name", "")
        if not name:
            raise ValueError("通用节点缺少 name")
        node_def.setdefault("display_name", name)
        node_def.setdefault("subgraph",
                            {"nodes": [], "connections": [], "entry_id": ""})
        p = self._write_path(name)
        p.write_text(json.dumps(node_def, ensure_ascii=False, indent=2),
                     encoding="utf-8")

    def delete(self, name: str) -> bool:
        p = self._path_of(name)
        if p is not None:
            p.unlink()
            return True
        return False
