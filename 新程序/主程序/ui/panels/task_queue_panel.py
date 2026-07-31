"""
UI 子面板：TaskQueuePanel 任务队列面板（四区布局）。

上方：正在执行的任务
下方：待执行（到期队列） | 未开始（未到时间） | 已失效（过期/待配置）
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)


class TaskQueuePanel(QWidget):
    """任务队列面板（四区）"""

    # 手动触发触发式任务（trigger）——由 MainWindow 连接 TaskBridge.update_next_run
    manual_trigger_requested = pyqtSignal(str)


    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("任务队列"))

        # ── 上方：正在执行 ──────────────────────────────────
        current_frame = QFrame()
        current_frame.setFrameShape(QFrame.StyledPanel)
        cur_layout = QVBoxLayout(current_frame)
        cur_layout.addWidget(QLabel("▶ 正在执行"))
        self.current_label = QLabel("（无）")
        self.current_label.setStyleSheet(
            "font-size:16px; font-weight:bold; color:#4CAF50; padding:8px;")
        self.current_label.setWordWrap(True)
        cur_layout.addWidget(self.current_label)
        layout.addWidget(current_frame)

        # ── 下方：待执行 / 未开始 / 已失效（三栏） ────────
        splitter = QSplitter(Qt.Horizontal)

        # 左：待执行
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("⏳ 待执行"))
        self.pending_list = QListWidget()
        ll.addWidget(self.pending_list)
        splitter.addWidget(left)

        # 中：未开始
        middle = QWidget()
        ml = QVBoxLayout(middle)
        ml.addWidget(QLabel("🕐 未开始"))
        self.upcoming_list = QListWidget()
        ml.addWidget(self.upcoming_list)
        splitter.addWidget(middle)

        # 右：已失效
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("⚠ 已失效"))
        self.invalid_list = QListWidget()
        rl.addWidget(self.invalid_list)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        layout.addWidget(splitter, 1)

        # 总体进度
        layout.addWidget(QLabel("总体进度"))
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

    # ── 四区更新（MainWindow 调用） ───────────────────────

    def update_panel(self, current: str | None, pending: list,
                     upcoming: list[dict[str, Any]], invalid: list | None = None) -> None:
        """一次性更新四区：正在执行 / 待执行 / 未开始 / 已失效"""
        self._set_current(current or "")
        self._set_pending(pending)
        self._set_upcoming(upcoming)
        self._set_invalid(invalid or [])

    def _set_invalid(self, invalid: list) -> None:
        self.invalid_list.clear()
        for item in invalid:
            if isinstance(item, dict):
                name = item.get("name", "")
                status = item.get("status", "")
                detail = item.get("detail", "")
                text = f"{name}  [{status}]"
                if detail:
                    text += f"  · {detail}"
                self.invalid_list.addItem(text)
            else:
                self.invalid_list.addItem(str(item))

    def _set_current(self, task: str) -> None:
        if task:
            self.current_label.setText(task)
            self.current_label.setStyleSheet(
                "font-size:16px; font-weight:bold; color:#4CAF50; padding:8px;")
        else:
            self.current_label.setText("（无）")
            self.current_label.setStyleSheet(
                "font-size:16px; color:#888; padding:8px;")

    def _set_pending(self, pending: list) -> None:
        self.pending_list.clear()
        for item in pending:
            if isinstance(item, dict):
                name = item.get("name", str(item))
                nrt = item.get("next_run", "")
                self.pending_list.addItem(f"{name}  ({nrt})" if nrt else name)
            else:
                self.pending_list.addItem(str(item))

    def _set_upcoming(self, upcoming: list) -> None:
        self.upcoming_list.clear()
        for item in upcoming:
            if isinstance(item, dict):
                name = item.get("name", "")
                nrt = item.get("next_run", "")
                is_trigger = not nrt  # 无 next_run → 触发式任务（待触发）
                if is_trigger:
                    # 触发式任务：显示"待触发" + 手动触发按钮
                    li = QListWidgetItem(f"⚡ {name}  [待触发]")
                    li.setData(Qt.UserRole, name)
                    self.upcoming_list.addItem(li)
                    idx = self.upcoming_list.count() - 1
                    row = QWidget()
                    h = QHBoxLayout(row)
                    h.setContentsMargins(6, 2, 6, 2)
                    lbl = QLabel(f"⚡ {name}  [待触发]")
                    btn = QPushButton("⚡触发")
                    btn.setMaximumWidth(64)
                    btn.setToolTip("手动触发：立即加入执行队列")
                    btn.clicked.connect(
                        lambda _=False, n=name: self.manual_trigger_requested.emit(n))
                    h.addWidget(lbl, 1)
                    h.addWidget(btn)
                    self.upcoming_list.setItemWidget(li, row)
                else:
                    self.upcoming_list.addItem(f"{name}  ({nrt})")
            else:
                self.upcoming_list.addItem(str(item))

    # ── 兼容旧方法（MainWindow 现有调用） ─────────────────

    def add_task(self, task_id: str, name: str) -> None:
        self.pending_list.addItem(f"{name} ({task_id})")

    def clear(self) -> None:
        self.pending_list.clear()
        self.upcoming_list.clear()
        self.invalid_list.clear()

    def set_progress(self, value: int) -> None:
        self.progress_bar.setValue(value)

    def on_task_started(self, task_id: str) -> None:
        """任务开始执行 → 上方显示当前任务"""
        self._set_current(task_id)

    def on_task_done(self) -> None:
        """任务完成 → 清空当前任务"""
        self._set_current("")

    def refresh_queue(self, queue: list) -> None:
        """重建待执行列表（§3.2）"""
        self._set_pending(queue)
