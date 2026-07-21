"""
倒计时标签（11-用户界面模块）

显示距离任务下次执行的剩余时间，自动每秒刷新。
"""

from datetime import datetime
from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import QTimer


class CountdownLabel(QLabel):
    """倒计时标签：绑定 next_run_time，自动每秒刷新。"""

    def __init__(self, next_run_time: datetime = None, parent=None):
        super().__init__(parent)
        self._next_run = next_run_time
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._refresh()
        if next_run_time:
            self._timer.start(1000)

    def set_next_run(self, dt: datetime | None):
        """更新目标时间。"""
        self._next_run = dt
        self._refresh()
        if dt:
            if not self._timer.isActive():
                self._timer.start(1000)
        else:
            self._timer.stop()
            self.setText("—")

    def _refresh(self):
        if not self._next_run:
            self.setText("—")
            return

        delta = self._next_run - datetime.now()
        total_sec = int(delta.total_seconds())

        if total_sec <= 0:
            self.setText("已到期")
            self.setStyleSheet("color:#EA4335;font-weight:bold;font-size:12px;")
            self._timer.stop()
            return

        hours = total_sec // 3600
        minutes = (total_sec % 3600) // 60
        seconds = total_sec % 60

        if hours > 0:
            text = f"{hours}时{minutes}分后"
        elif minutes > 0:
            text = f"{minutes}分{seconds}秒后"
        else:
            text = f"{seconds}秒后"

        self.setText(text)
        # 颜色：<5分钟 红 / <30分钟 橙 / 其余 灰
        if total_sec < 300:
            color = "#EA4335"
        elif total_sec < 1800:
            color = "#F9AB00"
        else:
            color = "#80868B"
        self.setStyleSheet(f"color:{color};font-size:12px;")
