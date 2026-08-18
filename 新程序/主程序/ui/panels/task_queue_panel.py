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
    QPushButton, QSplitter, QVBoxLayout, QWidget,
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
    # 后台线程事件 → 主线程 UI 更新（执行进度实时同步，2026-08-16）
    _ui_signal = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_PANEL_QSS)
        self._ui_signal.connect(lambda fn: fn())
        self._last_current: str | None = None
        self._progress_cache: dict[str, dict] = {}   # 任务 → 最近进度快照
        # 执行进度事件订阅（可视化任务 ProgressTracker 发布）
        try:
            from core.event_bus import get_global_bus
            from core.events import Events
            get_global_bus().subscribe(Events.VISUAL_PROGRESS,
                                       self._on_visual_progress)
        except Exception:
            pass
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
        # 暂停中任务（2026-08-16 信号体系）：等待信号/超时的挂起任务
        self.paused_label = QLabel("")
        self.paused_label.setStyleSheet(
            "color:#e65100; font-size:12px; padding:2px 6px;")
        self.paused_label.setWordWrap(True)
        self.paused_label.setVisible(False)
        cur_layout.addWidget(self.paused_label)
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

        # 待触发（2026-08-16 信号体系：含任务信号触发器节点的任务，
        # 到期后不进待执行，等待任务信号激活）
        trigger_box, tl = panel_group("📡 待触发")
        tl.setSpacing(2)
        tl.setContentsMargins(6, 2, 6, 6)
        self.trigger_list = QListWidget()
        self.trigger_list.setSpacing(2)
        tl.addWidget(self.trigger_list)
        splitter.addWidget(trigger_box)

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
        splitter.setStretchFactor(3, 1)
        layout.addWidget(splitter, 1)

        # ── 当前步骤 + 执行进度抽屉（2026-08-16 替换「总体进度」条） ──
        step_row = QHBoxLayout()
        step_row.setSpacing(8)
        step_row.addWidget(QLabel("当前步骤"))
        self.step_label = QLabel("无")
        self.step_label.setStyleSheet(
            "font-size:12px; font-weight:bold; color:#1565c0;")
        self.step_label.setWordWrap(True)
        step_row.addWidget(self.step_label, 1)
        self.drawer_btn = QPushButton("🔽 进度图")
        self.drawer_btn.setCheckable(True)
        self.drawer_btn.setChecked(False)   # 默认收起（只显示转圈+进度字段）
        self.drawer_btn.setCursor(Qt.PointingHandCursor)
        self.drawer_btn.clicked.connect(self._on_drawer_toggled)
        step_row.addWidget(self.drawer_btn)
        layout.addLayout(step_row)

        # 收起态：蓝色转圈小图标 + 当前进度字段
        from ui.panels.progress_thumb import ProgressThumb, SpinningDot
        self.collapsed_row = QWidget()
        cr = QHBoxLayout(self.collapsed_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        self.spinner = SpinningDot(12)
        self.spinner.setVisible(False)   # 有步骤时才显示转圈（2026-08-16）
        self.progress_summary = QLabel("")
        self.progress_summary.setStyleSheet("color:#666; font-size:12px;")
        cr.addWidget(self.spinner)
        cr.addWidget(self.progress_summary, 1)
        layout.addWidget(self.collapsed_row)

        # 展开态：进度图（o-o-o 缩略图，蓝箭头=游标路径）
        self.thumb = ProgressThumb()
        layout.addWidget(self.thumb)
        self._on_drawer_toggled()

    # ── 执行进度抽屉（2026-08-16）──────────────────────

    def _on_drawer_toggled(self) -> None:
        """抽屉：展开显示进度图；收起只显示转圈图标 + 当前进度字段"""
        expanded = self.drawer_btn.isChecked()
        self.thumb.setVisible(expanded)
        self.collapsed_row.setVisible(not expanded)
        self.drawer_btn.setText("🔼 进度图" if expanded else "🔽 进度图")

    def _on_visual_progress(self, **kw) -> None:
        """（后台线程）进度快照 → 缓存 + 投递主线程"""
        try:
            task_id = kw.get("task_id", "")
            snap = {k: kw[k] for k in
                    ("task_id", "current", "points", "states", "edges")
                    if k in kw}
            if not task_id:
                return
            self._progress_cache[task_id] = snap
            self._ui_signal.emit(lambda: self._apply_snapshot(snap))
        except Exception:
            pass

    def _apply_snapshot(self, snap: dict) -> None:
        """（主线程）当前任务快照 → 步骤名 / 进度字段 / 转圈 / 进度图"""
        if snap.get("task_id") != self._last_current:
            return
        points = snap.get("points") or []
        states = snap.get("states") or {}
        done = sum(1 for p in points if states.get(p["id"]) == "green")
        running = any(states.get(p["id"]) == "blue" for p in points)
        failed = any(states.get(p["id"]) == "red" for p in points)
        cur = snap.get("current") or ""
        self.step_label.setText(cur or "无")
        # 转圈图标：有步骤才显示；运行中旋转（2026-08-16）
        self.spinner.setVisible(bool(cur))
        self.spinner.set_spinning(bool(cur and running and not failed))
        if points:
            text = f"进度 {done}/{len(points)}"
            if failed:
                text += "（失败）"
            self.progress_summary.setText(text)
        else:
            self.progress_summary.setText("")
        self.thumb.update_snapshot(snap)

    def _reset_progress_view(self, task: str) -> None:
        """切换任务：清空/回显该任务的进度视图"""
        self.step_label.setText("无")
        self.progress_summary.setText("")
        self.spinner.setVisible(False)
        self.spinner.set_spinning(False)
        cached = self._progress_cache.get(task)
        if cached:
            self._apply_snapshot(cached)
        else:
            self.thumb.update_snapshot(None)

    # ── 五区更新（MainWindow 调用） ───────────────────────

    def update_panel(self, current: str | None, pending: list,
                     upcoming: list[dict[str, Any]], invalid: list | None = None,
                     trigger: list | None = None,
                     paused: list | None = None) -> None:
        """一次性更新各区：正在执行 / 待执行 / 待触发 / 未开始 / 已失效"""
        self._set_current(current or "")
        self._set_pending(pending)
        self._set_trigger(trigger or [])
        self._set_upcoming(upcoming)
        self._set_invalid(invalid or [])
        self._set_paused(paused or [])

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
                elif status in ("已达上限",):
                    # 触发已达周期最大次数 → 触发按钮失效（不可再触发）
                    color = "#e53935"
                    badge = "已达上限"
                    self._add_card(
                        self.invalid_list, title=f"🚫 {name}", sub=detail or "",
                        badge_text=badge, badge_color=color,
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
        # 任务切换 → 重置执行进度视图（2026-08-16）
        if task != self._last_current:
            self._last_current = task
            self._reset_progress_view(task)

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

    def _set_trigger(self, trigger: list) -> None:
        """待触发区（2026-08-16 信号体系）：等待任务信号的触发任务"""
        self.trigger_list.clear()
        for item in trigger:
            if isinstance(item, dict):
                name = item.get("name", "")
                nrt = item.get("next_run", "")
                pri = item.get("priority")
                sub = f"⏱ {nrt}" if nrt else "等待任务信号"
                self._add_card(
                    self.trigger_list, title=f"📡 {name}", sub=sub,
                    badge_text="待触发", badge_color="#1e88e5",
                )
                _ = pri
            else:
                self._add_card(self.trigger_list, title=str(item))

    def _set_paused(self, paused: list) -> None:
        """暂停展示（2026-08-16 信号体系）：正在执行区下的挂起任务"""
        if not paused:
            self.paused_label.setText("")
            self.paused_label.setVisible(False)
            return
        parts = []
        for rec in paused:
            if not isinstance(rec, dict):
                continue
            name = rec.get("name", "")
            if not name:
                continue
            if rec.get("active"):
                parts.append(f"⏳ {name}（继续执行中）")
            elif rec.get("ready"):
                parts.append(f"⏸ {name}（待唤醒：超时/信号已到）")
            else:
                sig = rec.get("signal") or "信号"
                secs = rec.get("seconds")
                tail = f" · {int(secs)}s" if secs else ""
                parts.append(f"⏸ {name}（等待 {sig}{tail}）")
        if not parts:
            self.paused_label.setText("")
            self.paused_label.setVisible(False)
            return
        self.paused_label.setText("   |   ".join(parts))
        self.paused_label.setVisible(True)

    def _set_upcoming(self, upcoming: list) -> None:
        self.upcoming_list.clear()
        for item in upcoming:
            if isinstance(item, dict):
                name = item.get("name", "")
                nrt = item.get("next_run", "")
                reason = item.get("reason", "")
                # 触发式任务统一在「已失效」区显示 ⚡触发（scheduler 归入）；
                # 未开始区仅展示普通等待任务，不再放触发按钮（避免普通任务误触发）
                if reason:
                    # 异常推迟/熔断标注（识别错误等导致的冷却重试）
                    sub = f"⏱ {nrt} · {reason}" if nrt else reason
                    self._add_card(
                        self.upcoming_list, title=f"⚠ {name}", sub=sub,
                        badge_text="异常推迟", badge_color="#e53935",
                    )
                else:
                    self._add_card(
                        self.upcoming_list, title=name,
                        sub=f"⏱ {nrt}" if nrt else "待调度",
                        badge_text="未开始" if nrt else "待调度", badge_color="#1e88e5",
                    )
            else:
                self._add_card(self.upcoming_list, title=str(item))

    # ── 兼容旧方法（MainWindow 现有调用） ─────────────────

    def add_task(self, task_id: str, name: str) -> None:
        self._add_card(self.pending_list, title=name, sub=task_id)

    def clear(self) -> None:
        self.pending_list.clear()
        self.trigger_list.clear()
        self.upcoming_list.clear()
        self.invalid_list.clear()
        self.paused_label.setText("")
        self.paused_label.setVisible(False)

    def on_task_started(self, task_id: str) -> None:
        """任务开始执行 → 上方显示当前任务"""
        self._set_current(task_id)

    def on_task_done(self) -> None:
        """任务完成 → 清空当前任务"""
        self._set_current("")

    def refresh_queue(self, queue: list) -> None:
        """重建待执行列表（§3.2）"""
        self._set_pending(queue)
