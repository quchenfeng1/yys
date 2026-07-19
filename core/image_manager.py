"""
图片管理器（v2.3 新增 — 按游戏场景分区管理素材）

将图片从"按任务类型分"重构为"按游戏场景分区"：
  主界面 / 探索 / 召唤 / 商城 / 战斗 / 阴阳寮 / 活动 / 通用 / 阵容

每张图片带有备注（用途说明），支持增删改查和真实尺寸预览。

目录结构：
  assets/
  ├── 主界面/     ← courtyard scenes + UI buttons in main page
  ├── 探索/       ← explore map, dungeon entries
  ├── 召唤/
  ├── 商城/
  ├── 战斗/       ← battle UI, victory/defeat
  ├── 阴阳寮/
  ├── 活动/
  ├── 通用/       ← common buttons (close, confirm, back) across all scenes
  └── 阵容/       ← team presets
"""

import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.event_bus import event_bus, Events

# ==================== 场景分区定义 ====================

SCENE_SECTIONS = {
    "主界面": {
        "icon": "🏠",
        "desc": "庭院、主界面入口按钮",
        "examples": "庭院标志、探索入口、町中入口、签到入口",
    },
    "探索": {
        "icon": "🗺",
        "desc": "探索地图内的副本入口",
        "examples": "御魂入口、觉醒入口、秘闻入口、章节选择",
    },
    "召唤": {
        "icon": "✨",
        "desc": "召唤界面相关",
        "examples": "召唤按钮、十连按钮、跳过动画",
    },
    "商城": {
        "icon": "🛒",
        "desc": "商城/商店界面",
        "examples": "商城入口、购买按钮、每日免费礼包",
    },
    "战斗": {
        "icon": "⚔",
        "desc": "战斗界面通用元素",
        "examples": "挑战按钮、胜利标志、失败标志、准备按钮",
    },
    "阴阳寮": {
        "icon": "🏯",
        "desc": "阴阳寮相关界面",
        "examples": "寮入口、结界突破、道馆、麒麟",
    },
    "活动": {
        "icon": "🎪",
        "desc": "限时活动界面",
        "examples": "活动Banner、活动入口、活动兑换",
    },
    "通用": {
        "icon": "🔧",
        "desc": "跨场景通用按钮",
        "examples": "关闭按钮、确认按钮、返回按钮",
    },
    "阵容": {
        "icon": "👥",
        "desc": "阵容预设标记图",
        "examples": "阵容验证图、选阵容分步图",
    },
}

# 分区对应的 assets 子目录名（安全文件名）
SECTION_DIRS = {name: name for name in SCENE_SECTIONS}


# ==================== 图片元数据 ====================

class ImageEntry:
    """单张图片的元数据。"""

    def __init__(self, name: str, section: str, note: str = "",
                 filepath: str = "", size: tuple = (0, 0)):
        self.name = name              # 文件名（含 .png）
        self.section = section        # 所属分区
        self.note = note              # 备注（用途说明）
        self.filepath = filepath      # 完整路径
        self.size = size              # (width, height)
        self.added_at = ""            # 添加时间 ISO
        self.used_by: list[str] = []  # 被哪些任务引用

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "section": self.section,
            "note": self.note,
            "filepath": self.filepath,
            "size": list(self.size),
            "added_at": self.added_at,
            "used_by": self.used_by,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ImageEntry":
        return cls(
            name=d.get("name", ""),
            section=d.get("section", ""),
            note=d.get("note", ""),
            filepath=d.get("filepath", ""),
            size=tuple(d.get("size", (0, 0))),
        )


# ==================== 图片管理器 ====================

class ImageManager:
    """图片资源管理器。管理 assets/ 下所有图片的增删改查。"""

    METADATA_FILE = "assets/.image_meta.json"

    def __init__(self, project_root: Path = None):
        self._root = project_root or Path(__file__).parent.parent
        self._assets_dir = self._root / "assets"
        self._images: dict[str, ImageEntry] = {}  # name → entry
        self._meta_path = self._root / self.METADATA_FILE
        self._ensure_dirs()
        self._load_meta()

    # ==================== 初始化 ====================

    def _ensure_dirs(self):
        """确保所有分区目录存在。"""
        for section in SECTION_DIRS:
            (self._assets_dir / section).mkdir(parents=True, exist_ok=True)

    def _load_meta(self):
        """加载图片元数据 JSON。"""
        if self._meta_path.exists():
            try:
                data = json.loads(self._meta_path.read_text(encoding="utf-8"))
                for d in data.get("images", []):
                    entry = ImageEntry.from_dict(d)
                    # 同步文件系统状态
                    full_path = self._assets_dir / entry.section / entry.name
                    if full_path.exists():
                        entry.filepath = str(full_path)
                        self._images[entry.name] = entry
            except (json.JSONDecodeError, KeyError):
                pass

        # 扫描文件系统补充未在元数据中的图片
        self._scan_filesystem()

    def _scan_filesystem(self):
        """扫描 assets/ 下所有 PNG，补充元数据。"""
        for section in SECTION_DIRS:
            section_dir = self._assets_dir / section
            if not section_dir.exists():
                continue
            for f in section_dir.iterdir():
                if f.suffix.lower() != ".png":
                    continue
                if f.name in self._images:
                    # 已有元数据，同步路径
                    self._images[f.name].filepath = str(f)
                else:
                    # 新建元数据
                    from PIL import Image
                    try:
                        img = Image.open(f)
                        size = img.size
                    except Exception:
                        size = (0, 0)
                    entry = ImageEntry(
                        name=f.name,
                        section=section,
                        note="",
                        filepath=str(f),
                        size=size,
                    )
                    entry.added_at = datetime.fromtimestamp(
                        f.stat().st_mtime).isoformat()
                    self._images[f.name] = entry

    def _save_meta(self):
        """保存元数据到 JSON。"""
        data = {
            "_version": 1,
            "_updated": datetime.now().isoformat(),
            "images": [e.to_dict() for e in self._images.values()],
        }
        self._meta_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    # ==================== 查询 ====================

    def get_sections(self) -> list[dict]:
        """获取所有分区列表。"""
        result = []
        for name, info in SCENE_SECTIONS.items():
            count = self.count_section(name)
            result.append({
                "name": name,
                "icon": info["icon"],
                "desc": info["desc"],
                "count": count,
            })
        return result

    def get_images(self, section: str) -> list[ImageEntry]:
        """获取指定分区的所有图片。"""
        return [e for e in self._images.values() if e.section == section]

    def count_section(self, section: str) -> int:
        return sum(1 for e in self._images.values() if e.section == section)

    def total_count(self) -> int:
        return len(self._images)

    def find(self, name: str) -> Optional[ImageEntry]:
        return self._images.get(name)

    def get_recognizer_index(self) -> dict[str, str]:
        """生成给 Recognizer 使用的索引：{索引名: 文件路径}。

        Recognizer 用 "主界面/庭院标志" 这样的索引名来查找图片。
        """
        index = {}
        for entry in self._images.values():
            key = f"{entry.section}/{entry.name.replace('.png', '')}"
            index[key] = entry.filepath
        return index

    # ==================== 增删改 ====================

    def add_image(self, source_path: str, section: str,
                  note: str = "", new_name: str = "") -> Optional[ImageEntry]:
        """添加一张图片。从外部路径复制到 assets/{section}/。

        Args:
            source_path: 源文件路径
            section: 目标分区
            note: 备注
            new_name: 新文件名（不含扩展名），留空则用原名

        Returns:
            新的 ImageEntry，失败返回 None
        """
        source = Path(source_path)
        if not source.exists():
            return None

        target_name = (new_name or source.stem) + ".png"
        target_dir = self._assets_dir / section
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / target_name

        # 复制文件
        shutil.copy2(str(source), str(target_path))

        # 获取尺寸
        from PIL import Image
        try:
            img = Image.open(target_path)
            size = img.size
        except Exception:
            size = (0, 0)

        entry = ImageEntry(
            name=target_name,
            section=section,
            note=note,
            filepath=str(target_path),
            size=size,
        )
        entry.added_at = datetime.now().isoformat()
        self._images[target_name] = entry
        self._save_meta()
        event_bus.publish("image_added", name=target_name, section=section)
        return entry

    def update_note(self, filename: str, note: str):
        """更新图片备注。"""
        entry = self._images.get(filename)
        if entry:
            entry.note = note
            self._save_meta()
            event_bus.publish("image_updated", name=filename)

    def delete_image(self, filename: str) -> bool:
        """删除图片（文件和元数据）。"""
        entry = self._images.get(filename)
        if not entry:
            return False
        path = Path(entry.filepath) if entry.filepath else (self._assets_dir / entry.section / filename)
        if path.exists():
            path.unlink()
        del self._images[filename]
        self._save_meta()
        event_bus.publish("image_deleted", name=filename, section=entry.section)
        return True

    def get_image_path(self, filename: str, section: str = "") -> Optional[str]:
        """获取图片的完整路径（用于预览）。"""
        entry = self._images.get(filename)
        if entry:
            return entry.filepath
        # fallback：按分区+文件名查找
        sec = section or self._guess_section(filename)
        path = self._assets_dir / sec / filename
        return str(path) if path.exists() else None

    def _guess_section(self, filename: str) -> str:
        for s in SECTION_DIRS:
            if (self._assets_dir / s / filename).exists():
                return s
        return "通用"
