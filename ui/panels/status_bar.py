"""
底部状态栏（v2.2 现代风格）

展示：运行状态 | 连接状态 | 当前账号 | 今日操作次数。
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt5.QtGui import QFont


class StatusBar(QWidget):
    """底部状态展示栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(24)

        self.run_label = self._make_item("●  已停止", "#80868B")
        self.conn_label = self._make_item("🔌  未连接", "#80868B")
        self.acct_label = self._make_item("👤  —", "#80868B")
        self.ops_label = self._make_item("🖱  0 次", "#80868B")

        layout.addWidget(self.run_label)
        layout.addWidget(self.conn_label)
        layout.addWidget(self.acct_label)
        layout.addWidget(self.ops_label)
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
