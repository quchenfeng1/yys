"""
底部状态栏（v4.0 — 对齐 07-运行时状态管理模块）

展示 9 项全局指标，全部数据源为 StateManager（通过 STATE_CHANGED 事件驱动刷新）。
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt5.QtGui import QFont

# 场景 → 图标映射
SCENE_ICONS = {
    "courtyard": "🏠", "battle": "⚔", "explore": "🌲",
    "loading": "⏳", "summon": "🎴", "shop": "🛒",
    "guild": "🏛", "unknown": "❓", None: "❓",
}


class StatusBar(QWidget):
    """底部状态展示栏 — 对齐 07-运行时状态管理模块的全部公开状态。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)

        self.run_label = self._make_item("●  已停止", "#80868B")
        self.conn_label = self._make_item("🔌  未连接", "#80868B")
        self.task_label = self._make_item("📋  —", "#80868B")
        self.scene_label = self._make_item("❓  未知", "#80868B")
        self.acct_label = self._make_item("👤  —", "#80868B")
        self.ops_label = self._make_item("🖱  0 次", "#80868B")
        self.limit_label = self._make_item("", "#80868B")       # 运行上限警告
        self.dry_label = self._make_item("🧪 沙盒关", "#80868B")
        self.window_label = self._make_item("📅 —", "#80868B")

        layout.addWidget(self.run_label)
        layout.addWidget(self.conn_label)
        layout.addWidget(self.task_label)
        layout.addWidget(self.scene_label)
        layout.addWidget(self.acct_label)
        layout.addWidget(self.ops_label)
        layout.addWidget(self.limit_label)
        layout.addWidget(self.dry_label)
        layout.addWidget(self.window_label)
        layout.addStretch()

        self.setStyleSheet("""
            StatusBar {
                background: #F8F9FA;
                border-top: 1px solid #E8ECF0;
                border-radius: 0;
            }
        """)

    def _make_item(self, text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Microsoft YaHei", 9))
        lbl.setStyleSheet(f"color: {color}; padding: 2px 0;")
        return lbl

    def set_run_status(self, status: str):
        mapping = {
            "running": ("●  运行中", "#1A73E8"),
            "paused": ("⏸  已暂停", "#F9AB00"),
            "stopped": ("●  已停止", "#80868B"),
            "error": ("⚠  异常", "#EA4335"),
        }
        text, color = mapping.get(status, (f"●  {status}", "#80868B"))
        self.run_label.setText(text)
        self.run_label.setStyleSheet(f"color: {color}; padding: 2px 0;")

    def set_connection(self, status: str):
        mapping = {
            "connected": ("🔌  已连接", "#34A853"),
            "disconnected": ("🔌  未连接", "#80868B"),
            "reconnecting": ("🔌  重连中...", "#F9AB00"),
        }
        text, color = mapping.get(status, (f"🔌  {status}", "#80868B"))
        self.conn_label.setText(text)
        self.conn_label.setStyleSheet(f"color: {color}; padding: 2px 0;")

    def set_account(self, name: str):
        self.acct_label.setText(f"👤  {name}" if name else "👤  —")

    def set_ops_count(self, count: int):
        self.ops_label.setText(f"🖱  {count} 次")

    def set_dry_run(self, enabled: bool):
        self.dry_label.setText("🧪 沙盒开" if enabled else "🧪 沙盒关")
        self.dry_label.setStyleSheet(f"color: {'#F9AB00' if enabled else '#80868B'}; padding: 2px 0;")

    def set_runtime_window(self, start: str, end: str):
        self.window_label.setText(f"📅 {start}-{end}" if start and end else "📅 —")
        self.window_label.setStyleSheet("color: #80868B; padding: 2px 0;")

    # ==================== 新增：对齐 07 模块 ====================

    def set_current_task(self, task: str | None, step: str | None = None):
        """显示当前任务+步骤，数据源 StateKeys.CURRENT_TASK / CURRENT_STEP。"""
        if task:
            text = f"📋  {task}"
            if step:
                text += f"·{step}"
            self.task_label.setText(text)
            self.task_label.setStyleSheet("color: #1A73E8; padding: 2px 0; font-weight: bold;")
        else:
            self.task_label.setText("📋  —")
            self.task_label.setStyleSheet("color: #80868B; padding: 2px 0;")

    def set_current_scene(self, scene: str | None):
        """显示当前游戏场景，数据源 StateKeys.CURRENT_SCENE。"""
        icon = SCENE_ICONS.get(scene, "❓")
        label = scene or "未知"
        self.scene_label.setText(f"{icon}  {label}")
        self.scene_label.setStyleSheet("color: #5F6368; padding: 2px 0;")

    def set_run_limit_reached(self, reached: bool):
        """运行上限警告，数据源 StateKeys.RUN_LIMIT_REACHED。"""
        if reached:
            self.limit_label.setText("⛔ 已达上限")
            self.limit_label.setStyleSheet("color: #EA4335; padding: 2px 0; font-weight: bold;")
        else:
            self.limit_label.setText("")
            self.limit_label.setStyleSheet("color: #80868B; padding: 2px 0;")

    def update_last_operation(self, op: dict | None):
        """更新最后操作 tooltip（14-执行器模块触点）。"""
        if op:
            tmpl = op.get("template", op.get("type", "?"))
            elapsed = op.get("elapsed", 0)
            success = "✓" if op.get("success") else "✗"
            self.ops_label.setToolTip(
                f"上次操作: {success} {tmpl} ({elapsed:.2f}s)")
        else:
            self.ops_label.setToolTip("")
