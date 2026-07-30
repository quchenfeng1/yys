"""
素材存储工具类（供 02-图像识别模块 和 11-用户界面模块 共用）

ImageManager 素材增删改查（纯数据层，不依赖 UI 框架）。
职责:
- 管理模板图片的索引（名称->路径映射）
- 支持文件夹分组（按场景/界面）
- 素材元数据（分辨率、hash、标签）
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AssetEntry:
    """素材条目"""
    name: str
    file_path: str
    group: str = ""
    tags: list[str] = field(default_factory=list)
    resolution: tuple[int, int] | None = None
    file_hash: str = ""
    description: str = ""


class ImageManager:
    """
    素材管理器（纯数据层）。

    管理模板图片的注册、查询、分组。
    不依赖 OpenCV 或 UI 框架，仅为文件路径索引。
    """

    def __init__(self, asset_dirs: list[str | Path] | None = None):
        self._lock = threading.Lock()
        self._entries: dict[str, AssetEntry] = {}  # name -> entry
        self._groups: dict[str, list[str]] = {}  # group -> [names]
        self._asset_dirs: list[Path] = [Path(d) for d in (asset_dirs or [])]

    # ── 注册 ──────────────────────────────────────────────────

    def register(self, entry: AssetEntry) -> bool:
        """注册一个素材条目"""
        with self._lock:
            if entry.name in self._entries:
                return False
            self._entries[entry.name] = entry
            if entry.group:
                self._groups.setdefault(entry.group, []).append(entry.name)
        return True

    def register_file(self, file_path: str | Path, group: str = "") -> AssetEntry | None:
        """注册一个图片文件为素材"""
        path = Path(file_path)
        if not path.exists():
            return None

        name = path.stem
        # 计算文件 hash
        file_hash = self._compute_hash(path)

        entry = AssetEntry(
            name=name,
            file_path=str(path.resolve()),
            group=group,
            file_hash=file_hash,
        )
        if self.register(entry):
            return entry
        return None

    def scan_directory(self, directory: str | Path, group: str = "", recursive: bool = True) -> int:
        """扫描目录，注册所有图片文件"""
        path = Path(directory)
        if not path.exists():
            return 0

        extensions = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
        count = 0

        if recursive:
            files = list(path.rglob("*"))
        else:
            files = list(path.glob("*"))

        for f in files:
            if f.suffix.lower() in extensions:
                if self.register_file(f, group=group):
                    count += 1

        return count

    # ── 查询 ──────────────────────────────────────────────────

    def get(self, name: str) -> AssetEntry | None:
        """通过名称获取素材"""
        return self._entries.get(name)

    def get_path(self, name: str) -> str | None:
        """获取素材文件路径"""
        entry = self.get(name)
        return entry.file_path if entry else None

    def list_by_group(self, group: str) -> list[AssetEntry]:
        """获取指定分组的所有素材"""
        names = self._groups.get(group, [])
        return [self._entries[n] for n in names if n in self._entries]

    def list_all(self) -> list[AssetEntry]:
        """获取所有素材"""
        return list(self._entries.values())

    def get_groups(self) -> list[str]:
        """获取所有分组名"""
        return sorted(self._groups.keys())

    def search(self, query: str) -> list[AssetEntry]:
        """搜索素材（名称/标签/描述）"""
        q = query.lower()
        results = []
        for entry in self._entries.values():
            if q in entry.name.lower():
                results.append(entry)
                continue
            if any(q in tag.lower() for tag in entry.tags):
                results.append(entry)
                continue
            if q in entry.description.lower():
                results.append(entry)
        return results

    # ── 删除 ──────────────────────────────────────────────────

    def remove(self, name: str) -> bool:
        """删除素材"""
        with self._lock:
            entry = self._entries.pop(name, None)
            if not entry:
                return False
            if entry.group and entry.group in self._groups:
                group_list = self._groups[entry.group]
                if name in group_list:
                    group_list.remove(name)
        return True

    def remove_group(self, group: str) -> int:
        """删除整个分组"""
        count = 0
        with self._lock:
            names = list(self._groups.get(group, []))
            for name in names:
                self._entries.pop(name, None)
                count += 1
            self._groups.pop(group, None)
        return count

    # ── 更新 ──────────────────────────────────────────────────

    def update_metadata(self, name: str, **kwargs: Any) -> bool:
        """更新素材元数据"""
        with self._lock:
            entry = self._entries.get(name)
            if not entry:
                return False
            for k, v in kwargs.items():
                if hasattr(entry, k):
                    setattr(entry, k, v)
        return True

    # ── 统计 ──────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._entries)

    def group_counts(self) -> dict[str, int]:
        """各分组素材数量"""
        return {g: len(names) for g, names in self._groups.items()}

    # ── 工具 ──────────────────────────────────────────────────

    @staticmethod
    def _compute_hash(path: Path) -> str:
        """计算文件 SHA256 hash"""
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()[:16]
        except Exception:
            return ""

    def add_asset_dir(self, directory: str | Path) -> None:
        """添加素材搜索目录"""
        path = Path(directory)
        if path not in self._asset_dirs:
            self._asset_dirs.append(path)
