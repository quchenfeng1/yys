"""
任务队列展示面板（★ v2.2 新增 — 从 Scheduler + UI 中拆出的独立可视化模块）

位于中间面板，全局控制栏下方。展示当前执行任务 + 即将执行的任务队列。
从 Scheduler 获取日程表数据，通过事件总线实时刷新。

布局：
┌─────────────────────────────┐
│  🔵 当前任务                 │
│  ┌───────────────────────┐  │
│  │ 御魂副本               │  │  ← 大卡片，执行中高亮
│  │ P:10  第15/30轮        │  │
│  │ ■■■■■■■□□□ 50%       │  │
│  └───────────────────────┘  │
│                             │
│  📋 任务队列                 │
│  ┌─────┐ ┌─────┐ ┌─────┐   │
│  │觉醒 │ │结界 │ │悬赏 │   │  ← 小方块卡片，按优先级排列
│  │P:10 │ │P:10 │ │P:1  │   │
│  │14:00│ │15:30│ │次日 │   │
│  └─────┘ └─────┘ └─────┘   │
└─────────────────────────────┘
"""

from datetime import datetime
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QLinearGradient
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QScrollArea, QSizePolicy, QProgressBar,
)

from core.event_bus import event_bus, Events
from core.state_schema import StateKeys


# ==================== 颜色主题 ====================

class QueueTheme:
    """任务队列面板颜色主题。"""

    BG = "#FAFBFC"
    CARD_BG = "#FFFFFF"
    CARD_BORDER = "#E0E3E8"
    CARD_SHADOW = "#00000010"

    CURRENT_BG = "#E3F2FD"
    CURRENT_BORDER = "#2196F3"
    CURRENT_GLOW = "#2196F340"

    TEXT_PRIMARY = "#1A1A2E"
    TEXT_SECONDARY = "#6B7280"
    TEXT_MUTED = "#9CA3AF"

    PRIORITY_COLORS = {
        1: "#EF4444",   # 红 — 最高
        2: "#F97316",   # 橙
        3: "#EAB308",   # 黄
        5: "#22C55E",   # 绿
        10: "#3B82F6",  # 蓝
        20: "#8B5CF6",  # 紫
        99: "#9CA3AF",  # 灰 — 最低
    }

    STATUS_COLORS = {
        "running": "#2196F3",
        "waiting": "#9CA3AF",
        "due": "#22C55E",
        "done": "#8B5CF6",
        "skipped": "#F97316",
        "failed": "#EF4444",
    }

    @classmethod
    def priority_color(cls, priority: int) -> str:
        for threshold, color in sorted(cls.PRIORITY_COLORS.items()):
            if priority <= threshold:
                return color
        return cls.PRIORITY_COLORS[99]


# ==================== 卡片组件 ====================

class TaskCard(QFrame):
    """单个任务卡片。用于当前任务（大）或队列任务（小）。"""

    clicked = pyqtSignal(str)

    def __init__(self, task_name: str, display_name: str = "",
                 priority: int = 10, status: str = "waiting",
                 progress: str = "", next_time: str = "",
                 compact: bool = False, parent=None):
        super().__init__(parent)
        self.task_name = task_name
        self.compact = compact
        self._status = status

        self.setCursor(Qt.PointingHandCursor)
        self._init_ui(display_name, priority, status, progress, next_time)
        self._apply_style()

    def _init_ui(self, display_name, priority, status, progress, next_time):
        if self.compact:
            self._init_compact(display_name, priority, status, next_time)
        else:
            self._init_full(display_name, priority, status, progress, next_time)

    def _init_full(self, display_name, priority, status, progress, next_time):
        """大卡片：当前任务用。"""
        self.setFixedHeight(90)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # 顶行：名称 + 优先级徽章 + 状态
        top = QHBoxLayout()
        name = QLabel(display_name or self.task_name)
        name.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        name.setStyleSheet(f"color: {QueueTheme.TEXT_PRIMARY};")
        top.addWidget(name)
        top.addStretch()

        badge = QLabel(f"P{priority}")
        badge.setFont(QFont("Consolas", 9, QFont.Bold))
        badge.setStyleSheet(
            f"background: {QueueTheme.priority_color(priority)}; "
            f"color: white; border-radius: 8px; padding: 2px 8px;"
        )
        top.addWidget(badge)

        status_lbl = QLabel({"running": "▶ 执行中", "due": "⏳ 待执行"}.get(status, ""))
        status_lbl.setFont(QFont("Microsoft YaHei", 9))
        status_lbl.setStyleSheet(f"color: {QueueTheme.STATUS_COLORS.get(status, '#888')};")
        top.addWidget(status_lbl)
        layout.addLayout(top)

        # 进度条
        if progress:
            pb = QProgressBar()
            pb.setTextVisible(True)
            pb.setFormat(f"  {progress}  %p%")
            pb.setStyleSheet("""
                QProgressBar {
                    border: none; border-radius: 4px; background: #E5E7EB;
                    height: 16px; text-align: center; font-size: 10px;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #2196F3, stop:1 #64B5F6);
                    border-radius: 4px;
                }
            """)
            try:
                parts = progress.split("/")
                if len(parts) == 2:
                    pb.setRange(0, int(parts[1]))
                    pb.setValue(int(parts[0]))
            except ValueError:
                pb.setRange(0, 100)
                pb.setValue(50)
            layout.addWidget(pb)

    def _init_compact(self, display_name, priority, status, next_time):
        """小卡片：队列任务用。"""
        self.setFixedSize(120, 70)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        name = QLabel(display_name or self.task_name)
        name.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        name.setStyleSheet(f"color: {QueueTheme.TEXT_PRIMARY};")
        name.setAlignment(Qt.AlignCenter)
        name.setWordWrap(True)
        layout.addWidget(name)

        info = QLabel(f"P{priority} · {next_time}" if next_time else f"P{priority}")
        info.setFont(QFont("Consolas", 8))
        info.setStyleSheet(f"color: {QueueTheme.TEXT_SECONDARY};")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

    def _apply_style(self):
        color = QueueTheme.STATUS_COLORS.get(self._status, QueueTheme.CARD_BORDER)
        if self._status == "running":
            border = f"2px solid {QueueTheme.CURRENT_BORDER}"
            bg = QueueTheme.CURRENT_BG
        else:
            border = f"1px solid {QueueTheme.CARD_BORDER}"
            bg = QueueTheme.CARD_BG

        self.setStyleSheet(f"""
            TaskCard {{
                background: {bg};
                border: {border};
                border-radius: 10px;
            }}
        """)

    def mousePressEvent(self, event):
        self.clicked.emit(self.task_name)


# ==================== 主面板 ====================

class TaskQueuePanel(QWidget):
    """任务队列展示面板。

    位于中间面板控制栏下方。展示：
      - 当前正在执行的任务（大卡片 + 进度条）
      - 即将执行的任务队列（小方块卡片，水平流式排列）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scheduler = None  # 由外部注入
        self._current_task: Optional[str] = None
        self._queue: list[dict] = []
        self._init_ui()
        self._start_events()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 12)
        layout.setSpacing(8)

        # ===== 当前任务区域 =====
        self._current_section_label = QLabel("● 当前任务")
        self._current_section_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self._current_section_label.setStyleSheet(f"color: {QueueTheme.TEXT_PRIMARY}; padding: 4px 0;")
        layout.addWidget(self._current_section_label)

        self._current_card = QLabel("空闲 — 等待调度")
        self._current_card.setFont(QFont("Microsoft YaHei", 12))
        self._current_card.setAlignment(Qt.AlignCenter)
        self._current_card.setMinimumHeight(70)
        self._current_card.setStyleSheet(f"""
            QLabel {{
                background: {QueueTheme.CARD_BG};
                border: 2px dashed {QueueTheme.CARD_BORDER};
                border-radius: 10px;
                color: {QueueTheme.TEXT_MUTED};
            }}
        """)
        layout.addWidget(self._current_card)

        # ===== 任务队列区域 =====
        self._queue_section_label = QLabel("📋 任务队列 (0)")
        self._queue_section_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        self._queue_section_label.setStyleSheet(f"color: {QueueTheme.TEXT_PRIMARY}; padding: 4px 0;")
        layout.addWidget(self._queue_section_label)

        # 队列卡片容器（可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._queue_container = QWidget()
        self._queue_layout = QHBoxLayout(self._queue_container)
        self._queue_layout.setContentsMargins(4, 4, 4, 4)
        self._queue_layout.setSpacing(8)
        self._queue_layout.addStretch()
        scroll.setWidget(self._queue_container)
        layout.addWidget(scroll)

        layout.addStretch()

    # ==================== 事件订阅 ====================

    def _start_events(self):
        event_bus.subscribe(Events.SCHEDULE_UPDATED, self._on_schedule_updated)
        event_bus.subscribe(Events.TASK_STARTED, self._on_task_started)
        event_bus.subscribe(Events.TASK_DONE, self._on_task_done)
        event_bus.subscribe(Events.STEP_DONE, self._on_step_done)

    def set_scheduler(self, scheduler):
        """注入 Scheduler 引用（用于获取队列详情）。"""
        self._scheduler = scheduler

    # ==================== 事件处理 ====================

    def _on_schedule_updated(self, **kwargs):
        """Scheduler 日程表刷新 → 从事件数据重建队列。
        注意：此方法在 event_bus 后台线程调用，需通过 QTimer 回到主线程更新 UI。"""
        queue_data = kwargs.get("queue", [])
        QTimer.singleShot(0, lambda: self._apply_schedule(queue_data))

    def _apply_schedule(self, queue_data):
        """在主线程中应用日程表数据。"""
        if not queue_data:
            if self._scheduler:
                queue_data = self._scheduler.get_all_tasks()
                queue_data = [t for t in queue_data if t.get("status") == "due"]

        pending = []
        for t in queue_data:
            if t.get("name") != self._current_task:
                pending.append({
                    "name": t.get("task", t.get("name", "")),
                    "priority": t.get("priority", 10),
                    "next_run": t.get("next_run"),
                    "status": t.get("status", "waiting"),
                })
        pending.sort(key=lambda x: x["priority"])
        self._queue = pending
        self._rebuild_queue()

    def _on_task_started(self, task_name: str):
        QTimer.singleShot(0, lambda: self._apply_task_started(task_name))

    def _apply_task_started(self, task_name: str):
        """在主线程中更新当前任务卡片。"""
        self._current_task = task_name
        self._rebuild_current(task_name, "running", "")

    def _on_task_done(self, task_name: str, success: bool, **kw):
        QTimer.singleShot(0, lambda: self._apply_task_done(task_name, success))

    def _apply_task_done(self, task_name: str, success: bool):
        """在主线程中清除当前卡片并刷新队列。"""
        if task_name == self._current_task:
            self._current_task = None
            self._rebuild_current("", "stopped", "")
        if self._scheduler:
            self._on_schedule_updated()  # 触发队列刷新

    def _on_step_done(self, step_name: str, status: str, **kw):
        """步骤完成 → 更新进度（如有）。"""
        pass  # 进度由具体任务通过 state_manager 更新

    # ==================== UI 重建 ====================

    def _rebuild_current(self, task_name: str, status: str, progress: str):
        """重建当前任务卡片。"""
        # 移除旧卡片
        old = self._current_card
        if old:
            old.setParent(None)

        if task_name and status == "running":
            display = task_name
            if self._scheduler:
                for t in self._scheduler.get_all_tasks():
                    if t["name"] == task_name:
                        display = t.get("display_name", task_name)
                        break

            card = TaskCard(
                task_name=task_name,
                display_name=display,
                priority=self._get_priority(task_name),
                status="running",
                progress=progress,
                compact=False,
            )
            card.clicked.connect(lambda n: None)  # 点击可查看详情（预留）
            self.layout().replaceWidget(old, card) if old else self.layout().addWidget(card)
            self._current_card = card
        else:
            placeholder = QLabel("空闲 — 等待调度")
            placeholder.setFont(QFont("Microsoft YaHei", 12))
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setMinimumHeight(70)
            placeholder.setStyleSheet(f"""
                QLabel {{
                    background: {QueueTheme.CARD_BG};
                    border: 2px dashed {QueueTheme.CARD_BORDER};
                    border-radius: 10px;
                    color: {QueueTheme.TEXT_MUTED};
                }}
            """)
            idx = self.layout().indexOf(old) if old else 1
            self.layout().insertWidget(idx, placeholder)
            if old:
                old.deleteLater()
            self._current_card = placeholder

    def _rebuild_queue(self):
        """重建任务队列卡片（小方块）。"""
        # 清除旧卡片
        while self._queue_layout.count() > 1:  # 保留最后的 stretch
            item = self._queue_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        count = len(self._queue)
        self._queue_section_label.setText(f"📋 任务队列 ({count})")

        for i, task in enumerate(self._queue[:20]):  # 最多显示20个
            next_time_str = ""
            nr = task.get("next_run")
            if nr:
                if isinstance(nr, datetime):
                    next_time_str = nr.strftime("%H:%M")
                elif isinstance(nr, str):
                    try:
                        next_time_str = nr[11:16] if len(nr) > 16 else nr
                    except Exception:
                        next_time_str = str(nr)[:5]

            card = TaskCard(
                task_name=task["name"],
                display_name=task.get("display_name", task["name"]),
                priority=task.get("priority", 10),
                status=task.get("status", "waiting"),
                next_time=next_time_str,
                compact=True,
            )
            card.clicked.connect(lambda n, t=task["name"]: self._on_card_clicked(t))
            self._queue_layout.insertWidget(self._queue_layout.count() - 1, card)

    # ==================== 辅助 ====================

    def _get_priority(self, task_name: str) -> int:
        if self._scheduler:
            for t in self._scheduler.get_all_tasks():
                if t["name"] == task_name:
                    return t.get("priority", 10)
        return 10

    def _on_card_clicked(self, task_name: str):
        """点击队列卡片 → 可跳转到任务详情（预留）。"""
        pass

    def refresh(self):
        """手动刷新（外部调用）。"""
        self._on_schedule_updated()
