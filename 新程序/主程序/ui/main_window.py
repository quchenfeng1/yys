"""
11-用户界面模块

MainWindow 主窗口（三栏 QSplitter 布局）。
对应设计书 §2.1/§3.1/§3.7/§5.2/§5.3。

设计原则：
- UI零逻辑：通过 10-参数桥接模块 与核心层交互
- 事件驱动刷新：22 种事件订阅自动更新，不轮询
- 三栏布局：左菜单 | 中央面板 | 右日志
- 底部状态栏：9 项运行状态
"""
from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMessageBox,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from ui.panels.config_panel import ConfigPanel
from ui.panels.control_bar import ControlBar
from ui.panels.execution_history import ExecutionHistoryPanel
from ui.panels.game_task_panel import GameTaskPanel
from ui.panels.image_manager_panel import ImageManagerPanel
from ui.panels.log_panel import LogPanel
from ui.panels.menu_tree import MenuTree
from ui.panels.status_bar import StatusBar
from ui.panels.sub_account_panel import SubAccountPanel
from ui.panels.task_manager_panel import TaskManagerPanel
from ui.panels.task_queue_panel import TaskQueuePanel
from ui.panels.ui_settings_panel import UISettingsPanel
from ui.theme import apply_theme


class MainWindow(QMainWindow):
    """
    主窗口：三栏布局（§5.2 方法定义）。

    Args:
        param_bridge: 10-参数桥接模块（UI 唯一通信通道）
        event_bus: 08-事件通信总线
        image_mgr: ImageManager（素材管理）
    """

    # §3.1 跨线程 UI 更新信号：事件总线分发线程 → Qt 主线程
    ui_update = pyqtSignal(object)  # 携带可调用对象，在主线程执行

    def __init__(
        self,
        param_bridge: Any = None,
        event_bus: EventBus | None = None,
        image_mgr: Any = None,
    ):
        super().__init__()
        self._param_bridge = param_bridge
        self._image_mgr = image_mgr
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名

        self.setWindowTitle("阴阳师自动化工具")
        self.setMinimumSize(1200, 800)

        # §2.3 面板注册表
        self.panels: dict[str, QWidget] = {}

        # 信号槽：在主线程执行 UI 更新（§3.1 跨线程安全）
        self.ui_update.connect(self._on_ui_update)

        self.init_ui()
        self._connect_events()

        # 调度队列自动整理：不点击启动也定期刷新
        # （get_due_tasks → build_schedule 推进过期任务 + 更新状态）
        self._queue_timer = QTimer(self)
        self._queue_timer.setInterval(5000)
        self._queue_timer.timeout.connect(self._on_queue_tick)
        self._queue_timer.start()

    def _on_queue_tick(self) -> None:
        """定时刷新队列面板（未启动也整理调度队列）"""
        self._refresh_queue_panel()

    def _on_ui_update(self, fn: Any) -> None:
        """在主线程执行传入的可调用对象（§3.1）"""
        try:
            fn()
        except Exception:
            pass

    # ── §5.2 init_ui ──────────────────────────────────────

    def init_ui(self) -> None:
        """初始化三栏布局 + 所有子面板 + 绑定（§5.2）"""
        # 应用全局主题（qt-material Material 浅蓝优先，失败兜底内置浅色主题；仅样式）
        try:
            from PyQt5.QtWidgets import QApplication
            _app = QApplication.instance()
            if _app is not None:
                apply_theme(_app)
        except Exception:
            pass

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部控制栏
        self.control_bar = ControlBar()
        layout.addWidget(self.control_bar)

        # 三栏分割
        self.splitter = QSplitter(Qt.Horizontal)

        # 左侧：菜单树
        self.menu_tree = MenuTree()
        self.menu_tree.setMinimumWidth(180)
        self.menu_tree.setMaximumWidth(300)

        # 中间：栈式面板（12 个面板）
        self.central_stack = QStackedWidget()
        self._create_panels()

        # 右侧：日志面板
        self.log_panel = LogPanel()
        self.log_panel.setMinimumWidth(250)
        self.log_panel.setMaximumWidth(450)

        self.splitter.addWidget(self.menu_tree)
        self.splitter.addWidget(self.central_stack)
        self.splitter.addWidget(self.log_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 1)

        layout.addWidget(self.splitter, 1)

        # 底部状态栏（9 项，§3.7）
        self.status_bar = StatusBar()
        layout.addWidget(self.status_bar)

        # 菜单树切换
        self.menu_tree.navigation_requested.connect(self._switch_panel)

        # 默认选中
        if self.panels:
            first_key = list(self.panels.keys())[0]
            self._switch_panel(first_key)

        # §5.2 调用 ParamBridge.bind_all()
        if self._param_bridge and hasattr(self._param_bridge, 'bind_all'):
            self._param_bridge.bind_all()

        # 连接控制栏按钮 → RunBridge（启停/暂停/恢复）
        self._connect_control_bar()

    def _create_panels(self) -> None:
        """创建全部 12 个面板（§5.1）"""
        panels = [
            ("game_task", "游戏任务", GameTaskPanel(param_bridge=self._param_bridge)),
            ("task_queue", "任务队列", TaskQueuePanel()),
            ("task_manager", "任务管理", TaskManagerPanel(param_bridge=self._param_bridge)),
            ("config", "配置", ConfigPanel(param_bridge=self._param_bridge)),
            ("image", "素材管理", ImageManagerPanel(param_bridge=self._param_bridge)),
            ("accounts", "小号管理", SubAccountPanel()),
            ("history", "执行历史", ExecutionHistoryPanel()),
            ("ui_settings", "UI 设置", UISettingsPanel()),
        ]
        for key, title, widget in panels:
            self.panels[key] = widget
            self.central_stack.addWidget(widget)

        # 连接任务队列面板的"手动触发"信号（触发式任务 → TaskBridge.update_next_run）
        qp = self.panels.get("task_queue")
        if qp is not None and hasattr(qp, 'manual_trigger_requested'):
            qp.manual_trigger_requested.connect(self._on_manual_trigger)

    def _switch_panel(self, key: str) -> None:
        """切换中央面板"""
        widget = self.panels.get(key)
        if widget:
            self.central_stack.setCurrentWidget(widget)

    def _connect_control_bar(self) -> None:
        """
        连接控制栏按钮 → ParamBridge 的 RunBridge（§3.2 运行传参）。

        用户点击启动/停止/暂停/恢复 → RunBridge 发布事件 → 09 订阅执行。
        """
        if not self._param_bridge:
            return
        run_bridge = getattr(self._param_bridge, 'run', None)
        if not run_bridge:
            return

        cb = self.control_bar
        cb.start_clicked.connect(lambda: self._safe_call(run_bridge.request_start))
        cb.stop_clicked.connect(lambda: self._safe_call(run_bridge.request_stop))
        cb.pause_clicked.connect(lambda: self._safe_call(run_bridge.request_pause))
        cb.resume_clicked.connect(lambda: self._safe_call(run_bridge.request_resume))

    @staticmethod
    def _safe_call(fn) -> None:
        """安全调用（捕获异常，避免 Qt 槽异常导致崩溃）"""
        try:
            fn()
        except Exception:
            pass

    # ── §5.2 refresh_task_list ─────────────────────────────

    def refresh_task_list(self) -> None:
        """
        刷新任务列表面板（§5.2）。

        通过 TaskBridge.get_task_list() 获取已注册任务，
        为每个任务生成一行配置控件（投递主线程）。
        """
        if not self._param_bridge:
            return
        bridge = getattr(self._param_bridge, 'task', None)
        if not bridge or not hasattr(bridge, 'get_task_list'):
            return
        try:
            tasks = bridge.get_task_list()
        except Exception:
            tasks = []
        # 控件更新必须在主线程执行（可能由事件线程触发）
        self.ui_update.emit(lambda: self._ui_load_tasks(tasks))

    def _ui_load_tasks(self, tasks: list) -> None:
        """（主线程）加载任务列表到面板"""
        task_panel = self.panels.get("task_manager")
        if task_panel and hasattr(task_panel, 'load_tasks'):
            try:
                metas = self._param_bridge.task.get_task_metas()
                task_panel.load_tasks(metas)
            except Exception:
                task_panel.load_tasks(tasks)
            # 通用模块（common，不单独执行）
            if hasattr(task_panel, 'load_generic'):
                try:
                    gmetas = self._param_bridge.task.get_generic_modules()
                    task_panel.load_generic(gmetas)
                except Exception:
                    pass
        # 游戏任务面板：加载带 uses_* 声明的元数据（设计书 §4.3 动态表单）
        game_panel = self.panels.get("game_task")
        if game_panel and hasattr(game_panel, 'load_tasks'):
            try:
                metas = self._param_bridge.task.get_task_metas()
                game_panel.load_tasks(metas)
            except Exception:
                pass

    # ── §3.1 事件驱动刷新（22 种事件）─────────────────────

    def _connect_events(self) -> None:
        """
        连接全部 22 种 UI 事件（§3.1 + §6.2）。
        """
        # 运行状态
        self._bus.subscribe(Events.STATE_CHANGED, self._on_state_changed)
        self._bus.subscribe(Events.STATE_RESET, self._on_state_reset)

        # 任务事件
        self._bus.subscribe(Events.TASK_STARTED, self._on_task_started)
        self._bus.subscribe(Events.TASK_COMPLETED, self._on_task_done)
        self._bus.subscribe(Events.TASK_SKIPPED, self._on_task_skipped)
        self._bus.subscribe(Events.EXECUTOR_STEP_COMPLETED, self._on_step_done)
        self._bus.subscribe(Events.TASK_QUEUED, self._on_task_queued)

        # 运行启停
        self._bus.subscribe(Events.RUN_STARTED, lambda **kw: self._on_run_started())
        self._bus.subscribe(Events.RUN_STOPPED, lambda **kw: self._on_run_stopped())
        self._bus.subscribe(Events.RUN_PAUSED, lambda **kw: self._on_run_paused())
        self._bus.subscribe(Events.RUN_ERROR, self._on_run_error)
        self._bus.subscribe(Events.RUN_LIMIT_REACHED, self._on_run_limit_reached)

        # 连接事件
        self._bus.subscribe(Events.CONNECTION_LOST, self._on_connection_lost)
        self._bus.subscribe(Events.CONNECTION_RESTORED, self._on_connection_restored)
        self._bus.subscribe(Events.CONNECTION_ERROR, self._on_connection_error)
        self._bus.subscribe(Events.CONNECTION_QUALITY_WARNING, self._on_connection_quality)

        # 调度更新
        self._bus.subscribe(Events.SCHEDULE_UPDATED, self._on_schedule_updated)

        # 日志
        self._bus.subscribe(Events.LOG_RECORD, self._on_log_record)
        self._bus.subscribe(Events.NOTIFY_ALERT, self._on_notify_alert)

        # 场景/素材
        self._bus.subscribe(Events.SCENE_UNKNOWN, self._on_scene_unknown)
        self._bus.subscribe(Events.SCENE_UPDATED, self._on_scene_updated)
        self._bus.subscribe(Events.ASSETS_MISSING, self._on_assets_missing)

        # 启动检查
        self._bus.subscribe(Events.PREFLIGHT_COMPLETE, self._on_preflight_complete)

        # 任务列表变更
        self._bus.subscribe(Events.TASKS_LIST_CHANGED,
                           lambda **kw: self.refresh_task_list())

    # ── 事件 handlers ──────────────────────────────────────

    def _on_state_changed(self, **kw: Any) -> None:
        """状态变更 → 更新状态栏 + 相关面板（投递主线程，§3.1）"""
        key = kw.get("key", "")
        value = kw.get("new_value")
        self.ui_update.emit(lambda: self._ui_apply_state(key, value))

    def _ui_apply_state(self, key: str, value: Any) -> None:
        """（主线程）应用状态变更到控件"""
        if key == "run_status" and self.status_bar:
            self.status_bar.update_run_status(value)
        elif key == "current_task" and self.status_bar:
            self.status_bar.update_current_task(value)
        elif key == "current_account" and self.status_bar:
            self.status_bar.update_current_account(value)
        elif key == "today_run_duration" and self.status_bar:
            self.status_bar.update_run_duration(value)
        elif key == "dry_run_mode" and self.status_bar:
            self.status_bar.update_dry_run_mode(value)
        elif key == "execution_history" and isinstance(value, list):
            # 执行历史面板（§3.9）：刷新记录
            history_panel = self.panels.get("history")
            if history_panel and hasattr(history_panel, 'add_record'):
                history_panel.table.setRowCount(0)
                for rec in value[-100:]:
                    if isinstance(rec, dict):
                        ts = rec.get("timestamp", "")[:19] if rec.get("timestamp") else ""
                        status = "成功" if rec.get("success") else "失败"
                        duration = f"{rec.get('duration', 0):.1f}s"
                        history_panel.add_record(ts, rec.get("task_name", ""), status, duration)
        elif key == "sub_account_status" and isinstance(value, dict):
            # 小号状态面板（§2.2）
            acc_panel = self.panels.get("accounts")
            if acc_panel and hasattr(acc_panel, 'update_accounts'):
                rows = []
                for sid, st in value.items():
                    rows.append({
                        "name": getattr(st, 'account_id', sid),
                        "status": getattr(st, 'status', 'unknown'),
                        "region": "cn",
                        "online": getattr(st, 'status', '') in ("scanning", "teaming", "battling"),
                        "remark": getattr(st, 'task', ''),
                    })
                acc_panel.update_accounts(rows)

    def _on_state_reset(self, **kw: Any) -> None:
        """状态重置 → 重载所有只读控件默认值（主线程）"""
        self.ui_update.emit(lambda: self.status_bar.reset_all() if self.status_bar else None)

    def _on_task_started(self, **kw: Any) -> None:
        task_id = kw.get("task_id", "")
        self.ui_update.emit(lambda: self._ui_task_started(task_id))

    def _ui_task_started(self, task_id: str) -> None:
        """（主线程）任务开始 → 更新状态栏 + 队列面板"""
        self.status_bar.update_current_task(task_id)
        queue_panel = self.panels.get("task_queue")
        if queue_panel and hasattr(queue_panel, 'on_task_started'):
            queue_panel.on_task_started(task_id)
        self._refresh_queue_panel()

    def _on_task_done(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self._ui_task_done())

    def _ui_task_done(self) -> None:
        """（主线程）任务完成 → 清空当前任务 + 刷新队列"""
        self.status_bar.update_current_task("")
        queue_panel = self.panels.get("task_queue")
        if queue_panel and hasattr(queue_panel, 'on_task_done'):
            queue_panel.on_task_done()
        self._refresh_queue_panel()

    def _on_task_queued(self, **kw: Any) -> None:
        """任务入队/出队 → 刷新队列三区"""
        self._refresh_queue_panel()

    def _refresh_queue_panel(self) -> None:
        """刷新任务队列三区：正在执行 / 待执行 / 未开始"""
        panel = self.panels.get("task_queue")
        if panel is None or not hasattr(panel, 'update_panel'):
            return
        current = None
        pending: list = []
        upcoming: list = []
        invalid: list = []
        runtime_q: list = []
        due: list = []
        try:
            if self._param_bridge and hasattr(self._param_bridge, 'run'):
                run = self._param_bridge.run
                current = run.get_current_task() if hasattr(run, 'get_current_task') else None
                runtime_q = run.get_queue_snapshot() if hasattr(run, 'get_queue_snapshot') else []
            if self._param_bridge and hasattr(self._param_bridge, 'task'):
                task = self._param_bridge.task
                # 待执行 = 运行时已入队任务 + 调度器到期任务（设计书 schedule_queue）
                if hasattr(task, 'get_due_tasks'):
                    due = task.get_due_tasks()
                if hasattr(task, 'get_upcoming'):
                    upcoming = task.get_upcoming()
                # 已失效 = 已过期 + 待配置（任务库未配置/停用）
                if hasattr(task, 'get_invalid_tasks'):
                    invalid = task.get_invalid_tasks()
        except Exception:
            pass
        # 合并去重：运行时队列优先，再补调度 DUE 任务
        # 关键：正在执行的任务（current）只显示在「正在执行」区，不进「待执行」区
        # （执行中任务的 next_run 尚未被 mark_done 清空，调度器仍判定其到期）
        pending = [n for n in runtime_q if n != current]
        for d in due:
            name = d.get("name", str(d)) if isinstance(d, dict) else str(d)
            if name == current or name in pending:
                continue
            pending.append(d)
        self.ui_update.emit(lambda: panel.update_panel(current, pending, upcoming, invalid))

    def _on_manual_trigger(self, task_name: str) -> None:
        """手动触发触发式任务（trigger）：UI"⚡触发"按钮 → TaskBridge.update_next_run(name, now)。

        置 next_run=当前时刻 → 任务立即到期 → 填充线程拾取入队（与 TriggerWatcher 识图触发同一链路）。
        """
        if not task_name:
            return
        if self._param_bridge and hasattr(self._param_bridge, 'task'):
            try:
                from datetime import datetime
                self._param_bridge.task.update_next_run(task_name, datetime.now())
                self._refresh_queue_panel()
            except Exception:
                pass

    def _on_task_skipped(self, **kw: Any) -> None:
        task_name = kw.get("task_name", "")
        self.ui_update.emit(lambda: self.status_bar.show_message(f"任务已跳过: {task_name}"))

    def _on_step_done(self, **kw: Any) -> None:
        step_id = kw.get("step_id", "")
        self.ui_update.emit(lambda: self.status_bar.show_message(f"步骤完成: {step_id}"))

    def _on_run_started(self) -> None:
        self.ui_update.emit(lambda: self.control_bar.set_running(True))

    def _on_run_stopped(self) -> None:
        self.ui_update.emit(lambda: self.control_bar.set_running(False))

    def _on_run_paused(self) -> None:
        self.ui_update.emit(lambda: self.control_bar.set_paused(True))

    def _on_run_error(self, **kw: Any) -> None:
        error = kw.get("error", "未知错误")
        self.ui_update.emit(lambda: self.status_bar.show_message(f"错误: {error}"))

    def _on_run_limit_reached(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.status_bar.show_message("已达今日上限，自动停止"))

    def _on_connection_lost(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.status_bar.update_connection("disconnected"))

    def _on_connection_restored(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.status_bar.update_connection("connected"))

    def _on_connection_error(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.status_bar.show_message("连接错误"))

    def _on_connection_quality(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.status_bar.update_quality("warning"))

    def _on_schedule_updated(self, **kw: Any) -> None:
        """日程更新 → 刷新队列卡片 + 状态栏（主线程）"""
        queue = kw.get("queue", [])
        self.ui_update.emit(lambda: self._ui_schedule_updated(queue))

    def _ui_schedule_updated(self, queue: list) -> None:
        """（主线程）日程刷新"""
        if hasattr(self.status_bar, 'update_queue_length'):
            self.status_bar.update_queue_length(len(queue))
        # 队列三区统一由 _refresh_queue_panel 重建（含"正在执行任务排除"），
        # 不再直接 refresh_queue，避免执行中任务闪现进待执行区
        self._refresh_queue_panel()

    def _on_log_record(self, **kw: Any) -> None:
        """日志记录 → 追加到日志面板（投递主线程，§3.1）"""
        payload = dict(kw)
        self.ui_update.emit(lambda: self.log_panel.append_log(**payload))

    def _on_notify_alert(self, **kw: Any) -> None:
        """通知提醒"""
        msg = kw.get("message", "")
        self.ui_update.emit(lambda: self.status_bar.show_message(msg))

    def _on_scene_unknown(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.log_panel.append_log(level="WARNING", message="未知场景"))

    def _on_scene_updated(self, **kw: Any) -> None:
        """场景感知命中（scene_updated）→ 状态栏显示当前场景"""
        scene = kw.get("scene", "")
        self.ui_update.emit(
            lambda: self.status_bar.update_current_scene(scene) if self.status_bar else None)

    def _on_assets_missing(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.log_panel.append_log(level="WARNING", message="素材缺失"))

    def _on_preflight_complete(self, **kw: Any) -> None:
        result = kw.get("result", {})
        self.ui_update.emit(lambda: self.status_bar.show_message("启动自检完成"))

    # ── 窗口事件 ──────────────────────────────────────────

    def closeEvent(self, event):
        """关闭窗口事件"""
        reply = QMessageBox.question(
            self, "确认退出", "确定要退出程序吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._bus.publish(Events.RUN_SHUTDOWN)
            event.accept()
        else:
            event.ignore()
