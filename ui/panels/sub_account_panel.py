"""
11-用户界面模块 — 小号状态监控面板

职责：
  展示小号实时状态：当前登录了哪些小号、正在做什么
  数据来源：07-运行时状态管理.sub_account_status

放置位置：
  任务队列面板下方，与主号任务队列上下排列
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor


# 状态→颜色映射
STATUS_COLORS = {
    "idle":     QColor(180, 180, 180),   # 灰色
    "login":    QColor(100, 180, 255),   # 蓝色
    "scanning": QColor(255, 200, 50),    # 黄色
    "teaming":  QColor(100, 200, 100),   # 绿色
    "battling": QColor(255, 100, 100),   # 红色
    "error":    QColor(255, 50, 50),     # 暗红
}


class SubAccountCard(QFrame):
    """单个小号的状态卡片"""

    def __init__(self, account_id: str, parent=None):
        super().__init__(parent)
        self.account_id = account_id
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(50)
        self.setMaximumHeight(70)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # 小号 ID
        self._id_label = QLabel(account_id)
        self._id_label.setStyleSheet("font-weight: bold; min-width: 50px;")
        layout.addWidget(self._id_label)

        # 状态徽章
        self._status_label = QLabel("● idle")
        self._status_label.setStyleSheet("min-width: 70px;")
        layout.addWidget(self._status_label)

        # 当前任务
        self._task_label = QLabel("等待中")
        self._task_label.setStyleSheet("color: #666;")
        layout.addWidget(self._task_label, 1)

        # 进度
        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #999; min-width: 60px;")
        layout.addWidget(self._progress_label)

    def update_status(self, status: dict):
        """更新小号状态显示"""
        state = status.get("status", "idle")
        task = status.get("task", "")
        progress = status.get("progress", "")

        # 状态文字 + 颜色
        color = STATUS_COLORS.get(state, QColor(180, 180, 180))
        self._status_label.setText(f"● {state}")
        self._status_label.setStyleSheet(f"color: {color.name()}; min-width: 70px;")

        # 任务描述
        self._task_label.setText(task if task else "等待中")

        # 进度
        self._progress_label.setText(progress)


class SubAccountStatusPanel(QWidget):
    """小号状态监控面板"""

    def __init__(self, state_manager, parent=None):
        super().__init__(parent)
        self._state = state_manager
        self._cards: dict[str, SubAccountCard] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        # 标题
        header = QLabel("📋 小号状态")
        header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px 0;")
        layout.addWidget(header)

        # 卡片容器
        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(2)
        layout.addLayout(self._cards_layout)

        layout.addStretch()

        # 定时刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)  # 每 2 秒刷新

    def _refresh(self):
        """从 07 状态管理读取小号状态并更新卡片"""
        if not self._state:
            return
        status_dict = self._state.get_state("sub_account_status", {})
        if not status_dict:
            # 无数据时显示占位
            if not self._cards_layout.count():
                placeholder = QLabel("无小号信息")
                placeholder.setStyleSheet("color: #999; padding: 8px;")
                self._cards_layout.addWidget(placeholder)
            return

        # 清理占位
        for i in reversed(range(self._cards_layout.count())):
            item = self._cards_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QLabel):
                item.widget().deleteLater()

        # 更新卡片
        for acc_id, status in status_dict.items():
            if acc_id not in self._cards:
                card = SubAccountCard(acc_id)
                self._cards[acc_id] = card
                self._cards_layout.addWidget(card)
            self._cards[acc_id].update_status(status)

        # 移除已经不存在的卡片
        existing = set(status_dict.keys())
        for acc_id in list(self._cards.keys()):
            if acc_id not in existing:
                self._cards[acc_id].deleteLater()
                del self._cards[acc_id]

    def set_state_manager(self, state_manager):
        """外部注入状态管理实例"""
        self._state = state_manager
