"""
17-可视化构建模块：规则库存储（P0，4.24 边界原则）。

可视化任务存 games/{game}/visual_tasks/{name}.json：
- 任务 = 节点图 + 示教产物（场景/点击点/OCR区域）— 全部游戏数据
- 骨架（节点类型/执行器）在 visual/ 包，零游戏内容

提供 CRUD + 枚举；UI 与注册中心共用。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from visual import visual_schema as vs


class VisualTaskStore:
    """可视化任务存储（目录 = games/{game}/visual_tasks/）"""

    def __init__(self, visual_dir: str | Path):
        self._dir = Path(visual_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def dir(self) -> Path:
        return self._dir

    # ── 枚举 ──────────────────────────────────────────────
    def list(self) -> list[dict]:
        """列出全部任务 [{name, display_name, category, mtime, node_count}]"""
        out: list[dict] = []
        for p in sorted(self._dir.glob("*.json")):
            if p.name.startswith("."):
                continue
            try:
                task = vs.load_task(p)
            except Exception:
                continue
            out.append({
                "name": task.get("name", p.stem),
                "display_name": task.get("display_name", p.stem),
                "category": task.get("category", "daily"),
                "mtime": p.stat().st_mtime,
                "node_count": len(task.get("graph", {}).get("nodes", [])),
            })
        return out

    def names(self) -> list[str]:
        return [t["name"] for t in self.list()]

    # ── CRUD ──────────────────────────────────────────────
    def load(self, name: str) -> dict:
        path = self._path_of(name)
        if not path.exists():
            raise FileNotFoundError(f"可视化任务不存在: {name}")
        return vs.load_task(path)

    def save(self, task: dict) -> None:
        name = task.get("name", "")
        if not name:
            raise ValueError("可视化任务缺少 name")
        vs.save_task(self._path_of(name), vs.normalize_task(task))

    def delete(self, name: str) -> bool:
        path = self._path_of(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def create(self, name: str, display_name: str = "",
               category: str = "daily") -> dict:
        """新建默认任务（含 Start 节点）"""
        if not name:
            raise ValueError("任务名不能为空")
        if self._path_of(name).exists():
            raise FileExistsError(f"可视化任务已存在: {name}")
        task = vs.default_task(name, display_name or name, category)
        self.save(task)
        return task

    def exists(self, name: str) -> bool:
        return self._path_of(name).exists()

    # ── 素材目录 ──────────────────────────────────────────
    def task_assets_dir(self, name: str) -> Path:
        """任务素材子目录 games/{game}/visual_tasks/assets/{name}/（示教模板）"""
        d = self._dir / "assets" / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── 内部 ──────────────────────────────────────────────
    def _path_of(self, name: str) -> Path:
        # 安全化文件名（防路径穿越）
        safe = "".join(c for c in str(name) if c.isalnum() or c in "_-.")
        return self._dir / f"{safe}.json"
