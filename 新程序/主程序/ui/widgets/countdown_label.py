"""
11-用户界面模块

CountdownLabel 可复用组件（§5.1）。
倒计时标签：显示 next_run_time 的倒计时。
"""
from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QLabel


class CountdownLabel(QLabel):
    """倒计时标签"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target: datetime | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_display)
        self._timer.start(1000)  # 每秒更新
        self.setText("--:--:--")

    def set_target(self, target: datetime | None) -> None:
        """设置目标时间"""
        self._target = target
        self._update_display()

    def _update_display(self) -> None:
        if not self._target:
            self.setText("--:--:--")
            return
        now = datetime.now()
        if now >= self._target:
            self.setText("已到期")
            return
        delta = self._target - now
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        secs = delta.seconds % 60
        if days > 0:
            self.setText(f"{days}d {hours:02d}:{minutes:02d}:{secs:02d}")
        else:
            self.setText(f"{hours:02d}:{minutes:02d}:{secs:02d}")
