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
from core.event_bus import event_bus, Events
from core.state_schema import StateKeys
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
from ui.panels.sub_account_panel import SubAccountConfigPanel
from ui.panels.ui_settings_panel import UISettingsPanel
from ui.panels.execution_history import ExecutionHistoryPanel
from ui.panels.metrics_panel import MetricsPanel
from ui.panels.snapshot_viewer import SnapshotViewer
from ui.panels.report_viewer import ReportViewer

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

# ==================== 可点击游戏任务行 ====================

class _GameTaskRow(QFrame):
    """游戏任务列表中的可点击行。子控件透明传鼠，点击整行触发。"""

    def __init__(self, task_module, callback, parent=None):
        super().__init__(parent)
        self._task = task_module
        self._callback = callback
        self.setObjectName("task_row")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#task_row{background:#FFFFFF;border:none;border-bottom:1px solid #F0F0F0;}"
            "QFrame#task_row:hover{background:#F5F8FF;}")
        self.setMinimumHeight(46)

        rly = QHBoxLayout(self)
        rly.setContentsMargins(10, 8, 10, 8)
        rly.setSpacing(8)

        ic = TaskManager.CATEGORY_ICONS.get(task_module.category, "📄")
        tic = TaskManager.TASK_TYPE_ICONS.get(getattr(task_module, 'task_type', ''), '')
        nm = QLabel(f"{ic} {tic} {task_module.display_name}")
        nm.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        nm.setStyleSheet("color:#1A1A2E;background:transparent;")
        nm.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # ★ 鼠标穿透
        rly.addWidget(nm, stretch=1)

        if task_module.description:
            d = QLabel(task_module.description[:40])
            d.setStyleSheet("color:#80868B;font-size:11px;background:transparent;")
            d.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # ★ 鼠标穿透
            rly.addWidget(d)

    def mousePressEvent(self, ev):
        self._callback(self._task)
        super().mousePressEvent(ev)


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
        self.task_mgr.scan_all()  # ★ 必须扫描 tasks/ 目录才能获取任务列表
        self.config_panel = ConfigPanel(self.config)

        # ★ 初始化监控中心（12-日志监控中心）
        from core.monitor import Monitor, monitor as global_monitor
        self._monitor = Monitor(self.config)
        # 注入全局单例
        import core.monitor as mon_mod
        mon_mod.monitor = self._monitor

        self._init_ui()
        self._connect_signals()
        self._subscribe_events()  # ★ 订阅 07-运行时状态管理 的状态变化
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

        # ★ 初始化账号管理（15-账号管理模块）— 必须在 _scheduler 之后
        from core.account_manager import AccountManager
        self._account_mgr = AccountManager(
            self.config, None, state_manager, event_bus, self._scheduler)
        self._account_mgr.load_accounts()
        import core.account_manager as acct_mod
        acct_mod.account_manager = self._account_mgr

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
        self.sub_account_panel = SubAccountConfigPanel(); self.sub_account_panel.hide()
        self.ui_settings_panel = UISettingsPanel(self.config); self.ui_settings_panel.hide()
        self.ui_settings_panel.settings_changed.connect(self._on_ui_setting_changed)
        self.execution_history = ExecutionHistoryPanel(self._monitor, self.task_mgr); self.execution_history.hide()
        self.metrics_panel = MetricsPanel(self._monitor); self.metrics_panel.hide()
        self.snapshot_viewer = SnapshotViewer(); self.snapshot_viewer.hide()
        self.report_viewer = ReportViewer(self._monitor); self.report_viewer.hide()

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

        # expire_at 类型：失效时间
        self._cfg_expire_at = QLineEdit(); self._cfg_expire_at.setPlaceholderText("2026-12-31 23:59")
        form.addRow("失效时间:", self._cfg_expire_at)

        # ── 活动有效期（所有类型通用）──
        self._cfg_active_start = QLineEdit(); self._cfg_active_start.setPlaceholderText("YYYY-MM-DD")
        form.addRow("有效期开始:", self._cfg_active_start)
        self._cfg_active_end = QLineEdit(); self._cfg_active_end.setPlaceholderText("YYYY-MM-DD")
        form.addRow("有效期结束:", self._cfg_active_end)

        # 导入活动日历按钮
        self._cfg_import_cal = QPushButton("📅 导入活动日历")
        self._cfg_import_cal.setStyleSheet(
            "QPushButton{background:transparent;color:#1A73E8;border:1px solid #1A73E8;border-radius:4px;padding:4px 12px;}"
            "QPushButton:hover{background:#E3F2FD;}")
        self._cfg_import_cal.clicked.connect(self._on_import_calendar)
        form.addRow("", self._cfg_import_cal)

        # ── 执行规则 ──
        self._cfg_exec_mode = QComboBox()
        self._cfg_exec_mode.addItems(["按次数", "按时间(分钟)"])
        form.addRow("执行方式:", self._cfg_exec_mode)
        self._cfg_exec_value = QSpinBox(); self._cfg_exec_value.setRange(1, 99999)
        form.addRow("执行值:", self._cfg_exec_value)

        self._cfg_max_daily = QSpinBox(); self._cfg_max_daily.setRange(0, 9999); self._cfg_max_daily.setSpecialValueText("不限")
        form.addRow("每日上限:", self._cfg_max_daily)
        self._cfg_max_total = QSpinBox(); self._cfg_max_total.setRange(0, 99999); self._cfg_max_total.setSpecialValueText("不限")
        form.addRow("总次数上限:", self._cfg_max_total)

        # ── 运行状态（只读）──
        self._cfg_status_label = QLabel("")
        self._cfg_status_label.setStyleSheet("color:#5F6368;font-size:11px;padding:4px 0;")
        form.addRow("运行状态:", self._cfg_status_label)

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
        try:
            self._center_content.takeWidget()
            self._center_content.setWidget(widget)
            widget.show()
        except Exception:
            pass  # 面板切换失败不崩溃

    def _switch_center_safe(self, widget: QWidget):
        """安全切换：widget 为 None 时显示占位符。"""
        if widget is None or not isinstance(widget, QWidget):
            self._show_placeholder("此面板暂不可用")
            return
        self._switch_center(widget)

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
        self.control_bar.resume_clicked.connect(self._on_resume)
        self.control_bar.dry_run_toggled.connect(self._on_dry_run_toggled)
        self.control_bar.self_check_clicked.connect(self._on_self_check)
        self.menu_tree.on_item_clicked(self._on_menu_clicked)

    # ==================== 事件总线订阅（07-运行时状态管理） ====================

    def _subscribe_events(self):
        """订阅 StateManager 的 STATE_CHANGED 事件，驱动 StatusBar 实时刷新。"""
        def _dispatch(**data):
            try:
                QTimer.singleShot(0, lambda d=data: self._on_state_changed_safe(d))
            except Exception:
                pass  # 窗口已销毁时忽略
        event_bus.subscribe(Events.STATE_CHANGED, _dispatch)

    def _on_state_changed_safe(self, data: dict):
        """安全的 STATE_CHANGED 处理：窗口已销毁时跳过。"""
        try:
            if not hasattr(self, 'status_bar') or self.status_bar is None:
                return
            self._on_state_changed(data)
        except Exception:
            pass  # 状态刷新失败不崩溃

    def _on_state_changed(self, data: dict):
        """响应 STATE_CHANGED 事件，更新 StatusBar 各指标。

        支持两种数据格式：
          - 单键变更：{'key': str, 'old_value': Any, 'new_value': Any}
          - 批量变更：{'changes': {key: (old_value, new_value), ...}}
        """
        sb = self.status_bar
        if 'key' in data:
            key, new_val = data['key'], data['new_value']
            self._apply_state(sb, key, new_val)
        elif 'changes' in data:
            for key, (_, new_val) in data['changes'].items():
                self._apply_state(sb, key, new_val)

    def _apply_state(self, sb, key: str, value):
        """将单个状态键映射到 StatusBar 更新方法。"""
        if key == StateKeys.RUN_STATUS:
            sb.set_run_status(value)
        elif key == StateKeys.CONNECTION_STATUS:
            sb.set_connection(value)
        elif key == StateKeys.CURRENT_TASK:
            sb.set_current_task(value)
        elif key == StateKeys.CURRENT_STEP:
            # current_step 与 current_task 配合显示
            from core.state_manager import state_manager
            task = state_manager.get_state(StateKeys.CURRENT_TASK)
            sb.set_current_task(task, value)
        elif key == StateKeys.CURRENT_SCENE:
            sb.set_current_scene(value)
        elif key == StateKeys.CURRENT_ACCOUNT:
            sb.set_account(value)
        elif key == StateKeys.TODAY_OPERATION_COUNT:
            sb.set_ops_count(value)
        elif key == StateKeys.RUN_LIMIT_REACHED:
            sb.set_run_limit_reached(value)
        elif key == StateKeys.CONNECTION_STATUS:
            sb.set_connection(value)
        elif key == StateKeys.RUN_STATUS:
            sb.set_run_status(value)
        # 其余状态键（task_status/schedule_queue 等）由 TaskQueuePanel 订阅处理

    # ==================== 菜单路由（v2.5） ====================

    def _on_menu_clicked(self, item, data):
        try:
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
                self._show_monitor(key)
            elif kind == "ui_settings":
                self._switch_center_safe(self.ui_settings_panel)
            elif kind == "sub_account":
                self._show_sub_account(key)
            elif kind == "sub_account_detail":
                self._show_sub_account_detail(key)
        except Exception as e:
            self._show_placeholder(f"菜单加载失败: {e}")
            self.append_log.emit("ERROR", f"菜单路由异常 [{data}]: {e}")

    def _show_monitor(self, key: str):
        """运行监控子菜单路由（安全兜底）。"""
        panel_map = {
            "monitor:metrics": "metrics_panel",
            "monitor:snapshots": "snapshot_viewer",
            "monitor:report": "report_viewer",
            "monitor:history": "execution_history",
        }
        attr = panel_map.get(key)
        if attr and hasattr(self, attr):
            panel = getattr(self, attr)
            if panel is not None:
                self._switch_center(panel)
                return
        self._show_placeholder(f"「运行监控 - {key}」暂不可用")

    def _show_config(self, key: str):
        try:
            self._switch_center(self.config_panel)
            self.config_panel.show_config(key.replace("config:", ""))
        except Exception as e:
            self._show_placeholder(f"配置面板加载失败: {e}")

    def _show_image(self, key: str):
        try:
            self._switch_center(self.image_panel)
            self.image_panel.show_section(key.replace("image:", ""))
        except Exception as e:
            self._show_placeholder(f"图片面板加载失败: {e}")

    def _show_taskmgr(self, key: str):
        try:
            self._switch_center(self.task_mgr_panel)
            self.task_mgr_panel.show_section(key.replace("taskmgr:", ""))
        except Exception as e:
            self._show_placeholder(f"任务管理加载失败: {e}")

    def _show_game(self, key: str):
        """游戏任务：任务列表(上) + 点击查看配置(下)。"""
        self._switch_center(self._game_panel)
        cat = key.replace("game:", "")
        labels = {"daily":"📅 日常任务","permanent":"⚔ 常驻任务","event":"🎪 活动任务","special":"⭐ 特殊任务"}
        self._game_title.setText(labels.get(cat, "游戏任务"))
        self._game_cfg.hide()
        self._game_cfg_placeholder.show()
        self._game_cfg_placeholder.setText("↑ 点击上方任务查看配置")
        self._clear_game_rows()
        tasks = self.task_mgr.get_tasks_by_category(cat) if self.task_mgr else []
        if not tasks:
            lb = QLabel("（暂无任务）"); lb.setAlignment(Qt.AlignCenter)
            lb.setStyleSheet("color:#BDC1C6;font-size:13px;padding:24px;")
            self._game_rows_layout.insertWidget(self._game_rows_layout.count()-1, lb)
            self._task_filter = cat
            self._refresh_task_list()
            return
        for t in tasks:
            row = _GameTaskRow(t, self._on_game_task_clicked)
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
            self._game_cfg.hide()
            return

        try:
            self._current_game_task = t
            tt = getattr(t, 'task_type', 'event_task')
            self._game_cfg_title.setText(f"📋 「{t.display_name}」— {'战斗任务' if tt == 'battle' else '事件任务'}")

            # 从 tasks.yaml 加载现有配置
            cfg = self.config.get_task_config(t.name) or {}
            repeat = cfg.get("repeat", {}) or {}

            self._cfg_enabled.setChecked(cfg.get("enabled", False))
            self._cfg_priority.setValue(cfg.get("priority", 10))
            rtype = repeat.get("type", "daily")
            type_map = {"daily":0,"weekly":1,"monthly_start":2,"interval_days":3,"interval_hours":4,"once":5,"expire_at":6,"special":7}
            self._cfg_repeat_type.setCurrentIndex(type_map.get(rtype, 0))
            self._cfg_time_start.setText(str(repeat.get("time_start", "")))
            self._cfg_time_end.setText(str(repeat.get("time_end", "")))
            wds = repeat.get("weekdays") or []
            for d, cb in self._cfg_wd_checks.items():
                cb.setChecked(d in wds)
            self._cfg_days.setValue(repeat.get("days", 1) or 1)
            self._cfg_hours.setValue(float(repeat.get("hours", 1.0) or 1.0))
            self._cfg_once_at.setText(str(repeat.get("at", "")))
            w = repeat.get("window") or {}
            self._cfg_date_start.setText(str(w.get("date_start", "")))
            self._cfg_date_end.setText(str(w.get("date_end", "")))
            self._cfg_max_daily.setValue(repeat.get("max_daily", 0) or 0)
            self._cfg_max_total.setValue(repeat.get("max_total", 0) or 0)
            self._cfg_expire_at.setText(str(repeat.get("at", "")))
            # active_range
            ar = cfg.get("active_range") or repeat.get("active_range") or [None, None]
            self._cfg_active_start.setText(str(ar[0] or ""))
            if len(ar) > 1:
                self._cfg_active_end.setText(str(ar[1] or ""))
            # 执行规则
            er = cfg.get("execution_rule", {}) or {}
            is_time = er.get("mode") == "time"
            self._cfg_exec_mode.setCurrentIndex(1 if is_time else 0)
            self._cfg_exec_value.setValue(er.get("value", 1) or 1)
            # 下次执行
            nr = cfg.get("next_run_time", "")
            if not nr:
                nr = self._load_next_run_from_state(t.name)
            self._cfg_next_run.setText(str(nr))

            # 运行状态
            self._load_task_status(t.name)

            self._cfg_team.setVisible(tt == "battle")
            self._on_repeat_type_changed(self._cfg_repeat_type.currentIndex())
            self._game_cfg_save.show()
            self._game_cfg_placeholder.hide()
            self._game_cfg.show()
        except Exception as e:
            import traceback
            self.append_log.emit("ERROR", f"配置表单加载失败: {e}\n{traceback.format_exc()}")

    def _load_task_status(self, task_name: str):
        """加载任务运行状态（today_count / success_count / fail_streak）。"""
        try:
            from core.task_state import TaskStateStore
            store = TaskStateStore()
            store.load()
            st = store.get(task_name)
            if st:
                parts = []
                parts.append(f"今日: {st.today_count} 次")
                parts.append(f"累计成功: {st.success_count}")
                if st.fail_streak > 0:
                    parts.append(f"连续失败: {st.fail_streak} (冷却 {min(st.fail_streak*5, 60)}min)")
                self._cfg_status_label.setText("  |  ".join(parts))
            else:
                self._cfg_status_label.setText("暂无运行记录")
        except Exception:
            self._cfg_status_label.setText("")

    def _on_import_calendar(self):
        """导入活动日历文件。"""
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "导入活动日历", "", "JSON/YAML (*.json *.yaml);;All (*)")
        if not path:
            return
        try:
            import json, yaml
            with open(path, "r", encoding="utf-8") as f:
                if path.endswith(".yaml"):
                    events = yaml.safe_load(f)
                else:
                    events = json.load(f)
            if not isinstance(events, list):
                events = [events]
            count = self._scheduler.import_calendar(events)
            QMessageBox.information(self, "导入完成", f"已导入/更新 {count} 个活动任务")
            self._scheduler.build_schedule()
            self.task_queue.refresh()
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

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
        elif rtype == "expire_at":
            self._cfg_expire_at.setVisible(True)
        # monthly_start: 无额外字段（每月1号自动触发）
        # 始终显示的字段
        self._cfg_active_start.setVisible(True)
        self._cfg_active_end.setVisible(True)
        self._cfg_import_cal.setVisible(True)
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
        if rtype == "expire_at":
            at = self._cfg_expire_at.text().strip()
            if at: repeat["at"] = at

        md = self._cfg_max_daily.value()
        if md > 0:
            repeat["max_daily"] = md
        mt = self._cfg_max_total.value()
        if mt > 0:
            repeat["max_total"] = mt

        # active_range（所有类型通用）
        ar_start = self._cfg_active_start.text().strip()
        ar_end = self._cfg_active_end.text().strip()
        if ar_start or ar_end:
            repeat["active_range"] = [ar_start, ar_end]

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

    def _show_sub_account(self, key: str):
        """显示小号配置面板。"""
        try:
            self._switch_center(self.sub_account_panel)
        except Exception as e:
            self._show_placeholder(f"小号面板加载失败: {e}")

    def _show_sub_account_detail(self, account_id: str):
        """显示指定小号的详细配置。"""
        try:
            self._switch_center(self.sub_account_panel)
            if hasattr(self.sub_account_panel, '_on_card_clicked'):
                self.sub_account_panel._on_card_clicked(account_id)
        except Exception as e:
            self._show_placeholder(f"小号详情加载失败: {e}")

    def _on_game_task_clicked(self, t):
        """点击游戏任务行 → 显示配置表单。"""
        self._show_form_row(t)

    # ==================== UI 自控（11-用户界面模块） ====================

    def _on_ui_setting_changed(self, key: str, value):
        """响应 UI 设置面板的变更，即时生效。"""
        if key == "theme":
            self._apply_theme(value)
        elif key == "font_size":
            self._apply_font_size(value)
        elif key == "show_status_bar":
            self.status_bar.setVisible(value)
        elif key == "show_control_bar":
            self.control_bar.setVisible(value)
        elif key == "show_log_panel":
            self.log_panel.setVisible(value)
        elif key == "show_menu_tree":
            self.menu_tree.setVisible(value)
        elif key == "max_log_lines":
            self.log_panel.set_max_lines(value)
        elif key == "refresh_interval":
            pass  # 重启后生效
        # 其余设置在 UISettingsPanel 内部处理

    def _apply_theme(self, theme: str):
        """应用主题。"""
        if theme == "dark":
            self.setStyleSheet(self.styleSheet().replace(
                "#FFFFFF", "#1E1E2E").replace("#F8F9FA", "#2D2D3F"))
        # 简化处理：浅色/深色切换核心颜色

    def _apply_font_size(self, size: int):
        """全局字号调整（简化版：修改主字体）。"""
        f = QFont("Microsoft YaHei", size)
        self.setFont(f)

    # ==================== 启动/停止/暂停 ====================

    def _on_start(self):
        try:
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
        except Exception as e:
            self._running = False
            self.status_bar.set_run_status("stopped")
            self.log_panel.terminal.append_message("ERROR", f"启动失败: {e}")
            self.append_log.emit("ERROR", f"启动异常: {e}")

    def _on_stop(self):
        """停止：先进入 STOPPING 状态，等待 worker 优雅退出。"""
        try:
            self.control_bar.set_stopping()
            self.status_bar.set_run_status("stopping")
            self.log_panel.terminal.append_message("WARNING", "正在优雅停止...")
            event_bus.publish(Events.STOP_REQUESTED)
            if self.worker and self.worker.isRunning():
                self.worker.stop()
            self._running = False
        except Exception as e:
            self._running = False
            self.control_bar.set_idle()
            self.status_bar.set_run_status("stopped")
            self.log_panel.terminal.append_message("ERROR", f"停止异常: {e}")
        # worker finished_signal 会最终置为 idle

    def _on_pause(self):
        """暂停：发布 PAUSE_REQUESTED 事件，暂停 worker。"""
        event_bus.publish(Events.PAUSE_REQUESTED)
        if self.worker:
            self.worker.pause()
        self.control_bar.set_paused(True)
        self.status_bar.set_run_status("paused")
        self.log_panel.terminal.append_message("INFO", "脚本已暂停")

    def _on_resume(self):
        """恢复：发布 RESUME_REQUESTED 事件，恢复 worker。"""
        event_bus.publish(Events.RESUME_REQUESTED)
        if self.worker:
            self.worker.resume()
        self.control_bar.set_running(True)
        self.status_bar.set_run_status("running")
        self.log_panel.terminal.append_message("INFO", "脚本已恢复运行")

    def _on_dry_run_toggled(self, enabled: bool):
        """沙盒模式切换：不实际执行点击，仅记录日志。"""
        self.status_bar.set_dry_run(enabled)
        if self.worker and self.worker.executor:
            self.worker.executor.set_dry_run(enabled)
        self.append_log.emit("INFO", f"沙盒模式: {'开启' if enabled else '关闭'}")

    def _on_self_check(self):
        """启动前自检：检查 ADB / 素材 / 配置是否就绪。"""
        try:
            self.append_log.emit("INFO", "🔍 启动前自检...")
            # ADB 检查
            from device.adb_client import ADBClient
            adb_path = self.config.get("adb.path", "adb")
            adb = ADBClient(device_id=f"127.0.0.1:{self.config.get('adb.port', 16384)}", adb_path=adb_path)
            if adb.is_connected():
                self.append_log.emit("INFO", "  ✅ ADB 连接正常")
            else:
                self.append_log.emit("WARNING", "  ⚠ ADB 未连接")
            # 素材检查
            asset_count = sum(1 for _ in Path(PROJECT_ROOT / "assets").rglob("*.png"))
            self.append_log.emit("INFO", f"  {'✅' if asset_count > 0 else '⚠'} 素材: {asset_count} 张")
            self.append_log.emit("INFO", "🔍 自检完成")
        except Exception as e:
            self.append_log.emit("ERROR", f"自检失败: {e}")

    def _on_status_change(self, status: str):
        pass  # 状态由 worker 管理

    def _on_progress(self, msg: str):
        self.statusBar().showMessage(msg)

    def _on_finished(self, success: bool, message: str):
        try:
            self._running = False
            self.control_bar.set_idle()
            self.status_bar.set_run_status("stopped")
            self.log_panel.terminal.append_message(
                "INFO" if success else "ERROR", message)
        except Exception:
            pass  # 窗口可能已关闭

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
