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

from PyQt5.QtCore import Qt
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


class MainWindow(QMainWindow):
    """
    主窗口：三栏布局（§5.2 方法定义）。

    Args:
        param_bridge: 10-参数桥接模块（UI 唯一通信通道）
        event_bus: 08-事件通信总线
        image_mgr: ImageManager（素材管理）
    """

    def __init__(
        self,
        param_bridge: Any = None,
        event_bus: EventBus | None = None,
        image_mgr: Any = None,
    ):
        super().__init__()
        self._param_bridge = param_bridge
        self._image_mgr = image_mgr
        self._bus = event_bus or get_global_bus()

        self.setWindowTitle("阴阳师自动化工具")
        self.setMinimumSize(1200, 800)

        # §2.3 面板注册表
        self.panels: dict[str, QWidget] = {}

        self.init_ui()
        self._connect_events()

    # ── §5.2 init_ui ──────────────────────────────────────

    def init_ui(self) -> None:
        """初始化三栏布局 + 所有子面板 + 绑定（§5.2）"""
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

    def _create_panels(self) -> None:
        """创建全部 12 个面板（§5.1）"""
        panels = [
            ("game_task", "游戏任务", GameTaskPanel()),
            ("task_queue", "任务队列", TaskQueuePanel()),
            ("task_manager", "任务管理", TaskManagerPanel()),
            ("config", "配置", ConfigPanel()),
            ("image", "素材管理", ImageManagerPanel()),
            ("accounts", "小号管理", SubAccountPanel()),
            ("history", "执行历史", ExecutionHistoryPanel()),
            ("ui_settings", "UI 设置", UISettingsPanel()),
        ]
        for key, title, widget in panels:
            self.panels[key] = widget
            self.central_stack.addWidget(widget)

    def _switch_panel(self, key: str) -> None:
        """切换中央面板"""
        widget = self.panels.get(key)
        if widget:
            self.central_stack.setCurrentWidget(widget)

    # ── §5.2 refresh_task_list ─────────────────────────────

    def refresh_task_list(self) -> None:
        """
        刷新任务列表面板（§5.2）。

        通过 TaskBridge.get_task_list() 获取已注册任务，
        为每个任务生成一行配置控件。
        """
        if not self._param_bridge:
            return
        bridge = getattr(self._param_bridge, 'task', None)
        if not bridge or not hasattr(bridge, 'get_task_list'):
            return
        try:
            tasks = bridge.get_task_list()
            task_panel = self.panels.get("task_manager")
            if task_panel and hasattr(task_panel, 'load_tasks'):
                task_panel.load_tasks(tasks)
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
        self._bus.subscribe(Events.ASSETS_MISSING, self._on_assets_missing)

        # 启动检查
        self._bus.subscribe(Events.PREFLIGHT_COMPLETE, self._on_preflight_complete)

        # 任务列表变更
        self._bus.subscribe(Events.TASKS_LIST_CHANGED,
                           lambda **kw: self.refresh_task_list())

    # ── 事件 handlers ──────────────────────────────────────

    def _on_state_changed(self, **kw: Any) -> None:
        """状态变更 → 更新状态栏"""
        key = kw.get("key", "")
        value = kw.get("new_value")
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

    def _on_state_reset(self, **kw: Any) -> None:
        """状态重置 → 重载所有只读控件默认值"""
        if self.status_bar:
            self.status_bar.reset_all()

    def _on_task_started(self, **kw: Any) -> None:
        task_id = kw.get("task_id", "")
        self.status_bar.update_current_task(task_id)
        queue_panel = self.panels.get("task_queue")
        if queue_panel and hasattr(queue_panel, 'on_task_started'):
            queue_panel.on_task_started(task_id)

    def _on_task_done(self, **kw: Any) -> None:
        self.status_bar.update_current_task("")
        queue_panel = self.panels.get("task_queue")
        if queue_panel and hasattr(queue_panel, 'on_task_done'):
            queue_panel.on_task_done()

    def _on_task_skipped(self, **kw: Any) -> None:
        task_name = kw.get("task_name", "")
        if hasattr(self.status_bar, 'show_message'):
            self.status_bar.show_message(f"任务已跳过: {task_name}")

    def _on_step_done(self, **kw: Any) -> None:
        step_id = kw.get("step_id", "")
        if hasattr(self.status_bar, 'show_message'):
            self.status_bar.show_message(f"步骤完成: {step_id}")

    def _on_run_started(self) -> None:
        if hasattr(self.control_bar, 'set_running'):
            self.control_bar.set_running(True)

    def _on_run_stopped(self) -> None:
        if hasattr(self.control_bar, 'set_running'):
            self.control_bar.set_running(False)

    def _on_run_paused(self) -> None:
        if hasattr(self.control_bar, 'set_paused'):
            self.control_bar.set_paused(True)

    def _on_run_error(self, **kw: Any) -> None:
        error = kw.get("error", "未知错误")
        if hasattr(self.status_bar, 'show_message'):
            self.status_bar.show_message(f"错误: {error}")

    def _on_run_limit_reached(self, **kw: Any) -> None:
        if hasattr(self.status_bar, 'show_message'):
            self.status_bar.show_message("已达今日上限，自动停止")

    def _on_connection_lost(self, **kw: Any) -> None:
        if hasattr(self.status_bar, 'update_connection'):
            self.status_bar.update_connection("disconnected")

    def _on_connection_restored(self, **kw: Any) -> None:
        if hasattr(self.status_bar, 'update_connection'):
            self.status_bar.update_connection("connected")

    def _on_connection_error(self, **kw: Any) -> None:
        if hasattr(self.status_bar, 'show_message'):
            self.status_bar.show_message("连接错误")

    def _on_connection_quality(self, **kw: Any) -> None:
        if hasattr(self.status_bar, 'update_quality'):
            self.status_bar.update_quality("warning")

    def _on_schedule_updated(self, **kw: Any) -> None:
        """日程更新 → 刷新队列卡片 + 状态栏"""
        queue = kw.get("queue", [])
        if hasattr(self.status_bar, 'update_queue_length'):
            self.status_bar.update_queue_length(len(queue))
        queue_panel = self.panels.get("task_queue")
        if queue_panel and hasattr(queue_panel, 'refresh_queue'):
            queue_panel.refresh_queue(queue)

    def _on_log_record(self, **kw: Any) -> None:
        """日志记录 → 追加到日志面板"""
        if hasattr(self.log_panel, 'append_log'):
            self.log_panel.append_log(**kw)

    def _on_notify_alert(self, **kw: Any) -> None:
        """通知提醒"""
        if hasattr(self.status_bar, 'show_message'):
            msg = kw.get("message", "")
            self.status_bar.show_message(msg)

    def _on_scene_unknown(self, **kw: Any) -> None:
        if hasattr(self.log_panel, 'append_log'):
            self.log_panel.append_log(level="WARNING", message="未知场景")

    def _on_assets_missing(self, **kw: Any) -> None:
        if hasattr(self.log_panel, 'append_log'):
            self.log_panel.append_log(level="WARNING", message="素材缺失")

    def _on_preflight_complete(self, **kw: Any) -> None:
        result = kw.get("result", {})
        if hasattr(self.status_bar, 'show_message'):
            self.status_bar.show_message("启动自检完成")

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
