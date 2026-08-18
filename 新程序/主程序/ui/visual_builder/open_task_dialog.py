"""
17-可视化构建模块：打开任务弹窗（OpenTaskDialog）。

布局（单游戏，游戏由外部顶部下拉决定）：
- 游戏任务列表（2026-08-15：通用操作体系已移除，改为框选封装→通用节点）
- 底部：＋新增 / 📂 打开 / 取消

交互：
- 新增：在列表中新建（不打开）
- 打开 / 双击：返回 (game_id, kind, name)，由调用方加载到画布编辑
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QInputDialog,
                             QListWidget, QListWidgetItem, QMessageBox,
                             QPushButton, QVBoxLayout)

from core.game_profile import scan_games
from visual.rule_store import VisualTaskStore


class OpenTaskDialog(QDialog):
    """打开任务弹窗（按外部指定的游戏）"""

    def __init__(self, profile, game_id: str, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._game_id = game_id or (profile.game_id if profile else "yys")
        self._root = Path(profile.root) if profile else Path(".")
        self._games = scan_games(self._root)
        self._selected: tuple[str, str, str] | None = None  # (game_id, kind, name)

        self.setWindowTitle(f"打开任务 — {self._game_display()}")
        self.resize(560, 440)

        lay = QVBoxLayout(self)

        # ── 游戏任务列表（2026-08-15：通用操作 Tab 已移除，改框选封装→通用节点）──
        self._task_list = QListWidget()
        self._task_list.itemDoubleClicked.connect(lambda i: self._open())
        self._task_list.setToolTip("游戏任务 — 双击打开编辑")
        lay.addWidget(self._task_list, 1)

        # ── 底部按钮 ────────────────────────────────────
        btn_row = QHBoxLayout()
        self._new_btn = QPushButton("＋ 新增")
        self._new_btn.clicked.connect(self._new_item)
        self._open_btn = QPushButton("📂 打开")
        self._open_btn.clicked.connect(self._open)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._new_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._open_btn)
        btn_row.addWidget(self._cancel_btn)
        lay.addLayout(btn_row)

        self._refresh_current()

    # ── 状态 ─────────────────────────────────────────────
    def _game_display(self) -> str:
        gp = self._game()
        return f"{gp.display_name}（{gp.game_id}）" if gp else self._game_id

    def _game(self) -> Any | None:
        for g in self._games:
            if g.game_id == self._game_id:
                return g
        return None

    def selected(self) -> tuple[str, str, str] | None:
        """返回 (game_id, kind, name) 或 None"""
        return self._selected

    def current_kind(self) -> str:
        return "task"   # 2026-08-15：通用操作体系已移除

    def current_list(self) -> QListWidget:
        return self._task_list

    def _store_for(self, game_id: str, kind: str) -> Any:
        """按游戏构造任务存储（自包含，不依赖当前 bridge）"""
        gp = self._game()
        if gp is None:
            raise FileNotFoundError(f"游戏不存在: {game_id}")
        return VisualTaskStore(gp.visual_tasks_dir)

    # ── 刷新 ─────────────────────────────────────────────
    def _refresh_current(self) -> None:
        kind = self.current_kind()
        lst = self.current_list()
        lst.clear()
        try:
            store = self._store_for(self._game_id, kind)
            metas = store.list()
        except Exception:
            metas = []
        for meta in metas:
            item = QListWidgetItem(
                f"{meta.get('display_name', meta['name'])}"
                f"（{meta['name']}）")
            item.setData(Qt.UserRole, meta["name"])
            item.setToolTip(f"节点:{meta.get('node_count', 0)}")
            lst.addItem(item)
        if not metas:
            it = QListWidgetItem("（暂无游戏任务 — 点「＋ 新增」创建）")
            it.setFlags(Qt.NoItemFlags)
            lst.addItem(it)

    # ── 新增 / 打开 ─────────────────────────────────────
    def _new_item(self) -> None:
        kind = self.current_kind()
        try:
            store = self._store_for(self._game_id, kind)
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))
            return
        hint = "任务名（英文，如 farm_soul）"
        name, ok = QInputDialog.getText(self, "新增", f"{hint}:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if store.exists(name):
            QMessageBox.warning(self, "已存在", f"「{name}」已存在")
            return
        display, ok2 = QInputDialog.getText(self, "新增", "显示名:",
                                            text=name)
        if not ok2:
            return
        try:
            store.create(name, display.strip() or name)
        except Exception as e:
            QMessageBox.warning(self, "新增失败", str(e))
            return
        self._refresh_current()

    def _open(self) -> None:
        kind = self.current_kind()
        lst = self.current_list()
        item = lst.currentItem()
        if item is None or not item.data(Qt.UserRole):
            return
        name = item.data(Qt.UserRole)
        self._selected = (self._game_id, kind, name)
        self.accept()
