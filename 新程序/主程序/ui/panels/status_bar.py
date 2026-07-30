"""
UI 子面板：StatusBar 底部状态栏。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget


# ── 状态着色 —— 与设计书 §3.2 优先级色阶一致 ─────────────
_STATUS_COLORS = {
    "running": "#4CAF50",     # 运行中-绿
    "paused": "#FF9800",      # 暂停-橙
    "stopped": "#9E9E9E",    # 停止-灰
    "error": "#F44336",       # 异常-红
    "connected": "#4CAF50",   # 已连接-绿
    "disconnected": "#F44336", # 断开-红
    "warning": "#FF9800",     # 告警-橙
}


class StatusBar(QWidget):
    """底部状态栏（§3.7 9 项）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #888;")

        self.task_label = QLabel("")
        self.task_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

        self.connection_label = QLabel("")
        self.account_label = QLabel("")
        self.duration_label = QLabel("")
        self.queue_label = QLabel("")
        self.mode_label = QLabel("")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setTextVisible(True)

        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignRight)

        layout.addWidget(self.status_label, 0)
        layout.addWidget(self.task_label, 1)
        layout.addWidget(self.connection_label, 0)
        layout.addWidget(self.account_label, 0)
        layout.addWidget(self.duration_label, 0)
        layout.addWidget(self.queue_label, 0)
        layout.addWidget(self.mode_label, 0)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.info_label, 1)

    # ── §3.7 状态栏方法 ──────────────────────────────────

    def show_message(self, message: str, timeout: int = 5000) -> None:
        """显示状态消息"""
        self.status_label.setText(message)

    def set_progress(self, value: int) -> None:
        """设置进度 0-100"""
        self.progress_bar.setValue(value)

    def set_info(self, text: str) -> None:
        """设置右侧信息"""
        self.info_label.setText(text)

    def update_run_status(self, status: str) -> None:
        """更新运行状态显示（§3.7 第1项）"""
        color = _STATUS_COLORS.get(status, "#888")
        label_map = {"running": "运行中", "paused": "已暂停", "stopped": "已停止", "error": "异常"}
        self.status_label.setText(label_map.get(status, status))
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def update_current_task(self, task_name: str | None) -> None:
        """更新当前任务显示（§3.7 第2项）"""
        if task_name:
            self.task_label.setText(f"当前: {task_name}")
        else:
            self.task_label.setText("")

    def update_connection(self, status: str) -> None:
        """更新连接状态显示（§3.7 第3项）"""
        color = _STATUS_COLORS.get(status, "#888")
        label_map = {"connected": "已连接", "disconnected": "未连接", "reconnecting": "重连中"}
        self.connection_label.setText(f"连接: {label_map.get(status, status)}")
        self.connection_label.setStyleSheet(f"color: {color};")

    def update_quality(self, level: str) -> None:
        """更新连接质量指示（§3.7 第4项）"""
        color = _STATUS_COLORS.get(level, "#888")
        label_map = {"good": "质量: 良好", "warning": "质量: 延迟高", "poor": "质量: 不稳定"}
        self.connection_label.setText(label_map.get(level, f"质量: {level}"))
        self.connection_label.setStyleSheet(f"color: {color};")

    def update_current_account(self, account: str) -> None:
        """更新当前账号显示（§3.7 第5项）"""
        self.account_label.setText(f"账号: {account}" if account else "")

    def update_run_duration(self, duration: float | str) -> None:
        """更新运行时长显示（§3.7 第6项）"""
        if isinstance(duration, (int, float)):
            hours = int(duration // 3600)
            minutes = int((duration % 3600) // 60)
            seconds = int(duration % 60)
            self.duration_label.setText(f"时长: {hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self.duration_label.setText(f"时长: {duration}")

    def update_queue_length(self, length: int) -> None:
        """更新队列长度显示（§3.7 第7项）"""
        self.queue_label.setText(f"队列: {length}个")

    def update_dry_run_mode(self, enabled: bool) -> None:
        """更新沙盒模式显示（§3.7 第9项）"""
        if enabled:
            self.mode_label.setText("沙盒模式")
            self.mode_label.setStyleSheet("color: #FF9800; font-weight: bold;")
        else:
            self.mode_label.setText("")

    def reset_all(self) -> None:
        """重置所有状态显示"""
        self.status_label.setText("就绪")
        self.status_label.setStyleSheet("color: #888;")
        self.task_label.setText("")
        self.connection_label.setText("")
        self.account_label.setText("")
        self.duration_label.setText("")
        self.queue_label.setText("")
        self.mode_label.setText("")
        self.progress_bar.setValue(0)
