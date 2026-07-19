"""
脚本工作线程模块

职责：在后台线程中执行脚本逻辑，通过 Qt 信号将日志、状态、进度传递到主界面。

执行流程（8步）：
  Step1 加载配置
  Step2 连接模拟器（含自动启动模拟器）
  Step3 读取模拟器分辨率（只读，绝不修改模拟器设置）
  Step4 启动阴阳师 App（优先执行，不依赖识图）★
  Step5 加载素材图片（从「所需图片」暂存区归入 assets/ 四层目录）
  Step6 初始化核心模块（识别器/防封号/执行器）
  Step7 检查图片素材（无强制必需图，仅统计提示）
  Step8 执行登录流程（OCR识别"进入游戏"位置 → 循环点击直到进入主界面）

素材目录结构（assets/ 四层分类）：
  common/   公共素材（battle/ui/nav）
  scenes/   场景标志图（login/courtyard/town/explore）
  tasks/    任务专属素材（daily/permanent/event/special）
  teams/    阵容御魂预设

信号：
- log_signal(str): 日志消息
- status_signal(str): 状态变更（待机/运行中/成功/失败）
- progress_signal(str): 当前进度描述
- finished_signal(bool, str): 执行完成（成功/失败, 消息）
"""

import sys
import time
import shutil
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal, QMutex

from core.config_manager import ConfigManager
from core.logger import get_logger, setup_logger
from core.exceptions import ScriptError, DeviceConnectError
from core.anti_detect import AntiDetect
from core.recognizer import Recognizer
from core.executor import Executor
from core.scheduler import Scheduler
from core.state_manager import state_manager
from core.event_bus import event_bus, Events
from device.adb_client import ADBClient
from device.emulator import EmulatorManager
from tasks.login_flow import LoginFlow

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent  # d:\yys

# 登录流程所需图片清单（已放弃6张必传图，改为OCR识别进入游戏位置循环点击）
# 此列表保留用于将来可选的识图增强，不再强制检查
REQUIRED_IMAGES = []

# 图片名到目标子目录的映射（新四层结构）
# 用户将截图放入「所需图片」后，脚本按此映射归入 assets/ 对应目录
IMAGE_MAP = {
    # 场景标志图
    "splash_skip.png": "scenes/login",
    "health_notice_confirm.png": "scenes/login",
    "announcement_close.png": "scenes/login",
    "select_server.png": "scenes/login",
    "enter_game.png": "scenes/login",
    "courtyard_main.png": "scenes/courtyard",
    # 通用战斗素材
    "challenge_btn.png": "common/battle",
    "confirm_btn.png": "common/battle",
    "victory.png": "common/battle",
    "defeat.png": "common/battle",
    # 通用UI元素
    "close_btn.png": "common/ui",
    "back_btn.png": "common/ui",
}


class ScriptWorker(QThread):
    """脚本执行工作线程"""

    # 信号定义
    log_signal = pyqtSignal(str)          # 日志消息
    status_signal = pyqtSignal(str)       # 状态: "idle" / "running" / "success" / "error"
    progress_signal = pyqtSignal(str)     # 进度描述
    finished_signal = pyqtSignal(bool, str)  # 完成: (成功?, 消息)

    def __init__(self, emulator_type: str = "ldplayer",
                 adb_port: int = 5555,
                 emulator_path: str = "",
                 auto_launch: bool = True,
                 scheduler=None,
                 parent=None):
        """
        Args:
            emulator_type: 模拟器类型 ldplayer / mumu / nox
            adb_port: ADB 端口
            emulator_path: 自定义模拟器路径
            auto_launch: 是否自动启动模拟器
            scheduler: 可选，复用已有的 Scheduler 实例
        """
        super().__init__(parent)
        self.emulator_type = emulator_type
        self.adb_port = adb_port
        self.emulator_path = emulator_path
        self.auto_launch = auto_launch
        self._external_scheduler = scheduler  # 外部注入的调度器

        self._stop_flag = False
        self._mutex = QMutex()

        # 运行时组件
        self.config: Optional[ConfigManager] = None
        self.adb: Optional[ADBClient] = None
        self.recognizer: Optional[Recognizer] = None
        self.executor: Optional[Executor] = None
        self.login_flow: Optional[LoginFlow] = None

    def stop(self):
        """请求停止执行"""
        self._mutex.lock()
        self._stop_flag = True
        self._mutex.unlock()
        self.log("收到停止请求，正在终止...")
        if self.login_flow:
            self.log("(当前步骤完成后将停止)")

    def is_stopped(self) -> bool:
        """检查是否被请求停止"""
        self._mutex.lock()
        val = self._stop_flag
        self._mutex.unlock()
        return val

    def log(self, msg: str, level: str = "INFO"):
        """发送日志到主界面"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_signal.emit(f"[{timestamp}] [{level}] {msg}")

    def run(self):
        """线程主函数：执行完整脚本流程"""
        try:
            self.status_signal.emit("running")
            self._execute()
        except KeyboardInterrupt:
            self.log("用户中断", "WARN")
            self.status_signal.emit("idle")
            self.finished_signal.emit(False, "用户中断")
        except Exception as e:
            self.log(f"脚本异常: {e}", "ERROR")
            self.status_signal.emit("error")
            self.finished_signal.emit(False, f"脚本异常: {e}")

    def _execute(self):
        """执行脚本流程"""
        # ===== Step 1: 加载配置 =====
        self.progress_signal.emit("正在加载配置...")
        self.log("加载配置...")
        self.config = ConfigManager()

        log_level = self.config.get("run.log_level", "INFO")
        setup_logger(log_level)
        logger = get_logger("worker")
        logger.info("脚本工作线程启动")

        # 初始化调度器并发布日程表（复用已有实例或新建）
        if self._external_scheduler:
            self.scheduler = self._external_scheduler
            self.scheduler.load_tasks_from_config()
            self.scheduler.load_state()
        else:
            self.scheduler = Scheduler(self.config, state_manager)
            self.scheduler.load_tasks_from_config()
            self.scheduler.load_state()
        self.scheduler.build_schedule()  # 发布 SCHEDULE_UPDATED 事件

        if self.is_stopped():
            self._stop_and_exit()
            return

        # ===== Step 2: 连接模拟器 =====
        self.progress_signal.emit("连接模拟器...")
        self.log(f"连接模拟器 (类型={self.emulator_type}, 端口={self.adb_port})...")

        adb_path = self.config.get("adb.path", "adb")
        self.adb = ADBClient(
            device_id=f"127.0.0.1:{self.adb_port}",
            adb_path=adb_path
        )

        # 使用 EmulatorManager 确保模拟器就绪
        emu_manager = EmulatorManager(
            emulator_type=self.emulator_type,
            custom_path=self.emulator_path
        )

        if self.auto_launch:
            ready = emu_manager.ensure_running(self.adb, port=self.adb_port, timeout=90,
                                               stop_check=self.is_stopped)
            if not ready:
                self.log("模拟器未就绪，请手动启动模拟器后重试", "ERROR")
                self.status_signal.emit("error")
                self.finished_signal.emit(False, "模拟器连接失败")
                return
        else:
            # 不自动启动，直接尝试连接
            try:
                self.adb.connect()
            except DeviceConnectError as e:
                self.log(f"模拟器连接失败: {e}", "ERROR")
                self.log("请手动启动模拟器，或在设置中开启自动启动", "WARN")
                self.status_signal.emit("error")
                self.finished_signal.emit(False, "模拟器连接失败")
                return

        self.log("模拟器连接成功!")

        if self.is_stopped():
            self._stop_and_exit()
            return

        # ===== Step 3: 读取模拟器分辨率（只读，绝不修改模拟器设置） =====
        self.progress_signal.emit("读取模拟器分辨率...")
        cur_w, cur_h = self.adb.get_screen_size()
        self.log(f"模拟器当前分辨率: {cur_w}x{cur_h}")
        expect_w = self.config.get("screen.width", 1280)
        expect_h = self.config.get("screen.height", 720)
        # 宽高集合相同即视为匹配（部分模拟器如 MuMu 的 wm size 报告方向与显示方向相反）
        if {cur_w, cur_h} != {expect_w, expect_h}:
            self.log(
                f"当前分辨率 {cur_w}x{cur_h} 与脚本期望 {expect_w}x{expect_h} 不一致，"
                f"请在模拟器自身的设置中调整为 {expect_w}x{expect_h}（脚本不会自动修改模拟器设置）",
                "WARN"
            )
        else:
            self.log(f"分辨率匹配（期望 {expect_w}x{expect_h}）")

        if self.is_stopped():
            self._stop_and_exit()
            return

        # ===== Step 4: 启动阴阳师 App（优先执行，不依赖识图） =====
        self.progress_signal.emit("启动阴阳师...")
        app_package = self.config.get("app.package", "com.netease.onmyoji.wyzymnqsd_cps")
        app_activity = self.config.get("app.activity", "com.netease.onmyoji.Launcher")
        self.log(f"启动阴阳师 App: {app_package}")
        launched = self.adb.launch_app(app_package, app_activity)
        if not launched:
            self.log("阴阳师启动失败，请检查 App 是否已安装", "ERROR")
            self.status_signal.emit("error")
            self.finished_signal.emit(False, "阴阳师 App 启动失败")
            return
        self.log("阴阳师已启动!")

        if self.is_stopped():
            self._stop_and_exit()
            return

        # ===== Step 5: 加载素材图片 =====
        self.progress_signal.emit("检查素材图片...")
        self.log("检查素材图片...")
        loaded = self._load_images()
        self.log(f"素材加载完成，共 {loaded} 张")

        if self.is_stopped():
            self._stop_and_exit()
            return

        # ===== Step 6: 初始化核心模块 =====
        self.progress_signal.emit("初始化核心模块...")
        self.log("初始化识别器、防封号引擎、执行器...")

        threshold = self.config.get("recognize.threshold", 0.8)
        grayscale = self.config.get("recognize.grayscale", True)

        self.recognizer = Recognizer(
            screenshot_func=self.adb.screenshot,
            threshold=threshold,
            grayscale=grayscale
        )

        anti_detect = AntiDetect(self.config.global_config)
        self.executor = Executor(self.adb, self.recognizer, anti_detect)
        self.log("核心模块初始化完成")

        if self.is_stopped():
            self._stop_and_exit()
            return

        # ===== Step 7: 检查图片素材 =====
        self.progress_signal.emit("检查图片素材...")
        missing = self._check_images()
        if missing:
            self.log(f"缺少 {len(missing)} 张图片素材:", "WARN")
            for img_name, desc in missing:
                self.log(f"  - {img_name} ({desc})", "WARN")
            self.log("阴阳师已启动，但缺少识图素材无法继续登录流程", "WARN")
            self.log("请将截图放入「所需图片」文件夹后重新运行", "WARN")
            self.status_signal.emit("error")
            self.finished_signal.emit(False, f"阴阳师已启动，但缺少 {len(missing)} 张图片素材")
            return

        self.log("所有图片素材就绪!")

        if self.is_stopped():
            self._stop_and_exit()
            return

        # ===== Step 8: 执行登录流程 =====
        self.progress_signal.emit("启动登录流程...")
        self.log("=" * 40)
        self.log("开始登录流程（识图）")
        self.log("=" * 40)

        login_config = self.config.get_coords("login")
        self.login_flow = LoginFlow(
            executor=self.executor,
            recognizer=self.recognizer,
            config=login_config,
            adb_client=self.adb,
            app_package=app_package,
            app_activity=app_activity
        )

        success = self.login_flow.execute()

        if success:
            self.log("=" * 40)
            self.log("登录成功! 已进入庭院主界面 — 开始调度循环")
            self.log("=" * 40)
            self._run_schedule_loop()
        else:
            self.log("登录失败，请检查日志和截图", "ERROR")
            self.status_signal.emit("error")
            self.finished_signal.emit(False, "登录失败")

    # ==================== 调度循环（v2.7 持续运行） ====================

    def _run_schedule_loop(self):
        """持续调度循环：Scheduler 驱动，不断检查并执行到期任务。"""
        import importlib, inspect
        from tasks.base.task_context import TaskContext
        from tasks.base.task_step import TaskStep

        idle_sleep = 5  # 无任务时休眠秒数
        _consecutive_errors = 0  # 连续错误计数器

        while not self.is_stopped():
            try:
                # 1. 刷新日程表并发布到 UI
                schedule = self.scheduler.build_schedule()
                if schedule:
                    names = [s["name"] for s in schedule[:5]]
                    self.log(f"日程表: {' → '.join(names)}")

                # 2. 获取下一个到期任务
                task_name = self.scheduler.get_next_task()
                if not task_name:
                    time.sleep(idle_sleep)
                    continue

                if self.is_stopped():
                    break

                # 3. 执行任务
                self.log(f"▶ 开始执行任务: {task_name}")
                self.progress_signal.emit(f"执行中: {task_name}")
                event_bus.publish(Events.TASK_STARTED, task_name=task_name)

                success = False
                try:
                    # 查找并导入任务模块
                    task_cls = None
                    for cat in ["daily", "permanent", "special", "event"]:
                        fpath = PROJECT_ROOT / "tasks" / cat / f"{task_name}.py"
                        if fpath.exists():
                            mod = importlib.import_module(f"tasks.{cat}.{task_name}")
                            for _, obj in inspect.getmembers(mod, inspect.isclass):
                                if (issubclass(obj, TaskStep) and
                                        obj is not TaskStep and
                                        getattr(obj, 'is_generic', True) is False):
                                    task_cls = obj
                                    break
                            break

                    if task_cls:
                        ctx = TaskContext(
                            task_name=task_name,
                            task_config=self.config.get_task_config(task_name),
                            executor=self.executor,
                            recognizer=self.recognizer,
                            connection=None,
                            log=self.log,
                        )
                        step = task_cls()
                        result = step.execute(ctx)
                        success = (result.status == "success")
                        self.log(f"  结果: {result.status} — {result.message}")
                    else:
                        self.log(f"  错误: 未找到任务类 {task_name}", "ERROR")

                except Exception as e:
                    self.log(f"  任务异常: {e}", "ERROR")

                # 4. 标记完成（失败自动冷却，防止无限重试）
                self.scheduler.mark_done(task_name, success=success)
                event_bus.publish(Events.TASK_DONE, task_name=task_name, success=success)
                self.progress_signal.emit("就绪")
                _consecutive_errors = 0

            except Exception as e:
                _consecutive_errors += 1
                self.log(f"调度循环异常: {e}", "ERROR")
                if _consecutive_errors > 10:
                    self.log("连续异常过多，停止调度循环", "ERROR")
                    break
                time.sleep(3)  # 短暂休眠后重试

    def _load_images(self) -> int:
        """从「所需图片」文件夹加载图片到 assets/ 对应目录

        Returns:
            加载的图片数量
        """
        source_dir = PROJECT_ROOT / "所需图片"
        if not source_dir.exists():
            self.log("「所需图片」文件夹不存在", "WARN")
            return 0

        moved = 0
        for img_file in source_dir.iterdir():
            if img_file.is_file() and img_file.suffix.lower() == ".png":
                target_dir = IMAGE_MAP.get(img_file.name)
                if target_dir:
                    target_path = PROJECT_ROOT / "assets" / target_dir / img_file.name
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(img_file), str(target_path))
                    self.log(f"  加载素材: {img_file.name} -> assets/{target_dir}/")
                    moved += 1
                else:
                    # 未知图片名，尝试按文件名前缀归类
                    self.log(f"  未知图片: {img_file.name} (跳过)", "WARN")

        return moved

    def _check_images(self) -> list:
        """检查必需图片是否齐全

        Returns:
            缺失的图片列表 [(name, desc), ...]
        """
        missing = []
        for img_name, desc in REQUIRED_IMAGES:
            if not self.recognizer.has_template(img_name):
                missing.append((img_name, desc))
        return missing

    def _stop_and_exit(self):
        """停止并退出"""
        self.log("脚本已停止")
        self.status_signal.emit("idle")
        self.finished_signal.emit(False, "用户手动停止")
