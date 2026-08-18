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
    QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from ui.panels.settings_panel import SettingsPanel
from ui.panels.control_bar import ControlBar
from ui.panels.anomaly_tasks_panel import AnomalyTasksPanel
from ui.panels.emulator_manager_panel import EmulatorManagerPanel
from ui.panels.game_task_panel import GameTaskPanel
from ui.panels.log_panel import LogPanel
from ui.panels.menu_tree import MenuTree
from ui.panels.signal_manager_panel import SignalManagerPanel
from ui.panels.status_bar import StatusBar
from ui.panels.sub_account_panel import SubAccountPanel
from ui.panels.task_manager_panel import TaskManagerPanel
from ui.panels.task_queue_panel import TaskQueuePanel
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
        visual_bridge: Any = None,
    ):
        super().__init__()
        self._param_bridge = param_bridge
        self._image_mgr = image_mgr
        self._visual_bridge = visual_bridge
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

        # 右侧：日志/终端 抽屉（可收起，省出中央区域空间）
        self.right_drawer = QWidget()
        rd_lay = QHBoxLayout(self.right_drawer)
        rd_lay.setContentsMargins(0, 0, 0, 0)
        rd_lay.setSpacing(0)

        self.drawer_handle = QToolButton()
        self.drawer_handle.setFixedWidth(30)
        self.drawer_handle.setToolTip("收起 / 展开 日志与终端")
        self.drawer_handle.setStyleSheet(
            "QToolButton { background:#eef4fd; border:1px solid #bcd4f0;"
            " margin:6px 2px; }"
            "QToolButton:hover { background:#dcebfc; }"
        )
        self.drawer_handle.clicked.connect(self._toggle_drawer)
        rd_lay.addWidget(self.drawer_handle)

        self.log_panel = LogPanel()
        self.log_panel.setMinimumWidth(250)
        self.log_panel.setMaximumWidth(450)
        rd_lay.addWidget(self.log_panel, 1)

        # 默认收起右侧日志（点把手展开）
        self.log_panel.hide()
        from ui.theme import icon as _theme_icon
        _ic = _theme_icon("fa5s.angle-left", "#1e6fd9")  # 指向左 → 点击展开
        if _ic:
            self.drawer_handle.setIcon(_ic)

        self.splitter.addWidget(self.menu_tree)
        self.splitter.addWidget(self.central_stack)
        self.splitter.addWidget(self.right_drawer)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 1)

        layout.addWidget(self.splitter, 1)

        # 底部状态栏（9 项，§3.7）
        self.status_bar = StatusBar()
        layout.addWidget(self.status_bar)

        # 菜单树切换
        self.menu_tree.navigation_requested.connect(self._switch_panel)

        # 默认选中：任务队列（打开脚本自动进入）
        if "task_queue" in self.panels:
            self._switch_panel("task_queue")
            self.menu_tree.select("task_queue")
        elif self.panels:
            first_key = list(self.panels.keys())[0]
            self._switch_panel(first_key)

        # §5.2 调用 ParamBridge.bind_all()
        if self._param_bridge and hasattr(self._param_bridge, 'bind_all'):
            self._param_bridge.bind_all()

        # 连接控制栏按钮 → RunBridge（启停/暂停/恢复）
        self._connect_control_bar()

        # 设置面板 → 绑定 LogPanel（日志级别 / 自动滚动 / 字体大小 实时生效）
        _settings = self.panels.get("config")
        if _settings is not None:
            _ui_panel = getattr(_settings, 'ui_panel', None)
            if _ui_panel is not None and hasattr(_ui_panel, 'bind_log_panel'):
                _ui_panel.bind_log_panel(self.log_panel)

    def _create_panels(self) -> None:
        """创建全部 12 个面板（§5.1）"""
        panels = [
            ("game_task", "游戏任务", GameTaskPanel(param_bridge=self._param_bridge,
                                                     visual_bridge=self._visual_bridge)),
            ("task_queue", "任务队列", TaskQueuePanel()),
            ("task_manager", "任务管理", TaskManagerPanel(
                param_bridge=self._param_bridge,
                visual_bridge=self._visual_bridge)),
            ("config", "设置", SettingsPanel(param_bridge=self._param_bridge)),
            ("image", "素材管理", self._make_material_preview()),
            ("accounts", "账号管理", SubAccountPanel(param_bridge=self._param_bridge)),
            ("emulators", "模拟器管理", self._make_emulator_panel()),
            ("signals", "信号管理", self._make_signal_panel()),
            ("anomalies", "异常任务", self._make_anomaly_panel()),
        ]
        for key, title, widget in panels:
            self.panels[key] = widget
            self.central_stack.addWidget(widget)

        # 17-可视化构建：可视化构建面板（节点画布 + 示教控制台）
        try:
            from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
            vb = VisualBuilderPanel(visual_bridge=self._visual_bridge)
            self.panels["visual_builder"] = vb
            self.central_stack.addWidget(vb)
        except Exception:
            pass

        # 连接任务队列面板的"手动触发"信号（触发式任务 → TaskBridge.update_next_run）
        qp = self.panels.get("task_queue")
        if qp is not None and hasattr(qp, 'manual_trigger_requested'):
            qp.manual_trigger_requested.connect(self._on_manual_trigger)

    def _system_bridge(self) -> Any:
        """ParamBridge.system（游戏/模拟器切换桥，可选）。"""
        pb = self._param_bridge
        return getattr(pb, 'system', None) if pb is not None else None

    def _make_emulator_panel(self) -> QWidget:
        """模拟器管理面板（数据经 SystemBridge 注入）。"""
        sysb = self._system_bridge()
        if sysb is not None:
            panel = EmulatorManagerPanel(
                list_provider=sysb.emulator_list,
                save_callback=sysb.save_emulator,
                delete_callback=sysb.delete_emulator,
                scan_callback=sysb.scan_emulators,
            )
        else:
            panel = EmulatorManagerPanel()
        panel.emulators_changed.connect(self._refresh_emulator_combo)
        return panel

    def _make_signal_panel(self) -> QWidget:
        """信号管理面板（数据经 VisualBridge 注入，2026-08-16）。"""
        vb = self._visual_bridge
        if vb is not None:
            return SignalManagerPanel(
                scene_provider=vb.scene_signal_list,
                trigger_provider=vb.trigger_signal_list,
                task_provider=vb.task_signal_list,
                custom_provider=vb.custom_signal_list,
                add_custom_cb=vb.add_custom_signal,
                remove_custom_cb=vb.remove_custom_signal,
            )
        return SignalManagerPanel()

    def _make_anomaly_panel(self) -> QWidget:
        """异常任务面板（数据经 VisualBridge 注入，2026-08-16）。"""
        vb = self._visual_bridge
        if vb is not None:
            panel = AnomalyTasksPanel(
                abnormal_provider=vb.anomaly_abnormal_tasks,
                list_provider=vb.anomaly_list,
                mark_handled_cb=vb.anomaly_mark_handled,
                confirm_fixed_cb=vb.anomaly_confirm_fixed,
                unresolved_cb=vb.anomaly_unresolved_count,
            )
        else:
            panel = AnomalyTasksPanel()
        panel.handle_requested.connect(self._jump_to_anomaly_node)
        return panel

    def _jump_to_anomaly_node(self, task_name: str, node_id: str) -> None:
        """异常「处理」：切到可视化构建并定位异常节点（2026-08-16）。"""
        self._switch_panel("visual_builder")
        vb = self.panels.get("visual_builder")
        if vb is not None and hasattr(vb, "open_task_and_select"):
            try:
                vb.open_task_and_select(task_name, node_id)
            except Exception:
                pass

    def _make_material_preview(self) -> QWidget:
        """素材管理（2026-08-15）：替换失效的老素材管理面板。

        数据源 = 可视化构建素材体系（全局素材库）：
          场景识别素材（SceneStore）/ 操作识别素材（assets/**/icons/*.json）
          / OCR识别素材（assets/**/ocr/*.json）
        删除：场景走 bridge.delete_scene；图标/OCR 由组件删除条目文件。
        """
        from ui.visual_builder.material_preview import MaterialPreviewWidget
        bridge = self._visual_bridge
        if bridge is not None:
            def _del_cb(kind: str, key: str, data: dict):
                if kind == "scene":
                    ok = bridge.delete_scene(key)
                    return ok, ("" if ok else "素材库删除失败")
                return True, ""
            return MaterialPreviewWidget(
                assets_dir=str(getattr(bridge, "_assets_dir", "") or ""),
                scenes_provider=bridge.scene_list,
                elements_provider=bridge.icon_items,
                ocr_provider=bridge.ocr_items,
                scene_loader=bridge.load_scene,
                delete_callback=_del_cb,
                scene_save_callback=bridge.save_scene,
            )
        try:
            from core.game_profile import current_game_assets
            return MaterialPreviewWidget(
                assets_dir=str(current_game_assets() or ""))
        except Exception:
            return MaterialPreviewWidget()

    def _switch_panel(self, key: str) -> None:
        """切换中央面板"""
        widget = self.panels.get(key)
        if widget:
            self.central_stack.setCurrentWidget(widget)

    # ── §3.8 UI 自控：面板显隐 + 主题切换 ─────────────────

    def set_panel_visible(self, key: str, visible: bool) -> None:
        """显示/隐藏中央面板（UI 设置面板调用，§3.8 面板显隐控制）。

        隐藏：从 QStackedWidget 移除 widget + 隐藏菜单项；
        显示：重新加入 + 显示菜单项。
        """
        widget = self.panels.get(key)
        if widget is None:
            return
        if visible:
            # 已加入则无需重复 add
            if self.central_stack.indexOf(widget) < 0:
                self.central_stack.addWidget(widget)
        else:
            idx = self.central_stack.indexOf(widget)
            if idx >= 0:
                self.central_stack.removeWidget(widget)
            if self.central_stack.currentWidget() == widget:
                # 切换到第一个可见面板
                first = self.panels.get("game_task")
                if first is not None and self.central_stack.indexOf(first) >= 0:
                    self.central_stack.setCurrentWidget(first)
        if hasattr(self.menu_tree, 'set_item_visible'):
            self.menu_tree.set_item_visible(key, visible)

    def set_theme(self, theme: str) -> None:
        """切换明/暗主题（§3.8 主题切换）"""
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                apply_theme(app, theme=theme)
                self._current_theme = theme
        except Exception:
            pass

    def _toggle_drawer(self) -> None:
        """切换右侧日志/终端抽屉（收起/展开）"""
        from ui.theme import icon as _theme_icon
        if self.log_panel.isVisible():
            self.log_panel.hide()
            _ic = _theme_icon("fa5s.angle-left", "#1e6fd9")
            if _ic:
                self.drawer_handle.setIcon(_ic)   # 指向左 → 点击展开
        else:
            self.log_panel.show()
            _ic = _theme_icon("fa5s.angle-right", "#1e6fd9")
            if _ic:
                self.drawer_handle.setIcon(_ic)   # 指向右 → 点击收起

    def _connect_control_bar(self) -> None:
        """
        连接控制栏按钮 → ParamBridge 的 RunBridge（§3.2 运行传参）。

        布局（2026-08-16）：游戏选择 → 连接/断开 → 启动/暂停/停止。
        沙盒/自检按钮已移除（试跑由可视化构建测试启动覆盖）。
        """
        if not self._param_bridge:
            return
        run_bridge = getattr(self._param_bridge, 'run', None)
        if not run_bridge:
            return

        cb = self.control_bar
        cb.start_clicked.connect(self._on_start_request)
        cb.stop_clicked.connect(lambda: self._safe_call(run_bridge.request_stop))
        cb.pause_clicked.connect(lambda: self._safe_call(run_bridge.request_pause))
        cb.resume_clicked.connect(lambda: self._safe_call(run_bridge.request_resume))
        cb.emulator_changed.connect(self._on_emulator_changed)
        cb.game_changed.connect(self._on_game_changed)
        cb.connect_toggled.connect(self._on_connect_toggle)

        # 填充模拟器下拉 + 游戏下拉 + 初始状态
        self._last_emu = ""
        self._refresh_emulator_combo()
        self._last_game = ""
        if self._visual_bridge is not None and hasattr(self._visual_bridge, 'game_list'):
            try:
                games = self._visual_bridge.game_list() or []
                cb.set_games(games)
                cur = getattr(self._visual_bridge, 'current_game', '')
                if cur:
                    cb.set_current_game(cur)
                    self._last_game = cur
            except Exception:
                pass
        cb.set_connected(self._is_device_connected())

    def _refresh_emulator_combo(self) -> None:
        """刷新顶部模拟器下拉（模拟器管理面板增删改后调用）。"""
        sysb = self._system_bridge()
        cb = self.control_bar
        if sysb is None:
            cb.set_emulators([])
            return
        try:
            items = [(e.get("id", ""),
                      f"{e.get('name', '')} ({e.get('host', '')}:{e.get('port', '')})")
                     for e in sysb.emulator_list()]
        except Exception:
            items = []
        cb.set_emulators(items)
        # 保持当前选中（若被删则回退第一个）
        if self._last_emu:
            cb.set_current_emulator(self._last_emu)
            self._last_emu = cb.current_emulator()
        if not self._last_emu and items:
            cb.set_current_emulator(items[0][0])
            self._last_emu = items[0][0]

    def _on_emulator_changed(self, emu_id: str) -> None:
        """模拟器下拉切换：断开旧设备 → 连接新模拟器（运行中禁止）。"""
        if not emu_id:
            return
        if self._is_running():
            self.status_bar.show_message("脚本运行中，无法切换模拟器")
            if self._last_emu:
                self.control_bar.set_current_emulator(self._last_emu)
            return
        sysb = self._system_bridge()
        if sysb is None:
            self._last_emu = emu_id
            return
        self.status_bar.show_message(f"正在连接模拟器...")
        ok = sysb.switch_emulator(emu_id)
        if ok:
            self._last_emu = emu_id
            self.control_bar.set_connected(True)
            self.status_bar.show_message("模拟器已连接")
        else:
            self.status_bar.show_message("模拟器连接失败（未启动？ADB 调试未开？）")
            if self._last_emu:
                self.control_bar.set_current_emulator(self._last_emu)

    def _is_device_connected(self) -> bool:
        """当前设备是否已连接（RunBridge 优先，回退 VisualBridge）"""
        run_bridge = getattr(self._param_bridge, 'run', None)
        if run_bridge is not None and hasattr(run_bridge, 'is_connected'):
            try:
                return bool(run_bridge.is_connected())
            except Exception:
                pass
        vb = self._visual_bridge
        if vb is not None and hasattr(vb, 'is_connected'):
            try:
                return bool(vb.is_connected())
            except Exception:
                pass
        return False

    def _on_game_changed(self, game_id: str) -> None:
        """切换游戏：B方案后端整体重建（仅脚本未运行时允许，2026-08-16）。"""
        if not game_id:
            return
        if self._is_running():
            self.status_bar.show_message("脚本运行中，无法切换游戏")
            # 回退下拉
            cb = self.control_bar
            if hasattr(cb, 'set_current_game') and self._last_game:
                cb.set_current_game(self._last_game)
            return
        sysb = self._system_bridge()
        if sysb is not None:
            ok = sysb.switch_game(game_id)
            if not ok:
                self.status_bar.show_message(f"切换游戏失败: {game_id}")
                if self._last_game:
                    self.control_bar.set_current_game(self._last_game)
                return
        self._last_game = game_id
        if self._visual_bridge is not None \
                and hasattr(self._visual_bridge, 'set_current_game'):
            try:
                self._visual_bridge.set_current_game(game_id)
            except Exception:
                pass
        # 可视化构建面板：刷新通用节点/素材下拉（跟随全局游戏）
        vb_panel = self.panels.get("visual_builder")
        if vb_panel is not None and hasattr(vb_panel, 'on_game_switched'):
            try:
                vb_panel.on_game_switched()
            except Exception:
                pass
        self.status_bar.show_message(f"已切换游戏: {game_id}")
        self.refresh_task_list()
        self._refresh_queue_panel()
        # 任务管理/素材管理面板跟随新游戏目录刷新
        for key in ("task_manager",):
            p = self.panels.get(key)
            if p is not None and hasattr(p, 'refresh'):
                try:
                    p.refresh()
                except Exception:
                    pass

    def _is_running(self) -> bool:
        run_bridge = getattr(self._param_bridge, 'run', None)
        ctrl = getattr(run_bridge, '_ctrl', None) if run_bridge else None
        if ctrl is not None:
            try:
                return bool(getattr(ctrl, 'is_running', False))
            except Exception:
                pass
        return False

    def _on_connect_toggle(self) -> None:
        """连接/断开模拟器按钮（2026-08-16）。

        连接时优先连接顶部选中的模拟器（有选择时），否则走自动发现。
        """
        run_bridge = getattr(self._param_bridge, 'run', None)
        if run_bridge is None:
            return
        if self._is_running():
            self.status_bar.show_message("脚本运行中，请先停止再操作连接")
            return
        connected = self._is_device_connected()
        if connected:
            self.status_bar.show_message("正在断开连接...")
            run_bridge.disconnect_device()
        else:
            emu_id = self.control_bar.current_emulator()
            sysb = self._system_bridge()
            self.status_bar.show_message("正在连接模拟器...")
            if emu_id and sysb is not None:
                ok = sysb.switch_emulator(emu_id)
            else:
                ok = run_bridge.connect_device()
            self.status_bar.show_message(
                "设备连接成功" if ok else "连接失败（模拟器未启动？）")
        self.control_bar.set_connected(self._is_device_connected())

    @staticmethod
    def _safe_call(fn) -> None:
        """安全调用（捕获异常，避免 Qt 槽异常导致崩溃）"""
        try:
            fn()
        except Exception:
            pass

    def _on_start_request(self) -> None:
        """正式启动：可视化测试运行中时拒绝并提示（互斥）"""
        try:
            ok = self._param_bridge.run.request_start()
        except Exception:
            return
        if ok is False:
            self.status_bar.show_message("可视化测试运行中，无法启动脚本")

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
        self._bus.subscribe(Events.TASK_PAUSED, self._on_task_pause_state)
        self._bus.subscribe(Events.TASK_RESUMED, self._on_task_pause_state)

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

        # 可视化任务保存/删除 → 刷新任务列表（游戏任务/任务管理可见）
        self._bus.subscribe(Events.VISUAL_TASK_CHANGED,
                            lambda **kw: self.refresh_task_list())

        # 日志
        self._bus.subscribe(Events.LOG_RECORD, self._on_log_record)
        self._bus.subscribe(Events.NOTIFY_ALERT, self._on_notify_alert)

        # 场景/素材
        self._bus.subscribe(Events.SCENE_UNKNOWN, self._on_scene_unknown)
        self._bus.subscribe(Events.SCENE_UPDATED, self._on_scene_updated)
        self._bus.subscribe(Events.ASSETS_MISSING, self._on_assets_missing)

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

    def _on_task_pause_state(self, **kw: Any) -> None:
        """任务暂停/唤醒（2026-08-16 信号体系）→ 刷新队列面板暂停展示"""
        self._refresh_queue_panel()

    def _refresh_queue_panel(self) -> None:
        """刷新任务队列：正在执行 / 待执行 / 待触发 / 未开始 / 已失效 + 暂停展示"""
        panel = self.panels.get("task_queue")
        if panel is None or not hasattr(panel, 'update_panel'):
            return
        current = None
        pending: list = []
        upcoming: list = []
        invalid: list = []
        trigger: list = []
        paused: list = []
        runtime_q: list = []
        due: list = []
        try:
            if self._param_bridge and hasattr(self._param_bridge, 'run'):
                run = self._param_bridge.run
                current = run.get_current_task() if hasattr(run, 'get_current_task') else None
                runtime_q = run.get_queue_snapshot() if hasattr(run, 'get_queue_snapshot') else []
                paused = run.get_paused_snapshot() if hasattr(run, 'get_paused_snapshot') else []
            if self._param_bridge and hasattr(self._param_bridge, 'task'):
                task = self._param_bridge.task
                # 待执行 = 运行时已入队任务 + 调度器到期任务（设计书 schedule_queue）
                if hasattr(task, 'get_due_tasks'):
                    due = task.get_due_tasks()
                if hasattr(task, 'get_upcoming'):
                    upcoming = task.get_upcoming()
                # 待触发（信号体系）：含任务信号触发器节点的任务（2026-08-16）
                if hasattr(task, 'get_pending_trigger_tasks'):
                    trigger = task.get_pending_trigger_tasks()
                # 已失效 = 已过期 + 待配置（任务库未配置/停用）
                if hasattr(task, 'get_invalid_tasks'):
                    invalid = task.get_invalid_tasks()
        except Exception:
            pass
        # 合并去重：运行时队列优先，再补调度 DUE 任务（seen 去重，避免 str/dict 混重）
        # 关键：正在执行的任务（current）只显示在「正在执行」区，不进「待执行」区
        # （执行中任务的 next_run 尚未被 mark_done 清空，调度器仍判定其到期）
        pending = []
        seen: set = set()
        for n in runtime_q:
            if n != current and n not in seen:
                pending.append(n)
                seen.add(n)
        for d in due:
            name = d.get("name", str(d)) if isinstance(d, dict) else str(d)
            if name == current or name in seen:
                continue
            pending.append(d)
            seen.add(name)
        # 总体进度条已退役（2026-08-16）：任务队列面板改为
        # 「当前步骤」+ 执行进度抽屉（可视化任务 VISUAL_PROGRESS 快照驱动）
        self.ui_update.emit(lambda: panel.update_panel(current, pending, upcoming,
                                                       invalid, trigger, paused))

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

    def _on_self_check(self) -> None:
        """自检按钮已移除（2026-08-16）：连接状态由顶部连接按钮反映；
        后端 RunBridge.run_self_check 保留（备查），此入口不再使用。"""
        return None

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
        # 中断时同步游戏任务配置页「下次执行」（任务可能 mark_done 推进了 next_run）
        self.ui_update.emit(lambda: self._sync_game_next_run())

    def _on_run_paused(self) -> None:
        self.ui_update.emit(lambda: self.control_bar.set_paused(True))

    def _on_run_error(self, **kw: Any) -> None:
        error = kw.get("error", "未知错误")
        self.ui_update.emit(lambda: self.status_bar.show_message(f"错误: {error}"))

    def _on_run_limit_reached(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.status_bar.show_message("已达今日上限，自动停止"))

    def _on_connection_lost(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.status_bar.update_connection("disconnected"))
        self.ui_update.emit(lambda: self.control_bar.set_connected(False))

    def _on_connection_restored(self, **kw: Any) -> None:
        self.ui_update.emit(lambda: self.status_bar.update_connection("connected"))
        self.ui_update.emit(lambda: self.control_bar.set_connected(True))

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
        # 任务执行完（mark_done 已推进 next_run，SCHEDULE_UPDATED 在其后发布）
        # → 实时同步游戏任务配置页「下次执行」
        self._sync_game_next_run()

    def _sync_game_next_run(self) -> None:
        """同步游戏任务配置页「下次执行」输入框（任务执行完/中断后）"""
        game_panel = self.panels.get("game_task")
        if game_panel is None or not hasattr(game_panel, 'refresh_next_run_time'):
            return
        try:
            game_panel.refresh_next_run_time()
        except Exception:
            pass

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
