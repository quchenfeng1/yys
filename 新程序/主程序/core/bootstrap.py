"""
16-应用启动引导

ApplicationBootstrap 应用的入口与组装器（§5.1 单文件）。
对应设计书 §2/§3/§4/§5/§6。

7 层 15 步初始化顺序：
  L1: ConfigManager + EventBus
  L2: Monitor + StateManager
  L3: ConnectionManager + Recognizer + AntiDetect
  L4: Scheduler + Executor + TaskRegistry + TaskManager + ParamBridge
  L5: AccountManager
  L6: RunController
  L7: MainWindow
"""
from __future__ import annotations

import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from core.event_bus import EventBus, get_global_bus
from core.events import Events


class ApplicationBootstrap:
    """
    应用启动引导（§5.2 方法定义）。

    按 7 层 15 步顺序初始化所有模块 → self_check → 信号处理 → UI。
    关闭顺序与初始化相反，保证资源正确释放。
    """

    def __init__(self, root_dir: str | Path = "."):
        self._root = Path(root_dir).resolve()
        self._bus = get_global_bus()

        # 18-游戏解耦：当前游戏档案（默认 yys，可由 YYS_GAME 环境变量切换）
        import os
        from core.game_profile import GameProfile
        self._game = GameProfile(
            root=self._root,
            game_id=os.environ.get("YYS_GAME", "yys"),
        )
        self._game.ensure_dirs()

        # §2.1 模块实例字典
        self._components: dict[str, Any] = {}
        self._modules = self._components  # 说明书 §2.1 要求名

        # §2.3
        self._init_order: list[str] = []       # 初始化顺序列表
        self._shutdown_hooks: list[tuple[str, Any, str]] = []  # (name, instance, method_name)
        self._running = False

    # ═══════════════════════════════════════════════════════════
    #  §5.2 + §3.2 启动流程
    # ═══════════════════════════════════════════════════════════

    def start(self) -> bool:
        """
        启动入口（§3.2 + §5.2）。

        按 7 层 15 步顺序初始化 → self_check → 信号处理 → UI。
        """
        self._bus.publish(Events.BOOTSTRAP_STARTED)

        # §3.1 严格按依赖顺序初始化
        init_steps: list[tuple[str, Any]] = [
            # ── 第1层：基础设施 ────────────────────────────
            ("L1_config", self._init_config),
            ("L1_event_bus", self._init_event_bus),

            # ── 第2层：基础服务 ────────────────────────────
            ("L2_monitor", self._init_monitor),
            ("L2_state", self._init_state),

            # ── 第3层：核心功能 ────────────────────────────
            ("L3_connection", self._init_connection),
            ("L3_recognizer", self._init_recognizer),
            ("L3_anti_detect", self._init_anti_detect),

            # ── 第4层：业务编排 ────────────────────────────
            ("L4_scheduler", self._init_scheduler),
            ("L4_executor", self._init_executor),
            ("L4_task_registry", self._init_task_registry),
            ("L4_task_manager", self._init_task_manager),
            ("L4_bridge", self._init_bridge),

            # ── 第5层：账号管理 ────────────────────────────
            ("L5_account", self._init_account),

            # ── 第6层：运行控制 ────────────────────────────
            ("L6_run_controller", self._init_run_controller),

            # ── 第6.5层：可视化构建（17-可视化构建模块）──────
            ("L6_visual", self._init_visual),

            # ── 第7层：用户界面 ────────────────────────────
            ("L7_ui", self._init_ui),
        ]

        for name, init_fn in init_steps:
            self._bus.publish(Events.BOOTSTRAP_STEP, step=name)
            try:
                init_fn()
                self._init_order.append(name)
            except Exception as e:
                self._bus.publish(Events.BOOTSTRAP_ERROR, step=name, error=str(e))
                traceback.print_exc()
                return False

        # §3.2 启动自检
        check_result = self.self_check()
        self._bus.publish(Events.PREFLIGHT_COMPLETE, source="bootstrap",
                         result=check_result)

        # §3.2 注册信号处理
        self._register_signal_handlers()

        # 发布 app_started
        self._bus.publish(Events.APP_STARTED, source="bootstrap")

        self._running = True
        self._bus.publish(Events.BOOTSTRAP_COMPLETED)
        return True

    # ═══════════════════════════════════════════════════════════
    #  各层级初始化方法
    # ═══════════════════════════════════════════════════════════

    # ── 第1层：基础设施 ───────────────────────────────────

    def _init_config(self) -> None:
        """初始化配置管理中心（§3.2 L1-①）"""
        from core.config_manager import ConfigManager
        cfg = ConfigManager(
            config_dir=str(self._root / "config"),
            event_bus=self._bus,
            # 18-游戏解耦：tasks.yaml/coords 在游戏目录
            game_tasks_yaml=str(self._game.tasks_yaml),
            game_coords_dir=str(self._game.coords_dir),
        )
        cfg.load()
        self._store("config_manager", cfg)

        # 模拟器条目库（2026-08-16：模拟器管理菜单数据源）
        from core.emulator_store import EmulatorStore
        self._store("emulator_store",
                    EmulatorStore(config_dir=str(self._root / "config")))

    def _init_event_bus(self) -> None:
        """初始化事件通信总线（§3.2 L1-②）"""
        self._store("event_bus", self._bus)

    # ── 第2层：基础服务 ───────────────────────────────────

    def _init_monitor(self) -> None:
        """初始化日志监控中心（§3.2 L2-③）"""
        from core.monitor import Monitor
        cfg = self._get("config_manager")
        monitor = Monitor(
            event_bus=self._bus,
            config=cfg,
            connection=None,
            log_dir=str(self._root / "logs"),
            snapshot_dir=str(self._root / "logs/snapshots"),
        )
        self._store("monitor", monitor)

    def _init_state(self) -> None:
        """初始化运行时状态管理（§3.2 L2-④）"""
        from core.state_manager import StateManager
        sm = StateManager(event_bus=self._bus)
        sm.set_state("run_status", "stopped")
        self._store("state_manager", sm)
        self._add_shutdown_hook("state_manager", "reset")

        # Monitor 指标统计需要 StateManager（12-日志监控中心 → 07 注入）
        mon = self._get("monitor")
        if mon is not None and hasattr(mon, 'set_state_manager'):
            mon.set_state_manager(sm)

    # ── 第3层：核心功能 ───────────────────────────────────

    def _init_connection(self) -> None:
        """初始化设备连接模块（§3.2 L3-⑤）

        支持模拟设备模式：global.yaml 配置 device.mock=true 时，
        注入 MockADBClient（无真实模拟器也可运行），并立即建立连接。
        """
        from device.connection import ConnectionManager
        cfg = self._get("config_manager")
        state = self._get("state_manager")

        # 读取 device.mock 开关
        mock_enabled = False
        try:
            g = getattr(cfg, 'global_config', None)
            if g is not None and getattr(g, 'device', None) is not None:
                mock_enabled = bool(getattr(g.device, 'mock', False))
        except Exception:
            mock_enabled = False

        adb = None
        if mock_enabled:
            from device.mock_adb import MockADBClient
            adb = MockADBClient(assets_dir=str(self._game.assets_dir))
            mon = self._get("monitor")
            if mon and hasattr(mon, 'info'):
                mon.info("已启用模拟设备模式（无真实模拟器）", module="16-应用启动引导")
        else:
            # 真实设备：用平台检测的 ADB 路径（PATH 中可能无真 adb）
            from device.adb_client import ADBClient
            from device.emulator import EmulatorDetector
            adb_path = EmulatorDetector._find_adb()
            adb = ADBClient(adb_path=adb_path)
            mon = self._get("monitor")
            if mon and hasattr(mon, 'info'):
                mon.info(f"使用 ADB: {adb_path}", module="16-应用启动引导")

        conn = ConnectionManager(
            adb_client=adb,
            config=cfg,
            event_bus=self._bus,
            state_manager=state,
        )

        # 启动不自动连接设备（2026-08-16）：端口扫描会阻塞启动数秒，
        # 且界面已增设「连接模拟器」按钮 → 按需连接（RunBridge.connect_device）。
        mon = self._get("monitor")
        if mon and hasattr(mon, 'info'):
            mon.info("设备连接请使用顶部「连接模拟器」按钮（启动已跳过自动扫描）",
                     module="16-应用启动引导")

        self._store("connection", conn)
        self._add_shutdown_hook("connection", "disconnect")

    def _init_recognizer(self) -> None:
        """初始化图像识别模块（§3.2 L3-⑥）"""
        from core.recognizer import Recognizer
        from core.image_manager import ImageManager
        from core.ocr_locator import OcrLocator
        cfg = self._get("config_manager")

        # 先初始化 ImageManager
        img_mgr = ImageManager()
        asset_dir = self._game.assets_dir
        if asset_dir.exists():
            for subdir in sorted(asset_dir.iterdir()):
                if subdir.is_dir():
                    img_mgr.scan_directory(str(subdir), group=subdir.name)
        self._store("image_manager", img_mgr)

        # OCR 定位器（懒加载：首次识别时才初始化 paddle 引擎并下载模型）
        img_cfg = cfg.global_config.image
        ocr_locator = None
        if img_cfg.ocr_enabled:
            ocr_locator = OcrLocator(
                engine="paddle",
                lang=self._game.ocr_lang,
                use_gpu=img_cfg.ocr_use_gpu,
                timeout=img_cfg.ocr_timeout,
                event_bus=self._bus,
                connection=self._get("connection"),
            )
        self._store("ocr_locator", ocr_locator)

        recognizer = Recognizer(
            image_manager=img_mgr,
            event_bus=self._bus,
            ocr_locator=ocr_locator,
            connection=self._get("connection"),
            config=cfg,
            monitor=self._get("monitor"),
            threshold=cfg.global_config.image.template_threshold,
            asset_dir=str(self._game.assets_dir),
        )
        self._store("recognizer", recognizer)

    def _init_anti_detect(self) -> None:
        """初始化防封策略模块（§3.2 L3-⑦）

        anti_detect.enabled=false → 传零间隔/零抖动/零失败率 +
        enabled=False（debug 档案：零偏移/零走神/零漂移），开关真正生效。
        """
        from core.anti_detect import AntiDetect
        cfg = self._get("config_manager")
        g = cfg.global_config.anti_detect
        enabled = bool(getattr(g, 'enabled', True))
        ad = AntiDetect(
            event_bus=self._bus,
            monitor=self._get("monitor"),
            config=cfg,
            enabled=enabled,
            min_interval=g.min_interval if enabled else 0.0,
            max_interval=g.max_interval if enabled else 0.0,
            action_jitter=g.action_jitter if enabled else False,
            random_fail_rate=g.random_fail_rate if enabled else 0.0,
        )
        mon = self._get("monitor")
        if not enabled and mon is not None and hasattr(mon, 'info'):
            mon.info("防封策略已关闭（anti_detect.enabled=false）",
                     module="16-应用启动引导")
        self._store("anti_detect", ad)

    # ── 第4层：业务编排 ───────────────────────────────────

    def _init_scheduler(self) -> None:
        """初始化时间调度模块（§3.2 L4-⑧）"""
        from core.scheduler import Scheduler
        from core.task_state import TaskStateStore
        cfg = self._get("config_manager")
        state = self._get("state_manager")

        # 创建持久化存储（18-游戏解耦：runtime 在游戏目录）
        store = TaskStateStore(
            path=str(self._game.task_state_path),
        )

        sched = Scheduler(
            event_bus=self._bus,
            config=cfg,
            state_manager=state,
            store=store,
        )
        sched.load_tasks_from_config()
        sched.load_state()
        self._store("scheduler", sched)
        self._add_shutdown_hook("scheduler", "save_state")

    def _init_executor(self) -> None:
        """初始化执行器模块（§3.2 L4-⑨）"""
        from core.executor import Executor
        exec_ = Executor(
            recognizer=self._get("recognizer"),
            anti_detect=self._get("anti_detect"),
            connection=self._get("connection"),
            monitor=self._get("monitor"),
            config=self._get("config_manager"),
            event_bus=self._bus,
        )
        self._store("executor", exec_)

    def _init_task_registry(self) -> None:
        """初始化任务执行引擎（§3.2 L4-⑩）"""
        from tasks.registry import TaskRegistry
        registry = TaskRegistry(
            config=self._get("config_manager"),
            event_bus=self._bus,
            state_manager=self._get("state_manager"),
        )
        # 18-游戏解耦：扫描游戏任务包（games.{game_id}.tasks）
        registry.scan(package=self._game.task_package)

        # 17-可视化构建：注册可视化任务（games/{game}/visual_tasks/*.json）
        try:
            from visual import VisualTask, VisualTaskStore
            from visual.scene_store import SceneStore
            vstore = VisualTaskStore(self._game.visual_tasks_dir)
            scene_store = SceneStore([
                self._game.scenes_dir,
                self._game.shared_scenes_dir,
            ])
            self._store("scene_store", scene_store)
            # ── 信号体系（2026-08-16）：异常存储 + 全局任务存储 + 信号注册表 ──
            from core.anomaly_store import AnomalyStore
            from core.signal_registry import SignalRegistry
            from visual.global_task_store import GlobalTaskStore
            anomaly_store = AnomalyStore(self._game.runtime_dir / "anomalies.json")
            global_task_store = GlobalTaskStore(
                self._game.base / "global_task.json")
            signal_registry = SignalRegistry(
                self._game.runtime_dir,
                scene_store=scene_store, visual_store=vstore)
            self._store("anomaly_store", anomaly_store)
            self._store("global_task_store", global_task_store)
            self._store("signal_registry", signal_registry)
            for meta in vstore.list():
                try:
                    defn = vstore.load(meta["name"])
                except Exception:
                    continue
                cls = type(defn.get("name", meta["name"]), (VisualTask,), {
                    "task_id": defn.get("name", meta["name"]),
                    "category": defn.get("category", "daily"),
                    "_display_name": defn.get("display_name", "") or meta["name"],
                    "_definition": defn,
                    "_assets_dir": str(self._game.assets_dir),
                    "_runtime_dir": str(self._game.runtime_dir),
                    "_scene_store": scene_store,
                })
                registry.register(cls)
        except Exception:
            pass

        # 清理孤儿调度条目（2026-08-16）：任务文件（.py / 可视化 JSON）已删除，
        # 但 tasks.yaml 残留条目 → 任务队列仍会显示。启动时按「注册表 ∪ 可视化
        # 任务库」修剪：两者都不存在的条目移除（CONFIG_CHANGED → 调度器热重载）。
        try:
            cfg = self._get("config_manager")
            if cfg is not None and hasattr(cfg, "tasks_config") \
                    and hasattr(cfg, "remove_task"):
                tc = cfg.tasks_config
                if tc is not None and hasattr(tc, "tasks"):
                    valid = set()
                    try:
                        valid.update(registry.list_tasks().keys())
                    except Exception:
                        pass
                    try:
                        valid.update(m.get("name", "")
                                     for m in vstore.list())
                    except Exception:
                        pass
                    for raw in list(getattr(tc, "tasks", []) or []):
                        nm = getattr(raw, "name", "") or getattr(raw, "id", "")
                        if nm and nm not in valid:
                            try:
                                cfg.remove_task(nm)
                            except Exception:
                                pass
        except Exception:
            pass

        self._store("task_registry", registry)

    def _init_task_manager(self) -> None:
        """初始化任务文件管理（§3.2 L4-⑪）"""
        from core.task_manager import TaskManager
        tm = TaskManager(
            tasks_dir=str(self._game.tasks_dir),
            assets_dir=str(self._game.assets_dir),
        )
        tm.scan_all()
        self._store("task_manager", tm)

    def _init_bridge(self) -> None:
        """初始化参数桥接模块（§3.2 L4-⑫）"""
        from ui.param_bridge import ParamBridge
        bridge = ParamBridge(
            event_bus=self._bus,
            config=self._get("config_manager"),
            state_manager=self._get("state_manager"),
            scheduler=self._get("scheduler"),
            account_manager=self._get("account_manager", None),
            task_manager=self._get("task_manager"),
            run_controller=self._get("run_controller", None),
            registry=self._get("task_registry"),
            file_manager=self._get("task_manager"),
        )
        self._store("bridge", bridge)

    # ── 第5层：账号管理 ───────────────────────────────────

    def _init_account(self) -> None:
        """初始化账号管理模块（§3.2 L5-⑬）"""
        from core.account_manager import AccountManager
        am = AccountManager(
            config=self._get("config_manager"),
            connection=self._get("connection"),
            state_manager=self._get("state_manager"),
            event_bus=self._bus,
            scheduler=self._get("scheduler"),
            cookie_dir=str(self._root / "config/cookies"),
        )
        self._store("account_manager", am)

        # 回注入桥接：L4 创建 bridge 时 account_manager 尚未初始化，
        # 这里把真实实例注入 AccountBridge，否则账号 UI 功能空转
        bridge = self._get("bridge")
        if bridge is not None and hasattr(bridge, 'account') \
                and hasattr(bridge.account, 'set_manager'):
            bridge.account.set_manager(am)

    # ── 第6层：运行控制 ───────────────────────────────────

    def _init_run_controller(self) -> None:
        """初始化运行控制中心（§3.2 L6-⑭）"""
        from core.run_controller import RunController
        cfg = self._get("config_manager")
        state = self._get("state_manager")
        rc = RunController(
            scheduler=self._get("scheduler"),
            connection=self._get("connection"),
            config=cfg,
            state_mgr=state,
            registry=self._get("task_registry"),
            executor=self._get("executor"),
            recognizer=self._get("recognizer"),
            anti_detect=self._get("anti_detect"),
            event_bus=self._bus,
            monitor=self._get("monitor"),
            account_mgr=self._get("account_manager"),
            runtime_progress_path=str(self._game.task_runtime_progress_path),
        )
        self._store("run_controller", rc)
        self._add_shutdown_hook("run_controller", "stop")

        # 注入识图信号映射：旧 assets manifest + 新 SceneStore 场景信号
        # （素材库重构后 2026-08-16：触发器按信号名解析场景特征块模板路径）
        try:
            from core.asset_meta import AssetMetaStore
            merged = dict(AssetMetaStore(
                self._game.assets_dir).all_signals())
            ss = self._get("scene_store")
            if ss is not None and hasattr(ss, 'signal_map'):
                merged.update(ss.signal_map())
            rc.set_signal_map(merged)
            # 触发素材开关可在素材管理中修改 → 启动前动态刷新
            if ss is not None and hasattr(rc, 'set_scene_store'):
                rc.set_scene_store(ss)
        except Exception:
            pass

        # 把 RunController 注入 RunBridge（供 UI 查询当前任务/队列）
        bridge = self._get("bridge")
        if bridge and hasattr(bridge, 'run') and hasattr(bridge.run, 'set_controller'):
            try:
                bridge.run.set_controller(rc)
            except Exception:
                pass
        # 注入 ConnectionManager（连接/断开模拟器按钮，2026-08-16）
        if bridge and hasattr(bridge, 'run') and hasattr(bridge.run, 'set_connection'):
            try:
                bridge.run.set_connection(self._get("connection"))
            except Exception:
                pass

        # 注入 SystemBridge（游戏/模拟器切换 + 模拟器条目库，2026-08-16）
        sysb = getattr(bridge, 'system', None)
        if sysb is not None:
            try:
                sysb.set_game_switcher(self.switch_game)
                sysb.set_emulator_switcher(self.switch_emulator)
                sysb.set_emulator_store(self._get("emulator_store"))
                sysb.set_connection(self._get("connection"))
            except Exception:
                pass

    # ── 第6.5层：可视化构建（17-可视化构建模块）──────────────

    def _init_visual(self) -> None:
        """17-可视化构建：规则库 + 示教引擎 + 可视化桥（可选加载）"""
        try:
            from visual.rule_store import VisualTaskStore
            from visual.teach_engine import TeachEngine
            from visual.compound_store import CompoundStore
            from ui.param_bridge.visual_bridge import VisualBridge

            store = VisualTaskStore(self._game.visual_tasks_dir)
            # 通用节点库（2026-08-15）：跨游戏共享 + 游戏内
            compound_store = CompoundStore([
                self._game.shared_nodes_dir,
                self._game.nodes_dir,
            ])
            # 识别素材库（L4 已创建，这里复用）
            scene_store = self._get("scene_store")
            teach = TeachEngine(
                event_bus=self._bus,
                store=store,
                assets_dir=str(self._game.assets_dir),
                executor=self._get("executor"),
                recognizer=self._get("recognizer"),
                anti_detect=self._get("anti_detect"),
                monitor=self._get("monitor"),
                scene_store=scene_store,
            )
            vbridge = VisualBridge(
                event_bus=self._bus,
                store=store,
                teach_engine=teach,
                game_profile=self._game,
                registry=self._get("task_registry"),
                assets_dir=str(self._game.assets_dir),
                compound_store=compound_store,
                scene_store=scene_store,
                connection=self._get("connection"),
                run_controller=self._get("run_controller"),
                config=self._get("config_manager"),
                signal_registry=self._get("signal_registry"),
                anomaly_store=self._get("anomaly_store"),
                global_task_store=self._get("global_task_store"),
            )
            self._store("visual_store", store)
            self._store("compound_store", compound_store)
            self._store("scene_store", scene_store)
            self._store("teach_engine", teach)
            self._store("visual_bridge", vbridge)

            # ── 信号体系注入（2026-08-16）：异常/全局任务/判定参数 ──
            try:
                from visual.visual_task import VisualTask
                cfg = self._get("config_manager")
                anomaly_cfg = getattr(cfg.global_config, "anomaly", None)
                VisualTask._anomaly_store = self._get("anomaly_store")
                VisualTask._global_task_store = self._get("global_task_store")
                VisualTask._anomaly_count = int(
                    getattr(anomaly_cfg, "count", 5) or 5)
                VisualTask._anomaly_window = int(
                    getattr(anomaly_cfg, "window", 30) or 30)
                # 暂停注册（暂停由节点返回 paused 快照留存，此处仅占位）
                VisualTask._on_wait_cb = \
                    (lambda tid, sig, sec, nid: None)
                # 调度器分支：运行期走到调度器节点时执行对应操作
                rc = self._get("run_controller")
                if rc is not None and hasattr(rc, "_scheduler_op_from_task"):
                    VisualTask._scheduler_op_cb = rc._scheduler_op_from_task
            except Exception:
                pass

            # 互斥：把测试运行状态检查器注入 RunBridge（测试运行中禁止正式启动）
            bridge = self._get("bridge")
            if bridge is not None and hasattr(bridge, 'run') \
                    and hasattr(bridge.run, 'set_teach_running_checker'):
                bridge.run.set_teach_running_checker(lambda: teach.is_running)
        except Exception:
            pass  # 可视化构建为可选能力，初始化失败不阻断启动

    # ═══════════════════════════════════════════════════════════
    #  游戏 / 模拟器切换（2026-08-16 B方案）
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _switching_blocked(rc: Any, teach: Any) -> bool:
        """脚本/示教运行中禁止切换。"""
        try:
            if rc is not None and (getattr(rc, 'is_running', False)
                                   or getattr(rc, 'is_paused', False)):
                return True
        except Exception:
            pass
        try:
            if teach is not None and getattr(teach, 'is_running', False):
                return True
        except Exception:
            pass
        return False

    def switch_emulator(self, emu_id: str) -> bool:
        """切换模拟器：断开旧设备 → 连接条目对应 serial。

        仅脚本未运行时允许（UI 层已拦截，这里兜底）。
        """
        if self._switching_blocked(self._get("run_controller"),
                                   self._get("teach_engine")):
            return False
        store = self._get("emulator_store")
        entry = store.get(emu_id) if store is not None else None
        if not entry:
            return False
        serial = f"{entry.get('host', '127.0.0.1')}:{entry.get('port', 0)}"
        conn = self._get("connection")
        mon = self._get("monitor")

        # 模拟设备模式：无需真实连接
        mock = False
        try:
            g = getattr(self._get("config_manager"), 'global_config', None)
            if g is not None and getattr(g, 'device', None) is not None:
                mock = bool(getattr(g.device, 'mock', False))
        except Exception:
            pass
        if mock:
            if mon and hasattr(mon, 'info'):
                mon.info(f"模拟设备模式：模拟器选择已切换为 {serial}",
                         module="16-应用启动引导")
            self._bus.publish(Events.EMULATOR_SWITCHED, source="bootstrap",
                              emulator_id=emu_id, serial=serial)
            return True

        if conn is None:
            return False
        try:
            try:
                conn.disconnect()
            except Exception:
                pass
            ok = bool(conn.connect(serial=serial))
        except Exception:
            ok = False
        if ok:
            if mon and hasattr(mon, 'info'):
                mon.info(f"已切换模拟器: {serial}", module="16-应用启动引导")
            self._bus.publish(Events.EMULATOR_SWITCHED, source="bootstrap",
                              emulator_id=emu_id, serial=serial)
        return ok

    def _register_visual_tasks(self, registry: Any,
                               game: Any) -> tuple[Any, Any]:
        """注册某游戏的可视化任务 + 场景素材库 → (vstore, scene_store)。"""
        from visual import VisualTask, VisualTaskStore
        from visual.scene_store import SceneStore
        vstore = VisualTaskStore(game.visual_tasks_dir)
        scene_store = SceneStore([
            game.scenes_dir,
            game.shared_scenes_dir,
        ])
        for meta in vstore.list():
            try:
                defn = vstore.load(meta["name"])
            except Exception:
                continue
            cls = type(defn.get("name", meta["name"]), (VisualTask,), {
                "task_id": defn.get("name", meta["name"]),
                "category": defn.get("category", "daily"),
                "_display_name": defn.get("display_name", "") or meta["name"],
                "_definition": defn,
                "_assets_dir": str(game.assets_dir),
                "_runtime_dir": str(game.runtime_dir),
                "_scene_store": scene_store,
            })
            registry.register(cls)
        return vstore, scene_store

    def switch_game(self, game_id: str) -> bool:
        """B方案（2026-08-16）：后端整体切换到新游戏。

        重建范围：配置中心游戏路径 → 调度器（状态存储）→ 任务注册表 →
        任务文件管理 → 素材管理/OCR/识别器 → 可视化任务库/场景库/通用节点
        → 示教引擎 → 可视化桥 → 运行控制（进度路径/信号映射/场景库）。

        各游戏有独立 runtime 目录 → 切换即加载该游戏自己的
        任务列表/队列/进度（类似数据库按 game_id 取数）。
        返回 False 且不改动任何状态的情况：脚本运行中 / 游戏不存在。
        """
        if game_id == self._game.game_id:
            return True
        rc = self._get("run_controller")
        teach = self._get("teach_engine")
        if self._switching_blocked(rc, teach):
            return False

        # 目标游戏必须有效（scan_games 判定）
        from core.game_profile import GameProfile, scan_games
        new_game = GameProfile(root=self._root, game_id=game_id)
        valid = {g.game_id for g in scan_games(self._root)}
        if game_id not in valid and not (
                new_game.profile_yaml.exists()
                or new_game.tasks_dir.exists()):
            return False

        mon = self._get("monitor")
        try:
            # 1. 停触发监控 + 保存旧游戏调度状态
            if rc is not None and hasattr(rc, 'stop_trigger_watcher'):
                rc.stop_trigger_watcher()
            sched = self._get("scheduler")
            if sched is not None and hasattr(sched, 'save_state'):
                sched.save_state()

            # 2. 切换游戏档案
            new_game.ensure_dirs()
            self._game = new_game

            # 3. 配置中心：游戏级路径（tasks.yaml / coords）
            cfg = self._get("config_manager")
            if cfg is not None and hasattr(cfg, 'switch_game'):
                cfg.switch_game(str(new_game.tasks_yaml),
                                str(new_game.coords_dir))

            # 4. 调度器：换持久化状态存储并整体重载
            if sched is not None and hasattr(sched, 'switch_state_store'):
                from core.task_state import TaskStateStore
                sched.switch_state_store(
                    TaskStateStore(path=str(new_game.task_state_path)))

            # 5. 任务注册表：清空 → 扫新游戏任务包 → 注册可视化任务
            registry = self._get("task_registry")
            if registry is not None and hasattr(registry, 'reset'):
                registry.reset()
                registry.scan(package=new_game.task_package)
            vstore = scene_store = None
            if registry is not None:
                vstore, scene_store = self._register_visual_tasks(
                    registry, new_game)
                self._store("visual_store", vstore)
                self._store("scene_store", scene_store)

            # ── 信号体系随游戏重建（2026-08-16）──
            try:
                from core.anomaly_store import AnomalyStore
                from core.signal_registry import SignalRegistry
                from visual.global_task_store import GlobalTaskStore
                anomaly_store = AnomalyStore(
                    new_game.runtime_dir / "anomalies.json")
                global_task_store = GlobalTaskStore(
                    new_game.base / "global_task.json")
                signal_registry = SignalRegistry(
                    new_game.runtime_dir,
                    scene_store=scene_store, visual_store=vstore)
                self._store("anomaly_store", anomaly_store)
                self._store("global_task_store", global_task_store)
                self._store("signal_registry", signal_registry)
                from visual.visual_task import VisualTask
                VisualTask._anomaly_store = anomaly_store
                VisualTask._global_task_store = global_task_store
                rc = self._get("run_controller")
                if rc is not None and hasattr(rc, "_rebuild_trigger_index"):
                    rc._rebuild_trigger_index()
            except Exception:
                pass

            # 6. 任务文件管理：新游戏任务目录
            tm = self._get("task_manager")
            if tm is not None and hasattr(tm, 'switch_game'):
                tm.switch_game(str(new_game.tasks_dir),
                               str(new_game.assets_dir))

            # 7. 素材管理 + OCR + 识别器（按新游戏素材/语言重建）
            from core.image_manager import ImageManager
            from core.ocr_locator import OcrLocator
            img_mgr = ImageManager()
            if new_game.assets_dir.exists():
                for subdir in sorted(new_game.assets_dir.iterdir()):
                    if subdir.is_dir():
                        img_mgr.scan_directory(str(subdir), group=subdir.name)
            self._store("image_manager", img_mgr)
            ocr_locator = None
            try:
                img_cfg = cfg.global_config.image
                if img_cfg.ocr_enabled:
                    ocr_locator = OcrLocator(
                        engine="paddle",
                        lang=new_game.ocr_lang,
                        use_gpu=img_cfg.ocr_use_gpu,
                        timeout=img_cfg.ocr_timeout,
                        event_bus=self._bus,
                        connection=self._get("connection"),
                    )
            except Exception:
                ocr_locator = None
            self._store("ocr_locator", ocr_locator)
            recognizer = self._get("recognizer")
            if recognizer is not None and hasattr(recognizer, 'switch_game'):
                recognizer.switch_game(img_mgr, ocr_locator,
                                       str(new_game.assets_dir))

            # 8. 通用节点库
            from visual.compound_store import CompoundStore
            compound_store = CompoundStore([
                new_game.shared_nodes_dir,
                new_game.nodes_dir,
            ])
            self._store("compound_store", compound_store)

            # 9. 示教引擎 + 可视化桥（引用整体换新）
            if teach is not None and hasattr(teach, 'switch_game'):
                teach.switch_game(vstore, str(new_game.assets_dir),
                                  scene_store)
            vbridge = self._get("visual_bridge")
            if vbridge is not None and hasattr(vbridge, 'switch_game'):
                vbridge.switch_game(new_game, vstore, compound_store,
                                    scene_store, teach,
                                    signal_registry=self._get("signal_registry"),
                                    anomaly_store=self._get("anomaly_store"),
                                    global_task_store=self._get("global_task_store"))

            # 10. 运行控制：进度路径 + 触发信号映射 + 场景库
            if rc is not None and hasattr(rc, 'switch_game'):
                merged = {}
                try:
                    from core.asset_meta import AssetMetaStore
                    merged.update(AssetMetaStore(
                        new_game.assets_dir).all_signals())
                except Exception:
                    pass
                if scene_store is not None and hasattr(scene_store, 'signal_map'):
                    merged.update(scene_store.signal_map())
                rc.switch_game(str(new_game.task_runtime_progress_path),
                               merged, scene_store)
        except Exception:
            traceback.print_exc()
            if mon and hasattr(mon, 'error'):
                mon.error(f"切换游戏失败: {game_id}", module="16-应用启动引导")
            return False

        if mon and hasattr(mon, 'info'):
            mon.info(f"已切换游戏: {new_game.display_name}（{game_id}）",
                     module="16-应用启动引导")
        self._bus.publish(Events.GAME_SWITCHED, source="bootstrap",
                          game_id=game_id)
        return True

    # ── 第7层：用户界面 ───────────────────────────────────

    def _init_ui(self) -> None:
        """初始化用户界面模块（§3.2 L7-⑮）"""
        from ui.main_window import MainWindow
        from core.image_manager import ImageManager
        img_mgr = self._get("image_manager")
        # MainWindow.__init__ 内部已调用 init_ui()，此处不重复调用
        window = MainWindow(
            param_bridge=self._get("bridge"),
            event_bus=self._bus,
            image_mgr=img_mgr,
            visual_bridge=self._get("visual_bridge"),
        )
        window.refresh_task_list()
        self._store("main_window", window)

    # ═══════════════════════════════════════════════════════════
    #  §5.2 + §3.2 自检
    # ═══════════════════════════════════════════════════════════

    def self_check(self) -> dict[str, Any]:
        """
        启动前自检（§3.2 + §5.2）。

        Returns:
            {检查项: 结果} 字典。

        失败策略：
        - 配置不合法 → 告警但继续
        - ADB 不通 → 告警但继续
        - 素材缺失 → 发布 assets_missing 事件
        - 依赖不完整 → 弹窗后退出
        """
        result: dict[str, Any] = {
            "config_valid": True,
            "adb_connectivity": False,
            "assets_complete": True,
            "dependencies_complete": True,
        }

        # 配置合法性
        cfg = self._get("config_manager")
        if cfg and hasattr(cfg, 'validate'):
            try:
                errors = cfg.validate()
                if errors:
                    result["config_valid"] = False
                    result["config_errors"] = errors
            except Exception:
                result["config_valid"] = False

        # ADB 连通性
        conn = self._get("connection")
        if conn and hasattr(conn, 'is_connected'):
            try:
                result["adb_connectivity"] = conn.is_connected()
            except Exception:
                pass

        # 素材完整性
        tm = self._get("task_manager")
        if tm and hasattr(tm, 'find_missing_assets'):
            try:
                missing = tm.find_missing_assets()
                if missing:
                    result["assets_complete"] = False
                    result["missing_assets"] = missing
                    self._bus.publish(Events.ASSETS_MISSING, source="bootstrap",
                                     missing=missing)
            except Exception:
                pass

        # 依赖完整性
        required = ["config_manager", "event_bus", "monitor", "state_manager",
                    "recognizer", "anti_detect", "scheduler", "executor",
                    "task_registry", "task_manager", "run_controller"]
        missing_deps = [n for n in required if n not in self._components]
        if missing_deps:
            result["dependencies_complete"] = False
            result["missing_dependencies"] = missing_deps

        return result

    # ═══════════════════════════════════════════════════════════
    #  §3.2 + §5.2 信号处理
    # ═══════════════════════════════════════════════════════════

    def _register_signal_handlers(self) -> None:
        """注册 SIGINT/SIGTERM 信号处理器（§3.2 + §5.2）"""
        def _signal_handler(signum: int, frame: Any) -> None:
            self._bus.publish(Events.APP_STOPPING, source="bootstrap",
                             signal=signum)
            self.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, _signal_handler)

    # ═══════════════════════════════════════════════════════════
    #  §3.3 + §5.2 关闭流程
    # ═══════════════════════════════════════════════════════════

    def shutdown(self) -> None:
        """
        优雅关闭（§3.3 + §5.2）。

        顺序与初始化相反：
        停止运行控制 → 保存调度状态 → 清理任务 → 断开设备 → 停止热重载
        → 停止事件总线 → 关闭日志 → 清空模块字典
        """
        self._bus.publish(Events.APP_STOPPING, source="bootstrap")

        # 1. 执行关闭钩子（倒序：run_controller.stop → scheduler.save_state
        #    → connection.disconnect → state_manager.reset）
        #    相比硬编码步骤的优势：依赖 _add_shutdown_hook 注册顺序自动推导，
        #    运行控制最先停止，状态最后重置，且不重复执行。
        for name, instance, method in reversed(self._shutdown_hooks):
            if instance and hasattr(instance, method):
                try:
                    getattr(instance, method)()
                except Exception:
                    pass

        # 2. 清理任务执行引擎上下文（§3.3 step 3）
        registry = self._get("task_registry")
        if registry and hasattr(registry, '_registry'):
            try:
                registry._registry.clear()
                if hasattr(registry, '_categories'):
                    registry._categories.clear()
                registry._scanned = False
            except Exception:
                pass

        # 3. 清空任务文件缓存（§3.3 step 5）
        tm = self._get("task_manager")
        if tm and hasattr(tm, '_cache'):
            try:
                tm._cache.clear()
            except Exception:
                pass

        # 4. 停止调度模块的监听器
        sched = self._get("scheduler")
        if sched and hasattr(sched, 'stop_watcher'):
            try:
                sched.stop_watcher()
            except Exception:
                pass

        # 5. 停止配置热重载
        cfg = self._get("config_manager")
        if cfg and hasattr(cfg, 'stop_watcher'):
            try:
                cfg.stop_watcher()
            except Exception:
                pass

        # 6. 关闭日志
        monitor = self._get("monitor")
        if monitor and hasattr(monitor, 'close'):
            try:
                monitor.close()
            except Exception:
                pass

        # 7. 停止事件总线
        if hasattr(self._bus, 'stop'):
            try:
                self._bus.stop()
            except Exception:
                pass

        # 8. 清空模块字典
        self._components.clear()
        self._running = False

    # ═══════════════════════════════════════════════════════════
    #  工具
    # ═══════════════════════════════════════════════════════════

    def _store(self, name: str, instance: Any) -> None:
        """存储组件实例"""
        self._components[name] = instance

    def _add_shutdown_hook(self, name: str, method: str = "close") -> None:
        """注册关闭钩子"""
        instance = self._components.get(name)
        if instance and hasattr(instance, method):
            self._shutdown_hooks.append((name, instance, method))

    def _get(self, name: str, default: Any = None) -> Any:
        """获取已初始化的组件"""
        return self._components.get(name, default)

    def get(self, name: str) -> Any:
        """公开的组件查询接口（§5.2）"""
        return self._components.get(name)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def modules(self) -> dict[str, Any]:
        """所有已初始化模块的单例字典（§2.2）"""
        return dict(self._components)

    @property
    def components(self) -> dict[str, Any]:
        return dict(self._components)
