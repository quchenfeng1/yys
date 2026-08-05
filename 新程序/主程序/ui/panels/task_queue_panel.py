"""
UI 子面板：TaskQueuePanel 任务队列面板（四区布局，卡片样式）。

上方：正在执行的任务（大卡片）
下方：待执行（到期队列） | 未开始（未到时间） | 已失效（过期/待配置）
每个列表项为 TaskCard 卡片：优先级徽章 + 名称 + 副信息 + 可选操作按钮。
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

# 优先级色阶（11-用户界面模块 §3.2）
_PRIORITY_COLORS = {
    1: "#e53935", 2: "#fb8c00", 3: "#fdd835", 5: "#43a047",
    10: "#1e88e5", 20: "#8e24aa", 99: "#9e9e9e",
}
_DEFAULT_BADGE = "#9e9e9e"
_CARD_HEIGHT = 62

# 面板全局样式（卡片 + 列表）
_PANEL_QSS = """
QFrame#TaskCard {
    background: #fbfbfd;
    border: 1px solid #d8dbe0;
}
QFrame#TaskCard:hover { background: #f0f5ff; border-color: #4a90d9; }
QLabel#card_title { font-size: 13px; font-weight: bold; color: #222; background: transparent; }
QLabel#card_sub   { font-size: 11px; color: #888; background: transparent; }
QListWidget {
    background: transparent;
    border: none;
    padding: 0px;
}
QListWidget::item {
    padding: 0px;
    margin: 0px;
    background: transparent;
}
QGroupBox {
    font-size: 12px; font-weight: bold; color: #333;
    border: 1px solid #c8ccd4;
    margin-top: 0px; padding-top: 4px;
    padding-left: 0px; padding-right: 0px; padding-bottom: 0px;
    background: #f7f8fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px; padding: 0 4px;
    background: #f7f8fa; color: #333;
}
QFrame#CurrentCard {
    background: #eef7ee;
    border: 1px solid #4CAF50;
}
QPushButton {
    border: 1px solid #1e88e5; background: #e8f1fc;
    color: #1565c0; padding: 2px 8px; font-size: 11px;
}
QPushButton:hover { background: #d4e6fb; }
QPushButton#card_action_btn {
    border: 1px solid #1e88e5; background: #1e88e5;
    color: #fff; font-weight: bold; font-size: 12px;
}
QPushButton#card_action_btn:hover { background: #1565c0; }
"""


class TaskCard(QFrame):
    """任务卡片：优先级徽章 + 名称 + 副信息 + 可选操作按钮"""

    def __init__(
        self,
        title: str = "",
        sub: str = "",
        badge_text: str | None = None,
        badge_color: str | None = None,
        action_text: str | None = None,
        on_action: Callable[[], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("TaskCard")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(9, 5, 9, 5)
        outer.setSpacing(6)

        # ── 左侧内容区（徽章 + 标题 + 副信息） ────────────
        content = QVBoxLayout()
        content.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(7)
        if badge_text:
            badge = QLabel(badge_text)
            badge.setObjectName("card_badge")
            badge.setStyleSheet(
                f"color:#fff; padding:1px 7px; font-size:10px; "
                f"background:{badge_color or _DEFAULT_BADGE};")
            row.addWidget(badge)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("card_title")
        row.addWidget(title_lbl, 1)
        content.addLayout(row)
        if sub:
            sub_lbl = QLabel(sub)
            sub_lbl.setObjectName("card_sub")
            content.addWidget(sub_lbl)
        outer.addLayout(content, 1)

        # ── 右侧操作按钮区（卡片一分为二：右侧小部分为按钮）──
        if action_text and on_action is not None:
            btn = QPushButton(action_text)
            btn.setObjectName("card_action_btn")
            btn.setFixedWidth(58)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False: on_action())
            outer.addWidget(btn, 0)


class TaskQueuePanel(QWidget):
    """任务队列面板（四区，卡片样式）"""

    # 手动触发触发式任务（trigger）——由 MainWindow 连接 TaskBridge.update_next_run
    manual_trigger_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_PANEL_QSS)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        # ── 面板标题（普通嵌入标签，与其他面板一致） ──
        layout.addWidget(QLabel("任务队列"))

        # ── 上方：正在执行（大卡片） ───────────────────────
        current_frame = QFrame()
        current_frame.setObjectName("CurrentCard")
        cur_layout = QVBoxLayout(current_frame)
        cur_layout.setContentsMargins(10, 8, 10, 8)
        cur_layout.addWidget(QLabel("▶ 正在执行"))
        self.current_label = QLabel("（无）")
        self.current_label.setStyleSheet(
            "font-size:16px; font-weight:bold; color:#2e7d32; padding:6px;")
        self.current_label.setWordWrap(True)
        cur_layout.addWidget(self.current_label)
        layout.addWidget(current_frame)

        # ── 下方：待执行 / 未开始 / 已失效（三栏卡片列表） ──
        splitter = QSplitter(Qt.Horizontal)

        # 左：待执行（容器框）
        from ui.theme import panel_group
        left_box, ll = panel_group("⏳ 待执行")
        ll.setSpacing(2)
        ll.setContentsMargins(6, 2, 6, 6)
        self.pending_list = QListWidget()
        self.pending_list.setSpacing(2)
        ll.addWidget(self.pending_list)
        splitter.addWidget(left_box)

        # 中：未开始（容器框）
        middle_box, ml = panel_group("🕐 未开始")
        ml.setSpacing(2)
        ml.setContentsMargins(6, 2, 6, 6)
        self.upcoming_list = QListWidget()
        self.upcoming_list.setSpacing(2)
        ml.addWidget(self.upcoming_list)
        splitter.addWidget(middle_box)

        # 右：已失效（容器框）
        right_box, rl = panel_group("⚠ 已失效")
        rl.setSpacing(2)
        rl.setContentsMargins(6, 2, 6, 6)
        self.invalid_list = QListWidget()
        self.invalid_list.setSpacing(2)
        rl.addWidget(self.invalid_list)
        splitter.addWidget(right_box)

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

    # ── 卡片渲染辅助 ─────────────────────────────────────

    @staticmethod
    def _badge_color(priority: Any) -> str:
        try:
            return _PRIORITY_COLORS.get(int(priority), _DEFAULT_BADGE)
        except (TypeError, ValueError):
            return _DEFAULT_BADGE

    @staticmethod
    def _add_card(lw: QListWidget, title: str = "", sub: str = "",
                  badge_text: str | None = None, badge_color: str | None = None,
                  action_text: str | None = None,
                  on_action: Callable[[], None] | None = None) -> None:
        """向列表添加一张任务卡片"""
        li = QListWidgetItem()
        li.setSizeHint(QSize(0, _CARD_HEIGHT))
        card = TaskCard(title=title, sub=sub, badge_text=badge_text,
                        badge_color=badge_color, action_text=action_text,
                        on_action=on_action)
        lw.addItem(li)
        lw.setItemWidget(li, card)

    def _set_invalid(self, invalid: list) -> None:
        self.invalid_list.clear()
        for item in invalid:
            if isinstance(item, dict):
                name = item.get("name", "")
                status = item.get("status", "")
                detail = item.get("detail", "")
                color = _DEFAULT_BADGE
                if status in ("已过期",):
                    color = "#9e9e9e"
                elif status in ("待配置",):
                    color = "#fb8c00"
                elif status in ("待触发", "等待下次触发"):
                    color = "#1e88e5"
                    # 触发式任务：已失效区也可手动触发（未触发/已执行完统一在此区）
                    self._add_card(
                        self.invalid_list, title=f"⚡ {name}", sub=detail or "",
                        badge_text=status, badge_color=color,
                        action_text="⚡触发",
                        on_action=lambda n=name: self.manual_trigger_requested.emit(n),
                    )
                    continue
                elif status in ("已跳过",):
                    color = "#e53935"
                self._add_card(self.invalid_list, title=name, sub=detail or "",
                               badge_text=status, badge_color=color)
            else:
                self._add_card(self.invalid_list, title=str(item))

    def _set_current(self, task: str) -> None:
        if task:
            self.current_label.setText(task)
            self.current_label.setStyleSheet(
                "font-size:16px; font-weight:bold; color:#2e7d32; padding:6px;")
        else:
            self.current_label.setText("（无）")
            self.current_label.setStyleSheet(
                "font-size:15px; color:#aaa; padding:6px;")

    def _set_pending(self, pending: list) -> None:
        self.pending_list.clear()
        for item in pending:
            if isinstance(item, dict):
                name = item.get("name", str(item))
                nrt = item.get("next_run", "")
                pri = item.get("priority")
                badge = f"P{int(pri)}" if pri else None
                sub = f"⏱ {nrt}" if nrt else "等待执行"
                self._add_card(
                    self.pending_list, title=name, sub=sub,
                    badge_text=badge,
                    badge_color=self._badge_color(pri) if pri else None,
                )
            else:
                self._add_card(self.pending_list, title=str(item))

    def _set_upcoming(self, upcoming: list) -> None:
        self.upcoming_list.clear()
        for item in upcoming:
            if isinstance(item, dict):
                name = item.get("name", "")
                nrt = item.get("next_run", "")
                if not nrt:
                    # 触发式任务：待触发 + 手动触发按钮
                    self._add_card(
                        self.upcoming_list, title=f"⚡ {name}", sub="等待外部触发",
                        badge_text="待触发", badge_color="#1e88e5",
                        action_text="⚡触发",
                        on_action=lambda n=name: self.manual_trigger_requested.emit(n),
                    )
                else:
                    self._add_card(
                        self.upcoming_list, title=name, sub=f"⏱ {nrt}",
                        badge_text="未开始", badge_color="#1e88e5",
                    )
            else:
                self._add_card(self.upcoming_list, title=str(item))

    # ── 兼容旧方法（MainWindow 现有调用） ─────────────────

    def add_task(self, task_id: str, name: str) -> None:
        self._add_card(self.pending_list, title=name, sub=task_id)

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
