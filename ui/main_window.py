"""
阴阳师自动化脚本 - 主界面（v2.4 现代风格）

三栏布局：左菜单树 / 中(控制栏+任务队列+任务列表/面板) / 右(日志+终端)
"""
import os, time
from pathlib import Path
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QCheckBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QFrame, QScrollArea, QApplication, QMessageBox, QSizePolicy,
    QFormLayout,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette, QIcon
from core.config_manager import ConfigManager
from ui.script_worker import ScriptWorker
from ui.panels.menu_tree import MenuTree
from ui.panels.control_bar import ControlBar
from ui.panels.task_queue_panel import TaskQueuePanel
from ui.panels.log_panel import LogPanel
from ui.panels.status_bar import StatusBar
from ui.panels.image_manager_panel import ImageManagerPanel
from ui.panels.task_manager_panel import TaskManagerPanel
from core.image_manager import ImageManager
from core.task_manager import TaskManager
from ui.panels.config_panel import ConfigPanel

PROJECT_ROOT = Path(__file__).parent.parent

# ==================== 全局样式 ====================
APP_STYLE = """
    QMainWindow { background: #F5F6F8; }
    QSplitter::handle {
        background: #E8ECF0; width: 2px;
    }
    QScrollArea { border: none; background: transparent; }
    QScrollBar:vertical {
        background: transparent; width: 8px;
    }
    QScrollBar::handle:vertical {
        background: #C4C8CC; border-radius: 4px; min-height: 30px;
    }
    QScrollBar::handle:vertical:hover { background: #A0A4A8; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
  # d:\yys

# ==================== 主窗口 ====================

class MainWindow(QMainWindow):
    """主界面（v2.5 重构版）。"""

    append_log = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.worker: ScriptWorker = None
        self.config = ConfigManager()
        self._running = False
        self.image_mgr = ImageManager(PROJECT_ROOT)
        self.task_mgr = TaskManager(PROJECT_ROOT)
        self.config_panel = ConfigPanel(self.config)

        self._init_ui()
        self._connect_signals()
        self._refresh_task_list()

        # ★ UI 就绪后再初始化调度器（确保 TaskQueuePanel 已订阅事件）
        from core.scheduler import Scheduler
        from core.state_manager import state_manager
        self._scheduler = Scheduler(self.config, state_manager)
        self._scheduler.load_tasks_from_config()
        self._scheduler.load_state()
        # 直接注入调度器到队列面板，确保 UI 能实时显示
        self.task_queue.set_scheduler(self._scheduler)
        self.task_queue.refresh()
        self._scheduler.build_schedule()  # 发布 SCHEDULE_UPDATED → 任务队列面板

        self.append_log.connect(self._on_append_log)

    # ==================== UI 构建 ====================

    def _init_ui(self):
        self.setWindowTitle("阴阳师自动化脚本")
        self.setMinimumSize(1180, 700)
        self.resize(1320, 800)
        self.setStyleSheet(APP_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)
        self.menu_tree = MenuTree()
        splitter.addWidget(self.menu_tree)
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([195, 560, 520])
        outer.addWidget(splitter, stretch=1)
        self.status_bar = StatusBar()
        outer.addWidget(self.status_bar)

    def _build_center(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(6, 0, 4, 0)
        layout.setSpacing(4)

        # 控制栏始终在顶部
        self.control_bar = ControlBar()
        layout.addWidget(self.control_bar)

        # 可切换的内容区（ScrollArea，隐藏内容不占空间）
        self._center_content = QScrollArea()
        self._center_content.setWidgetResizable(True)
        self._center_content.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        # ── 全局控制视图：仅任务队列 ──
        self._dashboard_stack = QWidget()
        self._dashboard_stack.setLayout(QVBoxLayout())
        self._dashboard_stack.layout().setContentsMargins(0,0,0,0)
        self._dashboard_stack.layout().setSpacing(4)
        self.task_queue = TaskQueuePanel()
        self._dashboard_stack.layout().addWidget(self.task_queue)
        self._dashboard_stack.layout().addStretch()

        # ── 游戏任务视图：任务队列 + 任务列表（暂不在菜单中使用）──
        self._game_stack = QWidget()
        self._game_stack.setLayout(QVBoxLayout())
        self._game_stack.layout().setContentsMargins(0,0,0,0)
        self._game_stack.layout().setSpacing(4)
        self._game_stack.layout().addWidget(QLabel("游戏任务视图"))
        self._game_stack.layout().addStretch()
        # task_tree 独立保存以供将来引用
        self.task_tree = QTreeWidget()
        self.task_tree.setHeaderLabels(["任务名称", "状态", "下次执行"])
        self.task_tree.setRootIsDecorated(True)
        self.task_tree.setStyleSheet("""
            QTreeWidget { background: #FFFFFF; border: 1px solid #E8ECF0; border-radius: 8px; }
            QTreeWidget::item { padding: 5px 4px; }
            QTreeWidget::item:hover { background: #F0F4FF; }
            QHeaderView::section { background: #F8F9FA; padding: 6px; border: none; font-weight: bold; color: #5F6368; }
        """)
        h = self.task_tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)

        # 初始显示全局控制视图
        self._center_content.setWidget(self._dashboard_stack)
        layout.addWidget(self._center_content, stretch=1)

        # 特殊面板（预先创建，按需替换 _center_content 的 widget）
        self.config_panel.hide()
        self.image_panel = ImageManagerPanel(self.image_mgr); self.image_panel.hide()
        self.task_mgr_panel = TaskManagerPanel(self.task_mgr); self.task_mgr_panel.hide()

        # ── 游戏任务面板：任务列表(上) + 任务配置(下) ──
        self._game_panel = QWidget()
        gply = QVBoxLayout(self._game_panel)
        gply.setContentsMargins(0,4,0,0); gply.setSpacing(6)
        self._game_title = QLabel("游戏任务")
        self._game_title.setFont(QFont("Microsoft YaHei",13,QFont.Bold))
        self._game_title.setStyleSheet("color:#1A1A2E;padding:0 4px;")
        gply.addWidget(self._game_title)

        # 列表外框 + 滚动区（替代 QListWidget）
        self._game_box = QFrame()
        self._game_box.setObjectName("list_box")
        self._game_box.setStyleSheet("QFrame#list_box{background:#FFFFFF;border:1px solid #E8ECF0;border-radius:8px;}")
        self._game_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._game_box.setMinimumHeight(80)
        gb_ly = QVBoxLayout(self._game_box); gb_ly.setContentsMargins(0,0,0,0); gb_ly.setSpacing(0)
        self._game_scroll = QScrollArea()
        self._game_scroll.setWidgetResizable(True)
        self._game_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self._game_rows = QWidget()
        self._game_rows_layout = QVBoxLayout(self._game_rows)
        self._game_rows_layout.setContentsMargins(0,0,0,0); self._game_rows_layout.setSpacing(0)
        self._game_rows_layout.addStretch()
        self._game_scroll.setWidget(self._game_rows)
        gb_ly.addWidget(self._game_scroll)
        gply.addWidget(self._game_box, stretch=1)

        self._game_cfg = QWidget()
        cly = QVBoxLayout(self._game_cfg); cly.setContentsMargins(0,0,0,0); cly.setSpacing(6)

        # ── 配置表单标题 ──
        cfg_header = QHBoxLayout()
        self._game_cfg_title = QLabel("任务配置")
        self._game_cfg_title.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self._game_cfg_title.setStyleSheet("color:#1A1A2E;")
        cfg_header.addWidget(self._game_cfg_title)
        cfg_header.addStretch()
        self._game_cfg_save = QPushButton("💾 保存配置")
        self._game_cfg_save.setStyleSheet(
            "QPushButton{background:#1A73E8;color:white;font-weight:bold;border:none;border-radius:6px;padding:6px 16px;}"
            "QPushButton:hover{background:#1557B0;}")
        self._game_cfg_save.clicked.connect(self._on_save_task_config)
        self._game_cfg_save.hide()
        cfg_header.addWidget(self._game_cfg_save)
        cly.addLayout(cfg_header)

        # ── 滚动区域包含表单 ──
        cfg_scroll = QScrollArea()
        cfg_scroll.setWidgetResizable(True)
        cfg_scroll.setStyleSheet("QScrollArea{border:1px solid #E8ECF0;border-radius:8px;background:#FAFBFC;}")
        self._cfg_form = QWidget()
        self._cfg_form.setStyleSheet("background:#FAFBFC;")
        form = QFormLayout(self._cfg_form)
        form.setContentsMargins(12, 10, 12, 10); form.setSpacing(8)

        # ── 基本 ──
        self._cfg_enabled = QCheckBox(); form.addRow("启用任务:", self._cfg_enabled)
        self._cfg_priority = QSpinBox(); self._cfg_priority.setRange(1, 99); form.addRow("优先级:", self._cfg_priority)

        # ── 重复规则 ──
        self._cfg_repeat_type = QComboBox()
        self._cfg_repeat_type.addItems([
            "daily(每日)", "weekly(每周)", "monthly_start(每月初)",
            "interval_days(隔N天)", "interval_hours(隔N小时)",
            "once(单次)", "expire_at(失效时间)", "special(活动限定)",
        ])
        self._cfg_repeat_type.currentIndexChanged.connect(self._on_repeat_type_changed)
        form.addRow("重复规则:", self._cfg_repeat_type)

        # 每日/每周：时间范围
        self._cfg_time_start = QLineEdit(); self._cfg_time_start.setPlaceholderText("如 08:00")
        form.addRow("开始时间:", self._cfg_time_start)  # daily
        self._cfg_time_end = QLineEdit(); self._cfg_time_end.setPlaceholderText("如 22:00")
        form.addRow("结束时间:", self._cfg_time_end)    # daily

        # 每周：星期多选
        self._cfg_weekdays = QWidget()
        wd_ly = QHBoxLayout(self._cfg_weekdays); wd_ly.setContentsMargins(0,0,0,0); wd_ly.setSpacing(2)
        self._cfg_wd_checks = {}
        for i, name in enumerate(["一","二","三","四","五","六","日"]):
            cb = QCheckBox(name); self._cfg_wd_checks[i+1] = cb; wd_ly.addWidget(cb)
        wd_ly.addStretch()
        form.addRow("每周:", self._cfg_weekdays)

        # 间隔天数
        self._cfg_days = QSpinBox(); self._cfg_days.setRange(1, 365); form.addRow("间隔天数:", self._cfg_days)
        # 间隔小时
        self._cfg_hours = QDoubleSpinBox(); self._cfg_hours.setRange(0.5, 168); self._cfg_hours.setSingleStep(0.5)
        form.addRow("间隔小时:", self._cfg_hours)
        # 单次
        self._cfg_once_at = QLineEdit(); self._cfg_once_at.setPlaceholderText("2026-08-01 10:00"); form.addRow("执行时间:", self._cfg_once_at)

        # 活动限定：日期范围
        self._cfg_date_start = QLineEdit(); self._cfg_date_start.setPlaceholderText("YYYY-MM-DD")
        form.addRow("活动开始:", self._cfg_date_start)
        self._cfg_date_end = QLineEdit(); self._cfg_date_end.setPlaceholderText("YYYY-MM-DD")
        form.addRow("活动结束:", self._cfg_date_end)

        # ── 执行规则 ──
        self._cfg_exec_mode = QComboBox()
        self._cfg_exec_mode.addItems(["按次数", "按时间(分钟)"])
        form.addRow("执行方式:", self._cfg_exec_mode)
        self._cfg_exec_value = QSpinBox(); self._cfg_exec_value.setRange(1, 99999)
        form.addRow("执行值:", self._cfg_exec_value)

        self._cfg_max_daily = QSpinBox(); self._cfg_max_daily.setRange(1, 9999); self._cfg_max_daily.setSpecialValueText("不限")
        form.addRow("每日上限:", self._cfg_max_daily)

        # ── 下次执行 ──
        self._cfg_next_run = QLineEdit(); self._cfg_next_run.setPlaceholderText("保存时自动填入当前时间")
        form.addRow("下次执行:", self._cfg_next_run)

        self._cfg_team = QComboBox(); self._cfg_team.addItem("（无）")
        form.addRow("阵容预设:", self._cfg_team)

        cfg_scroll.setWidget(self._cfg_form)
        cly.addWidget(cfg_scroll)

        # 初始占位文本
        self._game_cfg_placeholder = QLabel("↑ 点击上方任务查看配置")
        self._game_cfg_placeholder.setAlignment(Qt.AlignCenter)
        self._game_cfg_placeholder.setStyleSheet("color:#9CA3AF;font-size:13px;padding:20px;")
        cly.addWidget(self._game_cfg_placeholder)

        self._game_cfg.hide()
        gply.addWidget(self._game_cfg, stretch=1)
        self._game_panel.hide()
        return w

    def _switch_center(self, widget: QWidget):
        """切换中间内容区为指定 widget。"""
        self._center_content.takeWidget()
        self._center_content.setWidget(widget)
        widget.show()

    def _switch_center_dashboard(self):
        """切换到全局控制视图（仅任务队列）。"""
        self._center_content.takeWidget()
        self._center_content.setWidget(self._dashboard_stack)
        self._dashboard_stack.show()

    def _build_right(self) -> QWidget:
        self.log_panel = LogPanel()
        self.log_panel.start()
        return self.log_panel

    # ==================== 信号 ====================

    def _connect_signals(self):
        self.control_bar.start_clicked.connect(self._on_start)
        self.control_bar.stop_clicked.connect(self._on_stop)
        self.control_bar.pause_clicked.connect(self._on_pause)
        self.menu_tree.on_item_clicked(self._on_menu_clicked)

    # ==================== 菜单路由（v2.5） ====================

    def _on_menu_clicked(self, item, data):
        kind, key = data

        if kind == "dashboard":
            self._switch_center_dashboard()
        elif kind == "config":
            self._show_config(key)
        elif kind == "image":
            self._show_image(key)
        elif kind == "taskmgr":
            self._show_taskmgr(key)
        elif kind == "game":
            self._show_game(key)
        elif kind == "monitor":
            self._show_placeholder(f"「运行监控 - {key}」功能尚未实现")
        elif kind == "sub_account":
            self._show_placeholder(f"「小号设置 - {key}」功能尚未实现")

    def _show_config(self, key: str):
        self._switch_center(self.config_panel)
        self.config_panel.show_config(key.replace("config:", ""))

    def _show_image(self, key: str):
        self._switch_center(self.image_panel)
        self.image_panel.show_section(key.replace("image:", ""))

    def _show_taskmgr(self, key: str):
        self._switch_center(self.task_mgr_panel)
        self.task_mgr_panel.show_section(key.replace("taskmgr:", ""))

    def _show_game(self, key: str):
        """游戏任务：任务列表(上) + 点击查看配置(下)。"""
        self._switch_center(self._game_panel)
        cat = key.replace("game:", "")
        labels = {"daily":"📅 日常任务","permanent":"⚔ 常驻任务","event":"🎪 活动任务","special":"⭐ 特殊任务"}
        self._game_title.setText(labels.get(cat, "游戏任务"))
        self._game_cfg.hide()
        self._game_cfg_placeholder.setText("↑ 点击上方任务查看配置")
        self._clear_game_rows()
        tasks = self.task_mgr.get_tasks_by_category(cat)
        if not tasks:
            lb = QLabel("（暂无任务）"); lb.setAlignment(Qt.AlignCenter)
            lb.setStyleSheet("color:#BDC1C6;font-size:13px;padding:24px;")
            self._game_rows_layout.insertWidget(self._game_rows_layout.count()-1, lb)
            return
        for t in tasks:
            row = QFrame()
            row.setObjectName("task_row")
            row.setStyleSheet("QFrame#task_row{background:#FFFFFF;border:none;border-bottom:1px solid #F0F0F0;}QFrame#task_row:hover{background:#F5F8FF;}")
            row.setCursor(Qt.PointingHandCursor)
            rly = QHBoxLayout(row); rly.setContentsMargins(10,8,10,8); rly.setSpacing(8)
            ic = TaskManager.CATEGORY_ICONS.get(t.category, "📄")
            tic = TaskManager.TASK_TYPE_ICONS.get(getattr(t, 'task_type', ''), '')
            nm = QLabel(f"{ic} {tic} {t.display_name}")
            nm.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
            nm.setStyleSheet("color:#1A1A2E;background:transparent;")
            rly.addWidget(nm, stretch=1)
            if t.description:
                d = QLabel(t.description[:40])
                d.setStyleSheet("color:#80868B;font-size:11px;background:transparent;")
                rly.addWidget(d)
            row.setMinimumHeight(46)
            # 点击处理：lambda 捕获当前 t
            row.mousePressEvent = lambda ev, task=t: self._on_game_task_clicked(task)
            self._game_rows_layout.insertWidget(self._game_rows_layout.count()-1, row)
        self._task_filter = cat
        self._refresh_task_list()

    def _clear_game_rows(self):
        lay = self._game_rows_layout
        while lay.count() > 1:
            w = lay.takeAt(0).widget()
            if w: w.deleteLater()

    def _on_game_task_clicked(self, t):
        """点击游戏任务行 → 加载并显示配置表单。"""
        if not t:
            self._game_cfg.hide(); return

        self._current_game_task = t
        tt = getattr(t, 'task_type', 'event_task')
        self._game_cfg_title.setText(f"📋 「{t.display_name}」— {'战斗任务' if tt == 'battle' else '事件任务'}")

        # 从 tasks.yaml 加载现有配置
        cfg = self.config.get_task_config(t.name)
        repeat = cfg.get("repeat", {})

        self._cfg_enabled.setChecked(cfg.get("enabled", False))
        self._cfg_priority.setValue(cfg.get("priority", 10))
        rtype = repeat.get("type", "daily")
        type_map = {"daily":0,"weekly":1,"monthly_start":2,"interval_days":3,"interval_hours":4,"once":5,"expire_at":6,"special":7}
        self._cfg_repeat_type.setCurrentIndex(type_map.get(rtype, 0))
        self._cfg_time_start.setText(repeat.get("time_start", ""))
        self._cfg_time_end.setText(repeat.get("time_end", ""))
        wds = repeat.get("weekdays") or []
        for d, cb in self._cfg_wd_checks.items():
            cb.setChecked(d in wds)
        self._cfg_days.setValue(repeat.get("days", 1))
        self._cfg_hours.setValue(repeat.get("hours", 1.0))
        self._cfg_once_at.setText(repeat.get("at", ""))
        w = repeat.get("window") or {}
        self._cfg_date_start.setText(w.get("date_start", ""))
        self._cfg_date_end.setText(w.get("date_end", ""))
        self._cfg_max_daily.setValue(repeat.get("max_daily", 0) or 0)
        # 执行规则
        er = cfg.get("execution_rule", {})
        is_time = er.get("mode") == "time"
        self._cfg_exec_mode.setCurrentIndex(1 if is_time else 0)
        self._cfg_exec_value.setValue(er.get("value", 1))
        # 下次执行
        nr = cfg.get("next_run_time", "")
        if not nr:
            nr = self._load_next_run_from_state(t.name)
        self._cfg_next_run.setText(nr)

        self._cfg_team.setVisible(tt == "battle")
        self._on_repeat_type_changed(self._cfg_repeat_type.currentIndex())
        self._game_cfg_save.show()
        self._game_cfg_placeholder.hide()
        self._game_cfg.show()

    def _load_next_run_from_state(self, task_name: str) -> str:
        """从 task_state.json 读取下次执行时间。"""
        try:
            from core.task_state import TaskStateStore
            store = TaskStateStore()
            store.load()
            st = store.get(task_name)
            if st and st.next_run_time:
                return str(st.next_run_time)[:16]
        except Exception:
            pass
        return ""

    def _on_calc_next_run(self):
        """根据 repeat 规则计算下次执行时间。"""
        try:
            from core.repeat_rule import RepeatRule
            from datetime import datetime
            types = ["daily","interval_hours","interval_days","weekly","monthly","once","expire_at"]
            rtype = types[self._cfg_repeat_type.currentIndex()]
            repeat = RepeatRule(
                type=rtype,
                at_time=self._cfg_at_time.text() or "00:00",
                times=self._cfg_times.value(),
                days=self._cfg_days.value() if rtype == "interval_days" else None,
                hours=self._cfg_hours.value() if rtype == "interval_hours" else None,
            )
            nr = repeat.get_initial_next_run()
            self._cfg_next_run.setText(nr.strftime("%Y-%m-%d %H:%M"))
        except Exception as e:
            QMessageBox.warning(self, "计算失败", f"无法计算下次执行时间:\n{e}")

    def _on_edit_next_run(self):
        """允许手动编辑下次执行时间。"""
        self._cfg_next_run.setReadOnly(False)
        self._cfg_next_run.setStyleSheet("background:#FFFFFF;")
        self._cfg_next_run.setFocus()

    def _on_repeat_type_changed(self, idx):
        """根据选中的重复规则显示/隐藏相关字段。"""
        types = ["daily","weekly","monthly_start","interval_days","interval_hours","once","expire_at","special"]
        rtype = types[idx] if idx < len(types) else "daily"
        # 隐藏所有条件字段
        for w, lbl in [
            (self._cfg_time_start, "开始时间:"), (self._cfg_time_end, "结束时间:"),
            (self._cfg_weekdays, "每周:"), (self._cfg_days, "间隔天数:"),
            (self._cfg_hours, "间隔小时:"), (self._cfg_once_at, "执行时间:"),
            (self._cfg_date_start, "活动开始:"), (self._cfg_date_end, "活动结束:"),
        ]:
            w.setVisible(False)
            self._hide_form_row(w)
        # 按类型显示
        if rtype == "daily":
            self._cfg_time_start.setVisible(True)
            self._cfg_time_end.setVisible(True)
        elif rtype == "weekly":
            self._cfg_weekdays.setVisible(True)
            self._cfg_time_start.setVisible(True)
            self._cfg_time_end.setVisible(True)
        elif rtype == "interval_days":
            self._cfg_days.setVisible(True)
        elif rtype == "interval_hours":
            self._cfg_hours.setVisible(True)
        elif rtype == "once":
            self._cfg_once_at.setVisible(True)
        elif rtype == "special":
            self._cfg_date_start.setVisible(True)
            self._cfg_date_end.setVisible(True)
        # 显示对应 label
        for w, _ in [(self._cfg_time_start, ""), (self._cfg_time_end, ""),
                      (self._cfg_weekdays, ""), (self._cfg_days, ""),
                      (self._cfg_hours, ""), (self._cfg_once_at, ""),
                      (self._cfg_date_start, ""), (self._cfg_date_end, "")]:
            if w.isVisible():
                self._show_form_row(w)

    def _hide_form_row(self, widget):
        """隐藏 form 中指定 widget 及其 label。"""
        layout = self._cfg_form.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget() is widget and i > 0:
                label_item = layout.itemAt(i - 1)
                if label_item and label_item.widget():
                    label_item.widget().setVisible(False)

    def _show_form_row(self, widget):
        """显示 form 中指定 widget 及其 label。"""
        layout = self._cfg_form.layout()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget() is widget and i > 0:
                label_item = layout.itemAt(i - 1)
                if label_item and label_item.widget():
                    label_item.widget().setVisible(True)

    def _on_save_task_config(self):
        """保存当前任务配置到 tasks.yaml。"""
        t = getattr(self, '_current_game_task', None)
        if not t: return

        types = ["daily","weekly","monthly_start","interval_days","interval_hours","once","expire_at","special"]
        rtype = types[self._cfg_repeat_type.currentIndex()]
        repeat = {"type": rtype}
        if rtype in ("daily", "weekly"):
            repeat["time_start"] = self._cfg_time_start.text().strip() or "00:00"
            repeat["time_end"] = self._cfg_time_end.text().strip() or "23:59"
        if rtype == "weekly":
            wds = [d for d, cb in self._cfg_wd_checks.items() if cb.isChecked()]
            repeat["weekdays"] = wds
        if rtype == "interval_days":
            repeat["days"] = self._cfg_days.value()
        if rtype == "interval_hours":
            repeat["hours"] = self._cfg_hours.value()
        if rtype == "once":
            at = self._cfg_once_at.text().strip()
            if at: repeat["at"] = at
        if rtype == "special":
            ds = self._cfg_date_start.text().strip()
            de = self._cfg_date_end.text().strip()
            if ds or de:
                repeat["window"] = {}
                if ds: repeat["window"]["date_start"] = ds
                if de: repeat["window"]["date_end"] = de

        md = self._cfg_max_daily.value()
        if md > 0:
            repeat["max_daily"] = md

        # 执行规则
        exec_rule = {
            "mode": "time" if self._cfg_exec_mode.currentIndex() == 1 else "count",
            "value": self._cfg_exec_value.value(),
        }

        # 更新 tasks.yaml
        tasks_cfg = self.config.get_tasks_config()
        cat = t.category
        if cat not in tasks_cfg:
            tasks_cfg[cat] = []
        found = False
        for item in tasks_cfg[cat]:
            if item.get("name") == t.name:
                item["enabled"] = self._cfg_enabled.isChecked()
                item["priority"] = self._cfg_priority.value()
                item["repeat"] = repeat
                item["execution_rule"] = exec_rule
                found = True
                break
        if not found:
            tasks_cfg[cat].append({
                "name": t.name,
                "enabled": self._cfg_enabled.isChecked(),
                "priority": self._cfg_priority.value(),
                "repeat": repeat,
                "execution_rule": exec_rule,
            })

        import yaml
        tasks_path = Path(__file__).parent.parent / "config" / "tasks.yaml"
        tasks_path.write_text(yaml.dump(tasks_cfg, allow_unicode=True, default_flow_style=False), encoding="utf-8")
        self.config.load()  # 重新加载

        # 持久化 next_run_time 到 task_state.json（未填则自动填入当前时间）
        nr_text = self._cfg_next_run.text().strip()
        try:
            from datetime import datetime
            from core.task_state import TaskStateStore
            if nr_text:
                nr_dt = datetime.strptime(nr_text, "%Y-%m-%d %H:%M")
            else:
                nr_dt = datetime.now().replace(second=0, microsecond=0)
                self._cfg_next_run.setText(nr_dt.strftime("%Y-%m-%d %H:%M"))
            store = TaskStateStore()
            store.load()
            store.set_next_run(t.name, nr_dt)
            store.save()
        except ValueError:
            pass

        QMessageBox.information(self, "保存成功", f"「{t.display_name}」配置已保存")

    def _show_placeholder(self, text: str):
        w = QWidget()
        l = QVBoxLayout(w)
        lb = QLabel(text)
        lb.setAlignment(Qt.AlignCenter)
        lb.setStyleSheet("color:#9CA3AF;font-size:16px;padding:40px;")
        l.addWidget(lb)
        self._switch_center(w)

    # ==================== 启动/停止/暂停 ====================

    def _on_start(self):
        self._running = True
        self.status_bar.set_run_status("running")
        self.log_panel.terminal.append_message("INFO", "脚本启动中...")

        emu_type = self.config.get("emulator.type", "mumu")
        port = self.config.get("adb.port", 16384)
        path = self.config.get("emulator.path", "")
        auto_launch = self.config.get("emulator.auto_launch", True)

        self.worker = ScriptWorker(
            emulator_type=emu_type, adb_port=port,
            emulator_path=path, auto_launch=auto_launch,
            scheduler=self._scheduler, parent=self)
        self.worker.log_signal.connect(lambda m: self.append_log.emit(m, "INFO"))
        self.worker.status_signal.connect(self._on_status_change)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _on_stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        self._running = False
        self.control_bar.set_idle()
        self.status_bar.set_run_status("stopped")
        self.log_panel.terminal.append_message("WARNING", "脚本已强制停止")

    def _on_pause(self):
        self.status_bar.set_run_status("paused")

    def _on_status_change(self, status: str):
        pass  # 状态由 worker 管理

    def _on_progress(self, msg: str):
        self.statusBar().showMessage(msg)

    def _on_finished(self, success: bool, message: str):
        self._running = False
        self.control_bar.set_idle()
        self.status_bar.set_run_status("stopped")
        level = "INFO" if success else "ERROR"
        self.log_panel.terminal.append_message(level, message)

    # ==================== 任务列表 ====================

    def _refresh_task_list(self):
        self.task_tree.clear()
        flt = getattr(self, '_task_filter', 'all')
        categories = [
            ("日常任务", "daily", "#1A73E8"),
            ("常驻任务", "permanent", "#34A853"),
            ("活动任务", "event", "#F9AB00"),
            ("特殊任务", "special", "#9334E6"),
        ]
        for cat_name, cat_key, color in categories:
            if flt != "all" and flt != cat_key:
                continue
            task_dir = PROJECT_ROOT / "tasks" / cat_key
            tasks_found = []
            if task_dir.exists():
                for f in sorted(task_dir.glob("*.py")):
                    if not f.name.startswith("_"):
                        tasks_found.append(f.stem)
            root = QTreeWidgetItem(self.task_tree, [cat_name, "", ""])
            root.setFont(0, QFont("Microsoft YaHei", 10, QFont.Bold))
            root.setForeground(0, QColor(color))
            for tname in tasks_found:
                child = QTreeWidgetItem(root, [tname, "待执行", "—"])
                child.setCheckState(0, Qt.Checked)
            if not tasks_found:
                empty = QTreeWidgetItem(root, ["（暂无任务）", "", ""])
                empty.setForeground(0, QColor("#BDC1C6"))
        self.task_tree.expandAll()

    # ==================== 日志 ====================

    def _on_append_log(self, msg: str, level: str):
        color = {"INFO": "#202124", "WARN": "#F9AB00", "ERROR": "#EA4335"}.get(level, "#80868B")
        self.log_panel.log_stream._text.appendHtml(
            f'<span style="color:{color};font-family:Consolas;font-size:9pt;">{msg}</span>')

    # ==================== 关闭 ====================

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(self, "确认退出",
                "脚本正在运行中，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
            self.worker.stop()
            self.worker.wait(2000)
        self.log_panel.shutdown()
        self.config.save_global()
        event.accept()
