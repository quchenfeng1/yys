"""Game Profile 游戏档案：多游戏支持的核心加载器（18-游戏解耦迁移）。

每个游戏一个文件夹 games/{game_id}/，含：
  profile.yaml   游戏档案（名称/OCR语言/坐标模式等）
  tasks/         该游戏任务代码（games.{game_id}.tasks 包，含 common 等）
  assets/        该游戏素材
  tasks.yaml     该游戏任务调度配置
  coords/        坐标配置（预留）
  runtime/       该游戏调度运行状态（task_state / task_runtime_progress）
  visual_tasks/  可视化任务（节点图，新体系）

删除 games/{game_id}/ = 该游戏内容全部消失，核心骨架零残留。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GameProfile:
    """单个游戏的档案：提供该游戏所有内容路径。"""

    root: Path | str                 # 主程序根
    game_id: str = "yys"

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.base = self.root / "games" / self.game_id

    # ── 目录 ────────────────────────────────────────────────
    @property
    def base_dir(self) -> Path:
        return self.base

    @property
    def tasks_dir(self) -> Path:
        return self.base / "tasks"

    @property
    def assets_dir(self) -> Path:
        return self.base / "assets"

    @property
    def tasks_yaml(self) -> Path:
        return self.base / "tasks.yaml"

    @property
    def coords_dir(self) -> Path:
        return self.base / "coords"

    @property
    def runtime_dir(self) -> Path:
        return self.base / "runtime"

    @property
    def visual_tasks_dir(self) -> Path:
        return self.base / "visual_tasks"

    @property
    def nodes_dir(self) -> Path:
        """游戏内通用节点（2026-08-15）：games/{game}/nodes/"""
        return self.base / "nodes"

    @property
    def shared_nodes_dir(self) -> Path:
        """跨游戏通用节点（2026-08-15）：games/_shared/nodes/"""
        return self.root / "games" / "_shared" / "nodes"

    @property
    def scenes_dir(self) -> Path:
        """游戏内识别素材（识别素材库）：games/{game}/scenes/"""
        return self.base / "scenes"

    @property
    def shared_scenes_dir(self) -> Path:
        """跨游戏识别素材：games/_shared/scenes/"""
        return self.root / "games" / "_shared" / "scenes"

    @property
    def profile_yaml(self) -> Path:
        return self.base / "profile.yaml"

    # ── 运行时状态文件 ──────────────────────────────────────
    @property
    def task_state_path(self) -> Path:
        return self.runtime_dir / "task_state.json"

    @property
    def task_runtime_progress_path(self) -> Path:
        return self.runtime_dir / "task_runtime_progress.json"

    # ── 包命名空间 ──────────────────────────────────────────
    @property
    def task_package(self) -> str:
        """任务包：games.{game_id}.tasks（含 daily/event/.../common）"""
        return f"games.{self.game_id}.tasks"

    # ── 配置读取 ────────────────────────────────────────────
    def load_profile(self) -> dict[str, Any]:
        import yaml
        if self.profile_yaml.exists():
            try:
                return yaml.safe_load(
                    self.profile_yaml.read_text(encoding="utf-8")) or {}
            except Exception:
                return {}
        return {}

    @property
    def display_name(self) -> str:
        return self.load_profile().get("name") or self.game_id

    @property
    def ocr_lang(self) -> str:
        return self.load_profile().get("ocr_lang", "ch")

    def ensure_dirs(self) -> None:
        for d in (self.tasks_dir, self.assets_dir, self.coords_dir,
                  self.runtime_dir, self.visual_tasks_dir):
            d.mkdir(parents=True, exist_ok=True)


def scan_games(root: Path | str) -> list[GameProfile]:
    """扫描 games/ 目录，返回所有有效游戏档案（含 tasks/assets/profile 之一）。"""
    root = Path(root)
    games_dir = root / "games"
    if not games_dir.exists():
        return []
    out: list[GameProfile] = []
    for d in sorted(games_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name == "__pycache__":
            continue
        gp = GameProfile(root=root, game_id=d.name)
        if gp.tasks_dir.exists() or gp.assets_dir.exists() or gp.profile_yaml.exists():
            out.append(gp)
    return out


def load_game(root: Path | str, game_id: str = "yys") -> GameProfile:
    """加载指定游戏档案（不存在时返回对象，目录惰性创建）。"""
    return GameProfile(root=root, game_id=game_id)


def current_game_assets(root: Path | str | None = None) -> Path:
    """当前默认游戏（yys）的 assets 目录——UI 面板 fallback 用。"""
    base = Path(root) if root else Path(__file__).resolve().parents[1]
    return GameProfile(root=base).assets_dir
