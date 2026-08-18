"""
17-可视化构建模块：识别素材库（SceneStore，2026-08-14）。

场景（识别素材）= 一张目标图的识别特征集合：
  { "id", "name", "signal", "judgements": [...], "logic": "and"/"or" }

signal（2026-08-15）：场景判定成功后输出的场景信号（供信号触发器接收）。

「图像识别」节点（scene_probe）绑定 scene_id 后即可判断当前画面
是否命中该识别素材（true→out / false→not_found）。

存储（与通用操作库同层）：
- 跨游戏共享：games/_shared/scenes/{id}.json
- 游戏内共享：games/{game}/scenes/{id}.json

一次示教保存后，同游戏内所有任务的其他识图节点都能直接选用，
无需重复示教。
"""
from __future__ import annotations

import hashlib
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
        # 兼容哈希文件名（全非字母数字的 id，save 时用 md5 前缀作文件名）
        hash_name = hashlib.md5(str(scene_id).encode("utf-8")).hexdigest()[:8]
        names = {n for n in (safe, hash_name) if n}
        for d in self._dirs:
            for n in names:
                p = d / f"{n}.json"
                if p.exists():
                    return p
            # 兼容旧数据：中文原名直接作文件名保存的场景
            try:
                p2 = d / f"{str(scene_id)}.json"
                if p2.exists():
                    return p2
            except Exception:
                pass
        return None

    def _write_path(self, scene_id: str) -> Path:
        safe = self._safe(scene_id)
        if not safe:  # 全中文等被过滤 → 用短 hash 作文件名
            safe = hashlib.md5(str(scene_id).encode("utf-8")).hexdigest()[:8]
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
            scene.setdefault("signal", scene.get("id", ""))
            scene.setdefault("judgements", [])
            scene.setdefault("logic", "and")
            scene.setdefault("regions", [])
            scene.setdefault("accuracy", 0)
            return scene
        except Exception:
            return None

    def exists(self, scene_id: str) -> bool:
        return self._path_of(scene_id) is not None

    # ── 信号映射（2026-08-16：素材库重构后触发器的信号源）──
    def signal_map(self) -> dict[str, str]:
        """全部场景信号映射：{特征块模板相对路径(去扩展名): 信号名}。

        场景 = 多蓝框 × 多连通域特征块（templates[].template 为 PNG 相对路径）。
        TriggerWatcher 按信号名解析出全部特征块模板，匹配任一即触发。

        ⚠️ signal 为空串 = 非触发素材（素材管理中可开关），跳过不纳入。
        """
        out: dict[str, str] = {}
        for meta in self.list():
            sid = meta.get("id", "")
            scene = self.load(sid)
            if not scene:
                continue
            sig = scene.get("signal") or ""
            if not sig:
                continue  # 空信号 = 非触发素材
            for r in scene.get("regions", []) or []:
                for m in r.get("markers", []) or []:
                    for t in m.get("templates", []) or []:
                        if not isinstance(t, dict):
                            continue
                        tmpl = str(t.get("template", "") or "").strip()
                        if not tmpl:
                            continue
                        key = tmpl.rsplit(".", 1)[0] if "." in tmpl \
                            else tmpl
                        out[key] = sig
        return out

    def signal_options(self) -> list[tuple[str, str]]:
        """信号下拉选项 [(信号名, 场景id)]（信号去重，保留第一个场景）。

        signal 为空串 = 非触发素材，不出现在选项中。
        """
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for meta in self.list():
            sid = meta.get("id", "")
            scene = self.load(sid)
            if not scene:
                continue
            sig = scene.get("signal") or ""
            if not sig:
                continue
            if sig not in seen:
                seen.add(sig)
                out.append((sig, sid))
        return out

    # ── 写 / 删 ─────────────────────────────────────────
    def save(self, scene: dict) -> bool:
        sid = scene.get("id", "")
        if not sid:
            raise ValueError("识别素材缺少 id")
        if not self._dirs:
            raise ValueError("识别素材库未配置存储目录")
        scene.setdefault("name", sid)
        scene.setdefault("signal", sid)
        scene.setdefault("judgements", [])
        scene.setdefault("logic", "and")
        scene.setdefault("regions", [])
        scene.setdefault("accuracy", 0)
        p = self._write_path(sid)
        # 原子写入：先写 .tmp 再替换，避免中途断电/异常写坏文件
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(scene, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(p)
        return True

    def delete(self, scene_id: str) -> bool:
        p = self._path_of(scene_id)
        if p is not None:
            p.unlink()
            return True
        return False
