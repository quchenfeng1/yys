"""
UI 子面板：MenuTree 左侧菜单树。
"""
from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QListWidget, QListWidgetItem


class MenuTree(QListWidget):
    """左侧导航菜单树"""

    navigation_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._items: dict[str, QListWidgetItem] = {}
        menu_items = [
            ("game_task", "📋 游戏任务"),
            ("task_queue", "📌 任务队列"),
            ("task_manager", "📁 任务管理"),
            ("config", "⚙️ 配置"),
            ("image", "🖼 素材管理"),
            ("accounts", "👤 小号管理"),
            ("history", "📊 执行历史"),
            ("ui_settings", "🎨 UI 设置"),
        ]

        for key, label in menu_items:
            item = QListWidgetItem(label)
            item.setData(256, key)  # Qt.UserRole
            self.addItem(item)
            self._items[key] = item

        self.currentItemChanged.connect(self._on_item_changed)

    def _on_item_changed(self, current, previous):
        if current:
            key = current.data(256)
            self.navigation_requested.emit(key)

    def select(self, key: str) -> None:
        """编程方式选择菜单项"""
        item = self._items.get(key)
        if item:
            self.setCurrentItem(item)

    # ── §3.8 面板显隐（UI 自控）──────────────────────────

    def set_item_visible(self, key: str, visible: bool) -> None:
        """显示/隐藏某个菜单项（面板显隐控制）"""
        item = self._items.get(key)
        if item:
            item.setHidden(not visible)
            if not visible and self.currentItem() is item:
                # 当前选中项被隐藏 → 跳到第一个可见项
                for it in self._items.values():
                    if not it.isHidden():
                        self.setCurrentItem(it)
                        break
