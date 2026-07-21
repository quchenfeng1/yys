"""
16-应用启动引导（Application Bootstrap）

职责：
  按正确的依赖顺序初始化所有 16 个模块，建立模块间的引用关系，启动 UI，处理优雅关闭

初始化顺序（7层）：
  第1层（基础设施）  : 06-配置管理中心, 08-事件通信总线
  第2层（基础服务）  : 12-日志监控中心, 07-运行时状态管理
  第3层（核心功能）  : 01-设备连接模块, 02-图像识别模块, 03-防封策略模块
  第4层（业务编排）  : 05-时间调度模块, 14-执行器模块, 04-任务执行引擎, 13-任务文件管理, 10-参数桥接模块
  第5层（运行控制）  : 09-运行控制中心
  第6层（账号管理）  : 15-账号管理模块
  第7层（用户界面）  : 11-用户界面模块
"""

from __future__ import annotations

import logging
import signal
import sys
from typing import Optional

logger = logging.getLogger(__name__)


class ApplicationBootstrap:
    """应用启动引导：创建并持有所有模块的单例实例"""

    def __init__(self):
        self._modules: dict[str, object] = {}
        self._init_order: list[str] = []
        self._shutdown_hooks: list[callable] = []

    # ── 公开方法 ──────────────────────────────────────────────

    def start(self) -> None:
        """启动程序：初始化所有模块 → 显示 UI → 进入事件循环"""
        self.initialize()
        # 显示 UI
        ui = self.get_module("ui")
        ui.show()
        # 注册信号处理
        signal.signal(signal.SIGINT, lambda s, f: self.shutdown())
        signal.signal(signal.SIGTERM, lambda s, f: self.shutdown())
        # 进入 Qt 事件循环
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance().exec_() if QApplication.instance() else 0

    def initialize(self) -> None:
        """按初始化顺序创建所有模块实例"""
        # 第1层：基础设施 — 事件总线必须在配置之前初始化
        event_bus = self._init_event_bus()
        config = self._init_config()
        # 第2层：基础服务
        monitor = self._init_monitor(config, event_bus)
        state_manager = self._init_state_manager(event_bus)
        # 第3层：核心功能
        connection = self._init_connection(config, event_bus, state_manager)
        recognizer = self._init_recognizer(connection, config, monitor)
        anti_detect = self._init_anti_detect(config, monitor)
        # 第4层：业务编排
        scheduler = self._init_scheduler(config, state_manager, event_bus)
        executor = self._init_executor(recognizer, anti_detect, connection, monitor, config)
        task_registry = self._init_task_engine(config, event_bus, state_manager)
        task_manager = self._init_task_manager()
        param_bridge = self._init_param_bridge(config, event_bus, state_manager, scheduler)
        # 第5层：运行控制
        run_controller = self._init_run_controller(
            scheduler, task_registry, connection, config,
            state_manager, event_bus, monitor,
            executor, recognizer, anti_detect
        )
        # 第6层：账号管理
        account_manager = self._init_account_manager(config, connection, state_manager, event_bus, scheduler)
        # 第7层：用户界面
        ui = self._init_ui(param_bridge, event_bus, task_registry, task_manager)
        # 注册关闭钩子
        self._shutdown_hooks = [
            run_controller.stop,
            lambda: scheduler.save_state(),
            connection.disconnect,
        ]
        self._init_order = [
            "config", "event_bus", "monitor", "state_manager",
            "connection", "recognizer", "anti_detect",
            "scheduler", "executor", "task_engine", "task_manager", "param_bridge",
            "run_controller", "account_manager", "ui",
        ]
        logger.info("全部模块初始化完成")

    def shutdown(self) -> None:
        """优雅关闭：按初始化逆序执行关闭回调"""
        logger.info("正在关闭程序...")
        for hook in reversed(self._shutdown_hooks):
            try:
                hook()
            except Exception as e:
                logger.error(f"关闭回调异常: {e}")
        self._modules.clear()
        logger.info("程序已关闭")
        sys.exit(0)

    def get_module(self, name: str) -> Optional[object]:
        """按名称获取已初始化的模块实例"""
        return self._modules.get(name)

    # ── 私有初始化方法 ────────────────────────────────────────

    def _init_config(self):
        from core.config_manager import ConfigManager
        # ConfigManager 是单例模式，__init__() 无参数，通过 load() 加载配置
        inst = ConfigManager()
        inst.load()
        self._modules["config"] = inst
        return inst

    def _init_event_bus(self):
        from core.event_bus import EventBus
        inst = EventBus()
        self._modules["event_bus"] = inst
        return inst

    def _init_monitor(self, config, event_bus):
        from core.monitor import Monitor
        inst = Monitor(config)  # Monitor 只接受 config
        self._modules["monitor"] = inst
        return inst

    def _init_state_manager(self, event_bus):
        from core.state_manager import state_manager
        # StateManager 是全局单例
        self._modules["state_manager"] = state_manager
        return state_manager

    def _init_connection(self, config, event_bus, state_manager):
        from device.connection import ConnectionManager
        inst = ConnectionManager(config)
        self._modules["connection"] = inst
        return inst

    def _init_recognizer(self, connection, config, monitor):
        from core.recognizer import Recognizer
        # Recognizer 需要 screenshot_func（由 connection 提供）
        inst = Recognizer(screenshot_func=connection.screenshot,
                          threshold=config.get("recognize.threshold", 0.8),
                          grayscale=config.get("recognize.grayscale", True))
        self._modules["recognizer"] = inst
        return inst

    def _init_anti_detect(self, config, monitor):
        from core.anti_detect import AntiDetect
        inst = AntiDetect(config.global_config if hasattr(config, 'global_config') else config)
        self._modules["anti_detect"] = inst
        return inst

    def _init_scheduler(self, config, state_manager, event_bus):
        from core.scheduler import Scheduler
        inst = Scheduler(config, state_manager)
        inst.load_state()
        self._modules["scheduler"] = inst
        return inst

    def _init_executor(self, recognizer, anti_detect, connection, monitor, config):
        from core.executor import Executor
        inst = Executor(recognizer, anti_detect, connection, monitor, config)
        self._modules["executor"] = inst
        return inst

    def _init_task_engine(self, config, event_bus, state_manager):
        from tasks.registry import TaskRegistry
        inst = TaskRegistry(config, event_bus, state_manager)
        inst.scan_and_register()
        self._modules["task_engine"] = inst
        return inst

    def _init_task_manager(self):
        from core.task_manager import TaskManager
        inst = TaskManager()
        inst.scan_all()
        self._modules["task_manager"] = inst
        return inst

    def _init_param_bridge(self, config, event_bus, state_manager, scheduler):
        from ui.param_bridge.ui_binding import UIBinding
        from ui.param_bridge.run_bridge import RunBridge
        from ui.param_bridge.task_bridge import TaskBridge
        binding = UIBinding(config, state_manager, scheduler)
        run_bridge = RunBridge()  # RunBridge 无参构造
        task_bridge = TaskBridge(config, scheduler, state_manager)
        self._modules["param_bridge"] = {
            "binding": binding,
            "run_bridge": run_bridge,
            "task_bridge": task_bridge,
        }
        return self._modules["param_bridge"]

    def _init_run_controller(self, scheduler, task_registry, connection,
                              config, state_manager, event_bus, monitor,
                              executor, recognizer, anti_detect):
        from core.run_controller import RunController
        inst = RunController(
            scheduler=scheduler,
            task_registry=task_registry,
            connection=connection,
            config=config,
            state_mgr=state_manager,
            executor=executor,
            recognizer=recognizer,
            anti_detect=anti_detect,
        )
        self._modules["run_controller"] = inst
        return inst

    def _init_account_manager(self, config, connection, state_manager, event_bus, scheduler):
        from core.account_manager import AccountManager
        inst = AccountManager(config, connection, state_manager, event_bus, scheduler)
        inst.load_accounts()
        self._modules["account_manager"] = inst
        return inst

    def _init_ui(self, param_bridge, event_bus, task_registry, task_manager):
        from ui.main_window import MainWindow
        # MainWindow 无参构造，内部自完成所有模块初始化
        inst = MainWindow()
        self._modules["ui"] = inst
        return inst

    def _get_dep(self, name: str, required: bool = True) -> Optional[object]:
        if name in self._modules:
            return self._modules[name]
        if required:
            raise RuntimeError(f"依赖模块 {name} 尚未初始化")
        return None

    def self_check(self) -> dict:
        """启动前自检：检查各模块就绪状态"""
        results = {}
        # 检查 ADB
        try:
            conn = self.get_module("connection")
            results["adb"] = conn.is_connected() if conn else False
        except Exception:
            results["adb"] = False
        # 检查素材完整性
        try:
            rec = self.get_module("recognizer")
            results["assets"] = len(rec.list_templates()) > 0 if rec else False
        except Exception:
            results["assets"] = False
        # 检查配置
        try:
            cfg = self.get_module("config")
            results["config"] = cfg.validate() == [] if cfg else False
        except Exception:
            results["config"] = False
        # 检查任务注册
        try:
            te = self.get_module("task_engine")
            results["tasks"] = len(te) > 0 if isinstance(te, dict) else False
        except Exception:
            results["tasks"] = False
        return results
