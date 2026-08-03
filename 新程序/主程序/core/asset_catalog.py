"""
任务图片目录约定管理（Asset Catalog）

独立模块（不依赖核心素材机制/UI）。约定 assets/ 下的目录结构：

```
assets/
  scene/                 识图文件夹：场景感知/位置确认素材（scene_probe 引用 scene/xxx）
  tasks/                 任务图片（每个游戏任务一个子文件夹）
    {task_name}/         游戏任务专属图片（代码引用 tasks/{task_name}/xxx）
    _shared/             通用任务共享图片（代码引用 tasks/_shared/xxx）
```

说明：
- 02-图像识别模块 仍按相对 assets/ 的路径加载素材（本模块不修改加载机制）
- 任务代码引用素材时用相对路径（如 `click_image("tasks/my_task/button")`），
  find_missing_assets / recognizer 均可直接工作
- 通用任务共享 `_shared/`；识图文件夹 `scene/` 供场景感知（scene_probe/detect_scene）使用
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# 目录名约定
SCENE_DIR = "scene"       # 识图文件夹
TASKS_DIR = "tasks"       # 任务图片根
SHARED_DIR = "_shared"    # 通用共享


def open_in_file_manager(path, create: bool = False) -> bool:
    """用系统文件管理器打开路径（macOS open / Windows startfile / Linux xdg-open）。

    create=True 时目录不存在则自动创建（打开前确保目录存在，
    便于旧任务/未建图夹的任务补建空文件夹）。返回是否成功。
    """
    p = Path(path)
    if create:
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False
    if not p.exists() or not p.is_dir():
        return False
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        elif os.name == "nt":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return True
    except Exception:
        return False


class AssetCatalog:
    """任务图片目录管理（纯路径/文件操作，无依赖）"""

    def __init__(self, assets_dir: str | Path):
        self._assets = Path(assets_dir)

    # ── 路径 ──────────────────────────────────────────────

    def scene_dir(self) -> Path:
        """识图文件夹（场景感知素材）"""
        return self._assets / SCENE_DIR

    def tasks_dir(self) -> Path:
        """任务图片根目录"""
        return self._assets / TASKS_DIR

    def task_dir(self, task_name: str) -> Path:
        """指定游戏任务的专属图片目录"""
        return self.tasks_dir() / task_name

    def shared_dir(self) -> Path:
        """通用任务共享图片目录"""
        return self.tasks_dir() / SHARED_DIR

    # ── 创建 ──────────────────────────────────────────────

    def ensure_scene_dir(self) -> Path:
        """确保识图文件夹存在"""
        return self._ensure(self.scene_dir())

    def ensure_shared_dir(self) -> Path:
        """确保通用共享文件夹存在"""
        return self._ensure(self.shared_dir())

    def ensure_task_dir(self, task_name: str) -> Path:
        """确保指定游戏任务的图片文件夹存在"""
        return self._ensure(self.task_dir(task_name))

    @staticmethod
    def _ensure(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        # 空目录占位（git 保目录）
        if not any(path.iterdir()):
            keep = path / ".gitkeep"
            if not keep.exists():
                keep.write_text("", encoding="utf-8")
        return path

    # ── 列举 ──────────────────────────────────────────────

    @staticmethod
    def _list_images(folder: Path) -> list[dict]:
        """列出目录下图片：{name, rel, abs, size}（rel 为相对 assets/ 的引用路径）"""
        result = []
        if not folder.exists():
            return result
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.suffix.lower() in exts:
                result.append({
                    "name": f.stem,
                    "rel": str(f.relative_to(folder.parent.parent)).replace("\\", "/"),
                    "abs": str(f),
                    "size": f.stat().st_size,
                })
        return result

    def list_task_images(self, task_name: str) -> list[dict]:
        """列出指定任务的专属图片"""
        return self._list_images(self.task_dir(task_name))

    def list_scene_images(self) -> list[dict]:
        """列出识图文件夹图片"""
        return self._list_images(self.scene_dir())

    def list_shared_images(self) -> list[dict]:
        """列出通用共享图片"""
        return self._list_images(self.shared_dir())

    def list_task_folders(self) -> list[str]:
        """列出已建图片文件夹的任务名（含 _shared）"""
        td = self.tasks_dir()
        if not td.exists():
            return []
        return sorted(p.name for p in td.iterdir() if p.is_dir())
