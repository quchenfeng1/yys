"""
UI 子面板：MenuTree 左侧菜单树。

菜单项使用 FontAwesome 图标（QIcon）+ 统一 iconSize/行高，保证所有项左侧图标
大小一致、完全对齐。顺序：任务队列第一、设置最后。
"""
from __future__ import annotations

from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtWidgets import QListWidget, QListWidgetItem

# 菜单顺序（任务队列第一、设置最后）
_MENU_ORDER = [
    "task_queue",   # 📌 任务队列
    "game_task",    # 📋 游戏任务
    "visual_builder",  # 🛠 可视化构建
    "task_manager", # 📁 任务管理
    "image",        # 🖼 素材管理
    "accounts",     # 👤 小号管理
    "history",      # 📊 执行历史
    "config",       # ⚙️ 设置
]

# 显示名 + FontAwesome 图标名（统一 QIcon → 图标大小完全对齐）
_MENU_LABEL = {
    "task_queue": "任务队列",
    "game_task": "游戏任务",
    "visual_builder": "可视化构建",
    "task_manager": "任务管理",
    "image": "素材管理",
    "accounts": "小号管理",
    "history": "执行历史",
    "config": "设置",
}
_MENU_ICON = {
    "task_queue": "fa5s.tasks",
    "game_task": "fa5s.gamepad",
    "visual_builder": "fa5s.project-diagram",
    "task_manager": "fa5s.folder-open",
    "image": "fa5s.images",
    "accounts": "fa5s.user",
    "history": "fa5s.chart-bar",
    "config": "fa5s.cog",
}


class MenuTree(QListWidget):
    """左侧导航菜单树"""

    navigation_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 统一图标尺寸 + 行高，保证所有菜单项左侧图标对齐
        self.setIconSize(QSize(18, 18))
        self.setSpacing(2)

        from ui.theme import icon as theme_icon

        self._items: dict[str, QListWidgetItem] = {}
        for key in _MENU_ORDER:
            item = QListWidgetItem(_MENU_LABEL[key])
            item.setData(256, key)  # Qt.UserRole
            ic = theme_icon(_MENU_ICON[key], "#8a94a6")
            if ic is not None:
                item.setIcon(ic)
            item.setSizeHint(QSize(0, 30))  # 统一行高 → 垂直对齐
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
