"""
运行控制模块（09-运行控制）v2.1 强制停止版

程序运行生命周期管理：
  - 接收 UI 启停信号（通过事件总线）
  - 检查运行允许性（防封号上限、连接状态）
  - 驱动调度循环
  - ★ v2.1：停止按钮 = 立即强制终止，不等待。

v2.1 核心变更：
  - 停止信号 → 立即终止，不等待当前步骤完成
  - 使用 threading.Event 实现线程级中断检查
  - 任务在独立线程执行，force_stop() 用 TerminateThread 强制终止
  - 停止后立即发布 run_stopped 事件，UI 瞬间恢复

对应解耦文档：模块说明/09-运行控制模块.md
"""

import ctypes
import time
import threading
from datetime import datetime
from typing import Optional

from core.event_bus import event_bus, Events
from core.state_manager import state_manager
from core.state_schema import StateKeys
from core.run_state import RunState


class RunController:
    """程序运行生命周期管理（v2.1 强制停止版）。

    停止行为：点击停止按钮 → 立即中断正在执行的任务 →
    强制终止线程 → 标记停止 → 发布 run_stopped。
    不等待、不优雅、立即生效。
    """

    def __init__(self, scheduler, connection, config, state_mgr, task_registry):
        self._scheduler = scheduler
        self._connection = connection
        self._config = config
        self._state_mgr = state_mgr
        self._registry = task_registry

        self._state = RunState.STOPPED
        self._current_task: Optional[str] = None
        self._run_thread: Optional[threading.Thread] = None
        self._task_thread: Optional[threading.Thread] = None

        # ★ v2.1：强制停止事件（线程安全）
        self._stop_event = threading.Event()
        self._task_stop_event = threading.Event()

        self._register_events()

    # ==================== 事件订阅 ====================

    def _register_events(self):
        event_bus.subscribe(Events.START_REQUESTED, self._on_start)
        event_bus.subscribe(Events.STOP_REQUESTED, self._on_stop)
        event_bus.subscribe(Events.PAUSE_REQUESTED, self._on_pause)

    # ==================== 信号处理 ====================

    def _on_start(self):
        if self._state in (RunState.STOPPED, RunState.PAUSED):
            self._start_run()

    def _on_stop(self):
        """★ v2.1：立即强制停止。"""
        self.force_stop()

    def _on_pause(self):
        if self._state == RunState.RUNNING:
            self._state = RunState.PAUSED
            self._state_mgr.set_state(StateKeys.RUN_STATUS, "paused")
            event_bus.publish(Events.RUN_PAUSED)

    # ==================== 强制停止（★ v2.1 核心） ====================

    def force_stop(self):
        """立即强制终止所有执行。

        无论当前在执行什么（识图中、点击中、等待中），
        直接中断所有线程，清理状态，发布事件。
        """
        if self._state == RunState.STOPPED:
            return

        # 1. 设置停止标志（线程安全的信号）
        self._stop_event.set()
        self._task_stop_event.set()

        # 2. 强制终止任务线程（如果正在执行）
        if self._task_thread and self._task_thread.is_alive():
            self._force_kill_thread(self._task_thread)

        # 3. 终止主循环线程
        if self._run_thread and self._run_thread.is_alive():
            self._force_kill_thread(self._run_thread)

        # 4. 清理状态
        self._cleanup_after_stop()

    @staticmethod
    def _force_kill_thread(thread: threading.Thread):
        """Windows API 强制终止线程。"""
        try:
            tid = thread.ident
            if tid is None:
                return
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenThread(1, False, tid)
            if handle:
                kernel32.TerminateThread(handle, 0)
                kernel32.CloseHandle(handle)
        except Exception:
            pass

    def _cleanup_after_stop(self):
        """停止后立即清理。"""
        self._scheduler.save_state()
        self._state = RunState.STOPPED
        self._current_task = None
        self._run_thread = None
        self._task_thread = None
        self._stop_event.clear()
        self._task_stop_event.clear()
        self._state_mgr.set_state(StateKeys.RUN_STATUS, "stopped")
        self._state_mgr.set_state(StateKeys.CURRENT_TASK, None)
        self._state_mgr.set_state(StateKeys.CURRENT_STEP, None)
        event_bus.publish(Events.RUN_STOPPED)

    # ==================== 启动运行 ====================

    def _start_run(self):
        if not self._check_run_allowed():
            return

        if not self._connection.is_connected():
            self._connection.connect()

        # 从 tasks.yaml 加载任务到调度器
        self._scheduler.load_tasks_from_config()
        self._scheduler.load_state()
        self._stop_event.clear()
        self._task_stop_event.clear()

        self._state = RunState.RUNNING
        self._state_mgr.set_state(StateKeys.RUN_STATUS, "running")
        self._state_mgr.set_state(StateKeys.RUN_START_TIME, datetime.now())
        event_bus.publish(Events.RUN_STARTED, start_time=datetime.now())

        self._run_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._run_thread.start()

    def _run_loop(self):
        """主调度循环。每步检查 _stop_event。"""
        idle_sleep = 5

        while not self._stop_event.is_set():
            if self._state == RunState.PAUSED:
                time.sleep(0.5)
                continue

            if not self._check_run_allowed():
                break

            task_name = self._scheduler.get_next_task()
            if not task_name:
                time.sleep(idle_sleep)
                continue

            if self._stop_event.is_set():
                break

            # 执行任务
            self._current_task = task_name
            self._state_mgr.set_state(StateKeys.CURRENT_TASK, task_name)
            event_bus.publish(Events.TASK_STARTED, task_name=task_name)

            self._task_stop_event.clear()
            success = self._execute_task(task_name)

            self._scheduler.mark_done(task_name, success=success)
            event_bus.publish(Events.TASK_DONE, task_name=task_name, success=success)
            self._current_task = None
            self._state_mgr.set_state(StateKeys.CURRENT_TASK, None)

        if not self._stop_event.is_set():
            self._cleanup_after_stop()

    def _execute_task(self, task_name: str) -> bool:
        """在独立线程中执行任务（支持强制终止）。"""
        result = {"success": False}

        def _run():
            task = self._registry.get(task_name) if self._registry else None
            if task:
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
