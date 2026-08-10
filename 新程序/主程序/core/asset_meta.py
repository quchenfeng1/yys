"""
素材元数据管理（标签 / 描述 / 文件名）。

图片的标签、描述、保存文件名统一记录在 assets/manifest.json：

    {
      "tags": ["按钮", "主界面", "弹窗", "背景图"],   # 全部标签（预设 + 自定义）
      "images": {
        "scene/主界面.png": {                         # 键 = 相对 assets/ 的路径
          "tags": ["主界面", "背景图"],               # 图片标签（至少 1 个）
          "description": "主界面识别图",              # 描述
          "file_name": "主界面.png"                   # 保存时的文件名（可能被改名）
        }
      }
    }

线程安全 + 原子写（临时文件 + replace）。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

# 预设标签
DEFAULT_TAGS = ["按钮", "主界面", "弹窗", "背景图"]

_MANIFEST_NAME = "manifest.json"


class AssetMetaStore:
    """素材元数据存储（assets/manifest.json）"""

    def __init__(self, assets_dir: str | Path):
        self._assets = Path(assets_dir)
        self._path = self._assets / _MANIFEST_NAME
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"tags": list(DEFAULT_TAGS), "images": {}}
        self.load()

    # ── 读写 ─────────────────────────────────────────────

    def load(self) -> None:
        """从磁盘加载 manifest（文件缺失/损坏时用默认值）"""
        with self._lock:
            if not self._path.exists():
                return
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                return
            if not isinstance(raw, dict):
                return
            tags = raw.get("tags")
            if isinstance(tags, list):
                self._data["tags"] = [str(t) for t in tags if str(t).strip()]
            images = raw.get("images")
            if isinstance(images, dict):
                self._data["images"] = images

    def save(self) -> None:
        """原子写盘（临时文件 + replace）"""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".json.tmp")
                tmp.write_text(
                    json.dumps(self._data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
                tmp.replace(self._path)
            except Exception:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                raise

    # ── 标签 ─────────────────────────────────────────────

    def get_all_tags(self) -> list[str]:
        """返回全部标签"""
        with self._lock:
            return list(self._data["tags"])

    def add_tag(self, tag: str) -> bool:
        """新增标签（去重）；返回是否成功"""
        tag = str(tag).strip()
        if not tag:
            return False
        with self._lock:
            if tag in self._data["tags"]:
                return False
            self._data["tags"].append(tag)
        self.save()
        return True

    def remove_tag(self, tag: str) -> bool:
        """删除标签；同时从所有图片中移除该标签"""
        with self._lock:
            if tag not in self._data["tags"]:
                return False
            self._data["tags"].remove(tag)
            for meta in self._data["images"].values():
                if isinstance(meta, dict) and tag in meta.get("tags", []):
                    meta["tags"] = [t for t in meta["tags"] if t != tag]
        self.save()
        return True

    # ── 图片元数据 ───────────────────────────────────────

    def get_image_meta(self, rel: str) -> dict[str, Any] | None:
        """按相对路径取图片元数据（无则 None）"""
        with self._lock:
            meta = self._data["images"].get(rel)
            return dict(meta) if isinstance(meta, dict) else None

    def set_image_meta(self, rel: str, tags: list[str],
                       description: str = "", file_name: str = "",
                       signal: str = "") -> None:
        """设置/更新图片元数据并持久化。signal 为识图素材的识别信号名（scene/ 专用）"""
        clean_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        with self._lock:
            self._data["images"][rel] = {
                "tags": clean_tags,
                "description": str(description or ""),
                "file_name": str(file_name or Path(rel).name),
                "signal": str(signal or ""),
            }
        self.save()

    # ── 识图信号（scene/ 素材的识别信号名）────────────────

    @staticmethod
    def _rel_key(rel: str) -> str:
        """素材相对路径去扩展名（与识别素材名一致，如 scene/主界面.png → scene/主界面）"""
        rel = str(rel).replace("\\", "/")
        name = rel.rsplit("/", 1)[-1]
        if "." in name:
            return rel.rsplit(".", 1)[0]
        return rel

    def get_signal(self, rel: str) -> str | None:
        """按相对路径取识图信号名（无 signal 或不存在 → None）"""
        with self._lock:
            meta = self._data["images"].get(rel)
            if isinstance(meta, dict):
                sig = meta.get("signal")
                return str(sig) if sig else None
            return None

    def all_signals(self) -> dict[str, str]:
        """全部识图信号：{素材识别名(去扩展名): 信号名}（仅含配置了 signal 的）"""
        out = {}
        with self._lock:
            for rel, meta in self._data["images"].items():
                if isinstance(meta, dict) and meta.get("signal"):
                    out[self._rel_key(rel)] = str(meta["signal"])
        return out

    def get_rel_by_signal(self, signal: str) -> str | None:
        """按信号名反查素材识别名（去扩展名；无 → None）"""
        for rel, sig in self.all_signals().items():
            if sig == signal:
                return rel
        return None

    def remove_image_meta(self, rel: str) -> bool:
        """删除图片元数据条目；返回是否存在"""
        with self._lock:
            if rel in self._data["images"]:
                del self._data["images"][rel]
            else:
                return False
        self.save()
        return True

    # ── 查询 ─────────────────────────────────────────────

    def find_by_tag(self, tag: str) -> list[dict[str, Any]]:
        """按标签查找图片：返回 [{rel, tags, description, file_name}]"""
        out = []
        with self._lock:
            for rel, meta in self._data["images"].items():
                if isinstance(meta, dict) and tag in meta.get("tags", []):
                    item = dict(meta)
                    item["rel"] = rel
                    out.append(item)
        return out

    def all_image_meta(self) -> dict[str, dict[str, Any]]:
        """全部图片元数据（浅拷贝）"""
        with self._lock:
            return {k: dict(v) for k, v in self._data["images"].items()
                    if isinstance(v, dict)}
