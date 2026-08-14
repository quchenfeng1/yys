"""
17-可视化构建模块：识别素材库（SceneStore，2026-08-14）。

场景（识别素材）= 一张目标图的识别特征集合：
  { "id", "name", "judgements": [...], "logic": "and"/"or" }

「图像识别」节点（scene_probe）绑定 scene_id 后即可判断当前画面
是否命中该识别素材（true→out / false→not_found）。

存储（与通用操作库同层）：
- 跨游戏共享：games/_shared/scenes/{id}.json
- 游戏内共享：games/{game}/scenes/{id}.json

一次示教保存后，同游戏内所有任务的其他识图节点都能直接选用，
无需重复示教。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SceneStore:
    """识别素材库（多目录：共享 + 游戏内）"""

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

    def _path_of(self, scene_id: str) -> Path | None:
        safe = self._safe(scene_id)
        for d in self._dirs:
            p = d / f"{safe}.json"
            if p.exists():
                return p
        return None

    def _write_path(self, scene_id: str) -> Path:
        safe = self._safe(scene_id)
        base = self._dirs[0] if self._dirs else Path(".")
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{safe}.json"

    # ── 枚举 / 读取 ─────────────────────────────────────
    def list(self) -> list[dict]:
        """全部识别素材 [{id, name}]"""
        out: list[dict] = []
        seen: set[str] = set()
        for d in self._dirs:
            if not d.exists():
                continue
            for p in sorted(d.glob("*.json")):
                if p.name.startswith("."):
                    continue
                try:
                    scene = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                sid = scene.get("id") or p.stem
                if sid in seen:
                    continue
                seen.add(sid)
                out.append({"id": sid, "name": scene.get("name", sid)})
        return out

    def names(self) -> list[str]:
        return [s["id"] for s in self.list()]

    def load(self, scene_id: str) -> dict | None:
        p = self._path_of(scene_id)
        if p is None:
            return None
        try:
            scene = json.loads(p.read_text(encoding="utf-8"))
            scene.setdefault("id", p.stem)
            scene.setdefault("judgements", [])
            scene.setdefault("logic", "and")
            scene.setdefault("regions", [])
            scene.setdefault("accuracy", 0)
            return scene
        except Exception:
            return None

    def exists(self, scene_id: str) -> bool:
        return self._path_of(scene_id) is not None

    # ── 写 / 删 ─────────────────────────────────────────
    def save(self, scene: dict) -> None:
        sid = scene.get("id", "")
        if not sid:
            raise ValueError("识别素材缺少 id")
        scene.setdefault("name", sid)
        scene.setdefault("judgements", [])
        scene.setdefault("logic", "and")
        scene.setdefault("regions", [])
        scene.setdefault("accuracy", 0)
        p = self._write_path(sid)
        p.write_text(json.dumps(scene, ensure_ascii=False, indent=2),
                     encoding="utf-8")

    def delete(self, scene_id: str) -> bool:
        p = self._path_of(scene_id)
        if p is not None:
            p.unlink()
            return True
        return False
