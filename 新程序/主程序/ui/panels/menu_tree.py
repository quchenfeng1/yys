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
