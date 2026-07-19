"""
左侧菜单树面板（v2.5 重构版）

菜单：全局控制 | 脚本配置 | 图片配置 | 任务管理 | 游戏任务 | 运行监控 | 小号设置
"""

from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


MENU_STYLE = """
    QTreeWidget {
        background: #FFFFFF;
        border: 1px solid #E8ECF0;
        border-radius: 10px;
        padding: 4px;
    }
    QTreeWidget::item {
        padding: 8px 6px;
        border-radius: 6px;
        margin: 2px 4px;
    }
    QTreeWidget::item:hover {
        background: #F0F4FF;
    }
    QTreeWidget::item:selected {
        background: #E3F0FF;
        color: #1A73E8;
        font-weight: bold;
    }
    QTreeWidget::branch:has-children:!has-siblings:closed,
    QTreeWidget::branch:closed:has-children:has-siblings {
        border-image: none;
    }
"""

HEADER_STYLE = """
    QLabel {
        color: #5F6368;
        font-weight: bold;
        padding: 8px 10px;
        background: transparent;
        border-bottom: 2px solid #E8ECF0;
    }
"""


class MenuTree(QWidget):
    """左侧菜单树。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("导航菜单")
        header.setFont(QFont("Microsoft YaHei", 11))
        header.setStyleSheet(HEADER_STYLE)
        layout.addWidget(header)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(20)
        self.tree.setAnimated(True)
        self.tree.setStyleSheet(MENU_STYLE)
        self.tree.setFixedWidth(185)

        # === 1. 全局控制（一级，无子菜单，最上方）===
        ctrl = QTreeWidgetItem(self.tree, ["🎯 全局控制"])
        ctrl.setFont(0, QFont("Microsoft YaHei", 10, QFont.Bold))
        ctrl.setData(0, Qt.UserRole, ("dashboard", ""))

        # === 2. 脚本配置 ===
        cfg = self._add_root("⚙  脚本配置")
        for name, key in [
            ("📡 模拟器连接", "config:emulator"), ("👤 账号管理", "config:account"),
            ("📊 任务优先级", "config:priority"), ("🛡 防封号参数", "config:anti_detect"),
            ("⏱ 运行时段", "config:runtime"), ("👥 阵容预设", "config:teams"),
            ("📝 日志配置", "config:log"),
        ]:
            it = QTreeWidgetItem(cfg, [name]); it.setData(0, Qt.UserRole, ("config", key))

        # === 3. 图片配置（子菜单=分区）===
        img = self._add_root("🖼  图片配置")
        for name, key in [
            ("🏠 主界面", "image:主界面"), ("🗺 探索", "image:探索"),
            ("✨ 召唤", "image:召唤"), ("🛒 商城", "image:商城"),
            ("⚔ 战斗", "image:战斗"), ("🏯 阴阳寮", "image:阴阳寮"),
            ("🎪 活动", "image:活动"), ("🔧 通用", "image:通用"),
            ("👥 阵容", "image:阵容"),
        ]:
            it = QTreeWidgetItem(img, [name]); it.setData(0, Qt.UserRole, ("image", key))

        # === 4. 任务管理 ===
        tm = self._add_root("📋 任务管理")
        for name, key in [
            ("📅 日常任务", "taskmgr:daily"), ("⚔ 常驻任务", "taskmgr:permanent"),
            ("🎪 活动任务", "taskmgr:event"), ("⭐ 特殊任务", "taskmgr:special"),
            ("🔧 通用模块", "taskmgr:common"), ("🔨 特化模块", "taskmgr:specialized"),
        ]:
            it = QTreeWidgetItem(tm, [name]); it.setData(0, Qt.UserRole, ("taskmgr", key))

        # === 5. 游戏任务 ===
        game = self._add_root("🎮 游戏任务")
        for name, key in [
            ("📅 日常任务", "game:daily"), ("⚔ 常驻任务", "game:permanent"),
            ("🎪 活动任务", "game:event"), ("⭐ 特殊任务", "game:special"),
        ]:
            it = QTreeWidgetItem(game, [name]); it.setData(0, Qt.UserRole, ("game", key))

        # === 6. 运行监控 ===
        monitor = self._add_root("📈 运行监控")
        for name, key in [
            ("📊 运行指标", "monitor:metrics"),
            ("📸 异常截图", "monitor:snapshots"),
            ("📄 运行报告", "monitor:report"),
        ]:
            it = QTreeWidgetItem(monitor, [name]); it.setData(0, Qt.UserRole, ("monitor", key))

        # === 7. 小号设置 ===
        sub = self._add_root("👥 小号设置")
        for i in [1, 2]:
            it = QTreeWidgetItem(sub, [f"小号 {i}"])
            it.setData(0, Qt.UserRole, ("sub_account", f"sub{i}"))

        self.tree.expandAll()
        layout.addWidget(self.tree)

    def _add_root(self, name: str) -> QTreeWidgetItem:
        root = QTreeWidgetItem(self.tree, [name])
        root.setFont(0, QFont("Microsoft YaHei", 10, QFont.Bold))
        return root

    def on_item_clicked(self, callback):
        """绑定点击回调。callback(item, data)。"""
        self.tree.itemClicked.connect(lambda item, col: self._handle(item, col, callback))

    def _handle(self, item, col, callback):
        data = item.data(0, Qt.UserRole)
        if data:
            callback(item, data)
