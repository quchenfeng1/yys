"""
UI 子面板：TaskQueuePanel 任务队列卡片（含进度展示）。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)


class TaskQueuePanel(QWidget):
    """任务队列面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("任务队列"))

        self.queue_list = QListWidget()
        layout.addWidget(self.queue_list)

        # 控制按钮
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(QPushButton("上移"))
        btn_layout.addWidget(QPushButton("下移"))
        btn_layout.addWidget(QPushButton("移除"))
        btn_layout.addWidget(QPushButton("清空"))
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 进度
        layout.addWidget(QLabel("总体进度"))
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

    def add_task(self, task_id: str, name: str) -> None:
        item = QListWidgetItem(f"{name} ({task_id})")
        self.queue_list.addItem(item)

    def clear(self) -> None:
        self.queue_list.clear()

    def set_progress(self, value: int) -> None:
        self.progress_bar.setValue(value)

    # ── MainWindow 调用的事件响应方法 ─────────────────────

    def on_task_started(self, task_id: str) -> None:
        """任务开始执行时高亮当前任务（§3.2）"""
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            if task_id in item.text():
                item.setBackground(Qt.yellow)
                break

    def on_task_done(self) -> None:
        """任务完成时移除顶部任务并刷新卡片（§3.2）"""
        if self.queue_list.count() > 0:
            self.queue_list.takeItem(0)

    def refresh_queue(self, queue: list) -> None:
        """重建队列卡片列表（§3.2）"""
        self.queue_list.clear()
        for item in queue:
            if isinstance(item, str):
                self.queue_list.addItem(item)
            elif isinstance(item, dict):
                name = item.get("name", str(item))
                self.queue_list.addItem(name)
