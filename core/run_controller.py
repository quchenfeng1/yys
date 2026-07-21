"""
09-运行控制中心（Run Control Center）v3.0

程序运行生命周期管理：
  - 三线程模型：填充(filler) + 执行(executor) + 扫描(scanner)
  - 场景检测与弹窗拦截（每步执行前扫描）
  - 错误恢复机制（场景分析 → 恢复路径 → 保护模式）
  - 定时启停（scheduled_start / scheduled_stop / run_window）
  - 运行时进度持久化（停止保存，启动恢复）
  - 兼容 macOS/Linux/Windows（daemon 线程 + 协作停止）

对应模块说明：模块说明/09-运行控制中心.md
"""

import json
import os
import random
import threading
import time
from datetime import datetime
from typing import Optional

from core.event_bus import event_bus, Events
from core.state_manager import state_manager
from core.state_schema import StateKeys
from core.run_state import RunState

log = None


def _log():
    global log
    if log is None:
        from core.logger import get_logger
        log = get_logger("core.run_controller")
    return log


# 运行时进度持久化路径
RUNTIME_PROGRESS_PATH = "config/runtime/task_runtime_progress.json"


class RunController:
    """程序运行生命周期管理（v3.0 三线程版）。

    三线程模型：
      ① _filler_loop()    — 填充线程：到期任务入队
      ② _executor_loop()  — 执行线程：FIFO 出队执行（含场景检测+错误恢复）
      ③ _scanner_loop()   — 扫描线程：小号遍历维护
    """

    def __init__(self, scheduler, connection, config, state_mgr, task_registry,
                 executor=None, recognizer=None, anti_detect=None):
        self._scheduler = scheduler
        self._connection = connection
        self._config = config
        self._state_mgr = state_mgr
        self._registry = task_registry
        self._executor = executor
        self._recognizer = recognizer
        self._anti_detect = anti_detect

        self._state = RunState.STOPPED
        self._current_task: Optional[str] = None

        # 停止事件（线程安全）
        self._stop_event = threading.Event()

        # 线程引用
        self._filler_thread: Optional[threading.Thread] = None
        self._executor_thread: Optional[threading.Thread] = None
        self._scanner_thread: Optional[threading.Thread] = None

        # 任务队列（FIFO，填充线程入队，执行线程出队）
        self._task_queue: list[str] = []
        self._queue_lock = threading.Lock()
        self._idle_counter = 0

        # 连续恢复计数（防止死循环）
        self._recover_count: dict[str, int] = {}

        # 注册事件
        self._register_events()

    # ==================== 事件订阅 ====================

    def _register_events(self):
        event_bus.subscribe(Events.START_REQUESTED, self._on_start)
        event_bus.subscribe(Events.STOP_REQUESTED, self._on_stop)
        event_bus.subscribe(Events.PAUSE_REQUESTED, self._on_pause)

    def _on_start(self):
        if self._state in (RunState.STOPPED, RunState.PAUSED):
            self._start_run()

    def _on_stop(self):
        self.stop()

    def _on_pause(self):
        if self._state == RunState.RUNNING:
            self._state = RunState.PAUSED
            self._state_mgr.set_state(StateKeys.RUN_STATUS, "paused")
            event_bus.publish(Events.RUN_PAUSED)

    # ==================== 启动 ====================

    def _start_run(self):
        if not self._check_run_allowed():
            return

        if not self._connection.is_connected():
            self._connection.connect()

        # 加载任务配置
        self._scheduler.load_tasks_from_config()
        self._scheduler.load_state()

        # 恢复运行时进度
        self._restore_runtime_progress()

        self._stop_event.clear()
        self._recover_count.clear()
        self._task_queue.clear()
        self._idle_counter = 0

        self._state = RunState.RUNNING
        self._state_mgr.set_state(StateKeys.RUN_STATUS, "running")
        self._state_mgr.set_state(StateKeys.RUN_START_TIME, datetime.now())
        event_bus.publish(Events.RUN_STARTED, start_time=datetime.now())

        # 启动三个线程
        self._filler_thread = threading.Thread(target=self._filler_loop, daemon=True)
        self._executor_thread = threading.Thread(target=self._executor_loop, daemon=True)
        self._scanner_thread = threading.Thread(target=self._scanner_loop, daemon=True)
        self._filler_thread.start()
        self._executor_thread.start()
        self._scanner_thread.start()
        _log().info("三线程已启动: filler + executor + scanner")

    # ==================== 停止 ====================

    def stop(self):
        """安全停止所有线程（设置标志，等待线程自然退出）。"""
        if self._state == RunState.STOPPED:
            return

        _log().info("正在停止运行控制中心...")
        self._stop_event.set()

        # 等待线程退出（daemon=True 确保不会阻塞进程退出）
        for t in [self._filler_thread, self._executor_thread, self._scanner_thread]:
            if t and t.is_alive():
                t.join(timeout=3)

        # 持久化进度
        self._save_runtime_progress()

        # 清理状态
        self._scheduler.save_state()
        self._state = RunState.STOPPED
        self._current_task = None
        self._filler_thread = None
        self._executor_thread = None
        self._scanner_thread = None
        self._task_queue.clear()
        self._state_mgr.set_state(StateKeys.RUN_STATUS, "stopped")
        self._state_mgr.set_state(StateKeys.CURRENT_TASK, None)
        self._state_mgr.set_state(StateKeys.CURRENT_STEP, None)
        event_bus.publish(Events.RUN_STOPPED)
        _log().info("运行控制中心已停止")

    # ==================== ① 填充线程 ====================

    def _filler_loop(self):
        """填充线程：定时获取到期任务并入队。"""
        while not self._stop_event.is_set():
            if self._state == RunState.PAUSED:
                time.sleep(0.5)
                continue

            # 定时启停检查
            if self._check_timed_stop():
                break
            if self._check_timed_start():
                continue

            if not self._check_run_allowed():
                break

            task_name = self._scheduler.get_next_task()
            if task_name:
                with self._queue_lock:
                    if task_name not in self._task_queue:
                        self._task_queue.append(task_name)
                        _log().debug(f"填充线程: {task_name} 已入队")
                time.sleep(1)
            else:
                time.sleep(self._adaptive_delay())

    def _adaptive_delay(self) -> float:
        """自适应休眠：空闲越久休眠越长，减少 CPU 空转。"""
        self._idle_counter += 1
        return min(2 + self._idle_counter * 0.5, 10)

    # ==================== ② 执行线程 ====================

    def _executor_loop(self):
        """执行线程：FIFO 出队执行（含场景检测+错误恢复）。"""
        while not self._stop_event.is_set():
            if self._state == RunState.PAUSED:
                time.sleep(0.5)
                continue

            task_name = None
            with self._queue_lock:
                if self._task_queue:
                    task_name = self._task_queue.pop(0)
                    self._idle_counter = 0

            if not task_name:
                time.sleep(0.5)
                continue

            # 执行前扫描弹窗
            self._scan_popups_before_exec()

            # 执行任务
            self._current_task = task_name
            self._state_mgr.set_state(StateKeys.CURRENT_TASK, task_name)
            event_bus.publish(Events.TASK_STARTED, task_name=task_name)

            success = self._execute_task_with_recovery(task_name)

            self._scheduler.mark_done(task_name, success=success)
            event_bus.publish(Events.TASK_DONE, task_name=task_name, success=success)
            self._current_task = None
            self._state_mgr.set_state(StateKeys.CURRENT_TASK, None)

            # 更新运行时进度
            self._update_task_progress(task_name)

    def _execute_task_with_recovery(self, task_name: str) -> bool:
        """执行任务，失败时自动走错误恢复流程。"""
        max_recover = 3

        for attempt in range(max_recover + 1):
            if self._stop_event.is_set():
                return False

            success = self._execute_task_once(task_name)
            if success:
                self._recover_count[task_name] = 0
                return True

            _log().warning(f"任务 {task_name} 失败 (尝试 {attempt}/{max_recover})")
            recovered = self._error_recovery(task_name)
            if not recovered:
                _log().error(f"任务 {task_name} 错误恢复失败，跳过任务")
                self._recover_count[task_name] = self._recover_count.get(task_name, 0) + 1
                return False

            _log().info(f"任务 {task_name} 已恢复，重试执行")

        self._recover_count[task_name] = self._recover_count.get(task_name, 0) + 1
        return False

    def _execute_task_once(self, task_name: str) -> bool:
        """单次执行任务。"""
        try:
            task = self._registry.get(task_name) if self._registry else None
            if task:
                self._state_mgr.set_state(StateKeys.CURRENT_STEP, "pre_check")
                result = task.execute()
                self._state_mgr.set_state(StateKeys.CURRENT_STEP, None)
                return result
            return False
        except Exception as e:
            _log().error(f"任务 {task_name} 执行异常: {e}")
            return False

    def _error_recovery(self, task_name: str) -> bool:
        """错误恢复流程：场景检测 → 恢复路径选择 → 验证。"""
        if not self._recognizer:
            return False

        try:
            # 1. 截图保存现场
            self._capture_error_screen(task_name)

            # 2. 分析当前页面
            candidates = [
                "scenes/courtyard/courtyard_main",
                "scenes/login/enter_game",
                "common/popup/popup_reward",
                "common/popup/popup_ad",
                "common/battle/victory",
                "common/battle/defeat",
                "common/ui/close_btn",
            ]

            scene = None
            if self._executor and hasattr(self._executor, 'detect_scene'):
                scene = self._executor.detect_scene(candidates, timeout=3)
            elif hasattr(self._recognizer, 'detect_scene'):
                scene = self._recognizer.detect_scene(candidates)

            if scene:
                self._state_mgr.set_state(StateKeys.LAST_KNOWN_SCENE, scene)

            # 3. 根据场景选择恢复路径
            if scene in ("common/battle/victory",):
                _log().info("恢复: 战斗结算，点击确认")
                if self._executor:
                    self._executor.click_image("common/battle/confirm_btn", timeout=3)
                return True

            elif scene in ("common/battle/defeat",):
                _log().info("恢复: 战斗失败，退出")
                if self._executor:
                    self._executor.click_image("common/ui/close_btn", timeout=3)
                return self._navigate_to_courtyard()

            elif scene in ("common/popup/popup_reward", "common/popup/popup_ad", "common/ui/close_btn"):
                _log().info("恢复: 弹窗干扰，关闭")
                if self._executor:
                    self._executor.click_image("common/ui/close_btn", timeout=3)
                return True

            elif scene in ("scenes/login/enter_game",):
                _log().warning("恢复: 游戏断开，终止任务")
                return False

            elif scene in ("scenes/courtyard/courtyard_main",):
                _log().info("恢复: 已在庭院")
                return True

            else:
                return self._protection_mode()

        except Exception as e:
            _log().error(f"错误恢复异常: {e}")
            return False

    def _protection_mode(self) -> bool:
        """保护模式：未知场景下的通用退出序列。"""
        _log().warning("进入保护模式：尝试通用退出序列")
        if not self._executor:
            return False

        exit_actions = [
            ("close_btn", lambda: self._executor.click_image("common/ui/close_btn", timeout=2)),
            ("BACK", lambda: self._executor.input_key("BACK")),
        ]

        for action_name, action in exit_actions:
            try:
                action()
                time.sleep(2)
                if self._recognizer:
                    result = self._recognizer.find("scenes/courtyard/courtyard_main")
                    if result:
                        return True
            except Exception:
                continue

        return False

    def _navigate_to_courtyard(self) -> bool:
        """导航回庭院。"""
        if not self._executor:
            return False
        try:
            for _ in range(5):
                self._executor.input_key("BACK")
                time.sleep(1.5)
                if self._recognizer:
                    result = self._recognizer.find("scenes/courtyard/courtyard_main")
                    if result:
                        return True
            return False
        except Exception:
            return False

    def _scan_popups_before_exec(self):
        """每步执行前扫描弹窗并关闭。"""
        if not self._executor:
            return
        popup_templates = [
            "common/popup/popup_reward",
            "common/popup/popup_ad",
            "common/popup/popup_update",
            "common/ui/close_btn",
        ]
        for popup in popup_templates:
            if self._stop_event.is_set():
                return
            try:
                if self._executor.click_if_exists(popup):
                    _log().info(f"弹窗拦截: {popup}")
                    time.sleep(1)
            except Exception:
                pass

    def _capture_error_screen(self, task_name: str):
        """错误时通知监控模块保存截图现场。"""
        try:
            event_bus.publish(Events.ERROR_OCCURRED, task=task_name)
        except Exception:
            pass

    # ==================== ③ 扫描线程 ====================

    def _scanner_loop(self):
        """扫描线程：定时遍历小号执行维护操作。

        间隔可配置（默认 30 分钟），通过 _stop_event 响应停止。
        """
        scan_interval = self._config.get("scan.interval", 1800) if self._config else 1800

        while not self._stop_event.is_set():
            if self._state == RunState.PAUSED:
                time.sleep(0.5)
                continue

            self._run_scan_cycle()

            # 分段等待，以便及时响应停止
            for _ in range(scan_interval // 5):
                if self._stop_event.is_set():
                    return
                time.sleep(5)

    def _run_scan_cycle(self):
        """执行一轮小号扫描。"""
        try:
            from core.account_manager import account_manager
            accounts = account_manager.get_all_accounts() if account_manager else []
            subs = [a for a in accounts if hasattr(a, 'role') and a.role == "sub"]

            if not subs:
                return

            _log().info(f"扫描线程: 开始检查 {len(subs)} 个小号")

            status = {}
            findings = {}

            for sub in subs:
                if self._stop_event.is_set():
                    return

                sub_id = sub.id
                status[sub_id] = {"account_id": sub_id, "status": "login", "task": "连接中..."}
                self._state_mgr.set_state(StateKeys.SUB_ACCOUNT_STATUS, dict(status))

                try:
                    if hasattr(self._connection, 'switch_device') and sub.device_id:
                        self._connection.switch_device(sub.device_id)

                    status[sub_id] = {"account_id": sub_id, "status": "scanning", "task": "检查协作"}
                    self._state_mgr.set_state(StateKeys.SUB_ACCOUNT_STATUS, dict(status))

                    sub_findings = self._scan_sub_account(sub)
                    if sub_findings:
                        findings[sub_id] = sub_findings

                    status[sub_id] = {"account_id": sub_id, "status": "idle", "task": "等待"}
                    self._state_mgr.set_state(StateKeys.SUB_ACCOUNT_STATUS, dict(status))

                except Exception as e:
                    _log().warning(f"扫描小号 {sub_id} 失败: {e}")
                    status[sub_id] = {"account_id": sub_id, "status": "error", "task": f"扫描失败: {e}"}
                    self._state_mgr.set_state(StateKeys.SUB_ACCOUNT_STATUS, dict(status))

            if findings:
                self._state_mgr.set_state(StateKeys.SUB_ACCOUNT_FINDINGS, findings)

            best = self._analyze_best_finding(findings)
            if best:
                self._state_mgr.set_state(StateKeys.BEST_FINDING, best)

            _log().info(f"扫描线程: 完成 {len(subs)} 个小号检查")

            try:
                from core.account_manager import account_manager
                if account_manager and hasattr(account_manager, 'switch_to'):
                    account_manager.switch_to("main")
            except Exception:
                pass

        except Exception as e:
            _log().error(f"扫描线程循环异常: {e}")

    def _scan_sub_account(self, sub) -> list:
        """扫描单个小号：执行维护操作，返回发现物列表。"""
        return []

    def _analyze_best_finding(self, findings: dict) -> Optional[dict]:
        """分析所有小号的发现物，选出最优结果。"""
        if not findings:
            return None
        best = None
        best_value = -1
        for sub_id, items in findings.items():
            for item in items:
                value = item.get("value", 0)
                if value > best_value:
                    best_value = value
                    best = {
                        "sub_account_id": sub_id,
                        "finding_type": item.get("finding_type", ""),
                        "content": item.get("content", ""),
                        "value": value,
                    }
        return best

    # ==================== 定时启停 ====================

    def _check_timed_stop(self) -> bool:
        """检查是否到了自动停止时间。"""
        try:
            scheduled_stop = self._config.get("run.scheduled_stop", "") if self._config else ""
            if scheduled_stop:
                now_str = datetime.now().strftime("%H:%M")
                if now_str >= scheduled_stop:
                    _log().info(f"定时停止: 已到 {scheduled_stop}")
                    self.stop()
                    return True
        except Exception:
            pass
        return False

    def _check_timed_start(self) -> bool:
        """检查是否在运行窗口外，窗口外则暂停等待。"""
        try:
            run_window = self._config.get("run.run_window", []) if self._config else []
            if len(run_window) == 2:
                now_str = datetime.now().strftime("%H:%M")
                win_start, win_end = run_window
                if not (win_start <= now_str <= win_end):
                    _log().debug(f"不在运行窗口 {win_start}-{win_end}，等待中")
                    time.sleep(30)
                    return True
        except Exception:
            pass
        return False

    # ==================== 运行时进度持久化 ====================

    def _save_runtime_progress(self):
        """保存运行时进度到磁盘。"""
        try:
            progress = self._state_mgr.get_state(StateKeys.TASK_RUNTIME_PROGRESS, {})
            if not progress:
                return
            os.makedirs(os.path.dirname(RUNTIME_PROGRESS_PATH), exist_ok=True)
            with open(RUNTIME_PROGRESS_PATH, "w", encoding="utf-8") as f:
                json.dump(progress, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            _log().error(f"保存运行时进度失败: {e}")

    def _restore_runtime_progress(self):
        """从磁盘恢复运行时进度。"""
        try:
            if os.path.exists(RUNTIME_PROGRESS_PATH):
                with open(RUNTIME_PROGRESS_PATH, "r", encoding="utf-8") as f:
                    progress = json.load(f)
                self._state_mgr.set_state(StateKeys.TASK_RUNTIME_PROGRESS, progress)
                _log().info(f"已恢复运行时进度: {len(progress)} 个任务")
        except Exception as e:
            _log().error(f"恢复运行时进度失败: {e}")

    def _update_task_progress(self, task_name: str):
        """更新任务的运行时进度。"""
        try:
            progress = self._state_mgr.get_state(StateKeys.TASK_RUNTIME_PROGRESS, {})
            if task_name not in progress:
                progress[task_name] = {
                    "task_name": task_name,
                    "completed": 0,
                    "total": 0,
                    "updated": datetime.now().isoformat(),
                    "loop_type": "count",
                }
            self._state_mgr.set_state(StateKeys.TASK_RUNTIME_PROGRESS, progress)
        except Exception:
            pass

    # ==================== 运行检查 ====================

    def _check_run_allowed(self) -> bool:
        if self._state_mgr.get_state(StateKeys.RUN_LIMIT_REACHED, False):
            event_bus.publish(Events.RUN_LIMIT_REACHED)
            return False
        if not self._connection.is_connected():
            return False
        return True

    # ==================== 查询 ====================

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def current_task(self) -> Optional[str]:
        return self._current_task

    @property
    def task_queue_size(self) -> int:
        with self._queue_lock:
            return len(self._task_queue)

    def get_task_queue(self) -> list[str]:
        with self._queue_lock:
            return list(self._task_queue)
                try:
                    result["success"] = task.execute()
                except Exception:
                    result["success"] = False

        self._task_thread = threading.Thread(target=_run, daemon=True)
        self._task_thread.start()

        # 等待完成或强制停止
        while self._task_thread.is_alive():
            if self._stop_event.is_set() or self._task_stop_event.is_set():
                self._force_kill_thread(self._task_thread)
                self._task_thread = None
                return False
            time.sleep(0.1)

        self._task_thread = None
        return result["success"]

    def _check_run_allowed(self) -> bool:
        if self._state_mgr.get_state(StateKeys.RUN_LIMIT_REACHED, False):
            event_bus.publish(Events.RUN_LIMIT_REACHED)
            return False
        if not self._connection.is_connected():
            return False
        return True

    # ==================== 查询 ====================

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def current_task(self) -> Optional[str]:
        return self._current_task
