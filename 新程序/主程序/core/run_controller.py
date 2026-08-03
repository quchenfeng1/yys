"""
09-运行控制中心

RunController 核心控制逻辑（三线程模型）。
对应设计书 §2/§3/§4/§5。

三线程：
- _filler_loop：到期任务入队（Scheduler 查询 + 自适应休眠）
- _executor_loop：FIFO 出队执行（含错误恢复 + 弹窗扫描）
- _scanner_loop：小号维护（30min 一轮 + scanner_lock 互斥）

设计原则：
- 协作停止：threading.Event + daemon 线程
- 暂停不中断：暂停保留队列和线程，恢复继续
- 错误自愈：场景分析 → 恢复路径 → 保护模式
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.exceptions import RunError, StopSignal
from core.run_state import RunState, RuntimeProgress, Finding, SubStatus


class RunController:
    """
    运行控制器（§5.3 方法定义）。

    用法:
        ctrl = RunController(scheduler, connection, config, state_mgr, ...)
        ctrl.execute()  # 启动三线程
        ctrl.stop()     # 停止
    """

    def __init__(
        self,
        scheduler: Any = None,
        connection: Any = None,
        config: Any = None,
        state_mgr: Any = None,
        registry: Any = None,
        executor: Any = None,
        recognizer: Any = None,
        anti_detect: Any = None,
        event_bus: EventBus | None = None,
        monitor: Any = None,
        account_mgr: Any = None,
        runtime_progress_path: str | Path | None = None,
        max_task_retries: int = 3,
        scanner_interval: float = 1800.0,
    ):
        # ── §2.1 依赖注入 ────────────────────────────────────
        self._scheduler = scheduler
        self._connection = connection
        self._config = config
        self._state_mgr = state_mgr
        self._registry = registry
        self._executor = executor
        self._recognizer = recognizer
        self._anti_detect = anti_detect
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名
        self._monitor = monitor
        self._account_mgr = account_mgr

        # ── §2.3 线程控制 ────────────────────────────────────
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._lock = threading.Lock()

        # §2.3 状态
        self._status = RunState.STOPPED
        self._paused = threading.Event()
        self._paused.set()  # 初始非暂停

        # §2.3 任务队列
        self._task_queue: deque[str] = deque()
        self._queue_lock = threading.Lock()

        # §3.10 扫描线程互斥
        self._scanner_lock = threading.Lock()
        self._scanner_running = threading.Event()

        # §2.3 错误计数+空闲计数
        self._recover_count: dict[str, int] = {}  # 各任务连续恢复失败计数
        self._idle_counter: int = 0
        self._consecutive_errors: int = 0
        self._max_consecutive_errors: int = 10
        self._last_error: str = ""

        # §2.3 线程引用
        self._filler_thread: threading.Thread | None = None
        self._executor_thread: threading.Thread | None = None
        self._scanner_thread: threading.Thread | None = None

        # §2.2 对外属性
        self.current_task: str | None = None

        # §3.5 运行时进度持久化路径
        self._runtime_progress_path = Path(runtime_progress_path) if runtime_progress_path else None

        # §4.6 沙盒模式
        self._dry_run: bool = False

        # §3.8 执行层最多重试次数
        self._max_task_retries = max_task_retries

        # §3.2 扫描间隔
        self._scanner_interval = scanner_interval

        # §3.6 触发监控（TriggerWatcher，02-图像识别模块 子服务）
        # 构造时内部创建（复用已注入的 recognizer/connection/event_bus，构造函数不变）
        from core.trigger_watcher import TriggerWatcher
        self._trigger_watcher: Any = None
        if self._recognizer is not None:
            self._trigger_watcher = TriggerWatcher(
                recognizer=self._recognizer,
                connection=self._connection,
                event_bus=self._event_bus,
            )

        # §3.4 订阅启停控制
        self._bus.subscribe(Events.START_REQUESTED, lambda **kw: self._on_start())
        self._bus.subscribe(Events.STOP_REQUESTED, lambda **kw: self._on_stop())
        self._bus.subscribe(Events.PAUSE_REQUESTED, lambda **kw: self._on_pause())
        self._bus.subscribe(Events.RESUME_REQUESTED, lambda **kw: self._on_resume())
        self._bus.subscribe(Events.RUN_SHUTDOWN, lambda **kw: self._on_shutdown())
        self._bus.subscribe(Events.TASK_DUE, lambda **kw: self._on_task_due(kw.get('task_name', '')))
        self._bus.subscribe(Events.SCHEDULER_TASK_DUE, lambda **kw: self._on_task_due(kw.get('task_name', '')))

    # ═══════════════════════════════════════════════════════════
    #  §2.2 对外暴露属性
    # ═══════════════════════════════════════════════════════════

    @property
    def status(self) -> str:
        with self._state_lock:
            return self._status.value if hasattr(self._status, "value") else str(self._status)

    @property
    def state(self) -> str:
        """说明书 §2.2 要求名（status 的别名）"""
        return self.status

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._status == RunState.RUNNING

    @property
    def is_paused(self) -> bool:
        with self._state_lock:
            return self._status == RunState.PAUSED

    @property
    def task_queue_size(self) -> int:
        with self._queue_lock:
            return len(self._task_queue)

    @property
    def queue_snapshot(self) -> list[str]:
        """当前队列内容快照（供 UI 展示）"""
        with self._queue_lock:
            return list(self._task_queue)

    @property
    def progress(self) -> float:
        return 0.0  # 由 StateManager 的 task_runtime_progress 追踪

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    # ═══════════════════════════════════════════════════════════
    #  §5.3 公开方法
    # ═══════════════════════════════════════════════════════════

    def _connect_device(self) -> None:
        """
        建立设备连接（§3.1 + §5.3）。

        真实/模拟模式统一入口。连接失败仅告警，不阻塞启动
        （与 self_check 策略一致：ADB 不通 → 告警但继续）。
        """
        if not self._connection:
            return
        if not hasattr(self._connection, 'connect'):
            return

        try:
            ok = self._connection.connect()
        except Exception as e:
            ok = False
            if self._monitor and hasattr(self._monitor, 'warning'):
                self._monitor.warning(f"设备连接失败: {e}", module="01-设备连接模块")

        if ok:
            serial = (getattr(self._connection, 'current_serial', None)
                      or getattr(self._connection, 'active_device_id', None)
                      or '')
            if self._monitor and hasattr(self._monitor, 'info'):
                self._monitor.info(f"设备连接成功: {serial}", module="01-设备连接模块")
        else:
            if self._monitor and hasattr(self._monitor, 'warning'):
                self._monitor.warning("设备连接失败", module="01-设备连接模块")

    def _start_run(self) -> None:
        """
        启动前准备工作（§5.3 _start_run）。

        Step0-Step6：建立连接 → 加载配置 → 构建日程 → 恢复进度 → 清空队列 → 设置状态 → 发事件
        """
        # Step 0: 建立设备连接（真实/模拟统一）
        self._connect_device()

        # Step 1: 加载配置
        if self._scheduler:
            self._scheduler.load_tasks_from_config()

        # Step 2: 构建初始日程
        if self._scheduler:
            self._scheduler.build_schedule()

        # Step 3: 恢复运行时进度
        self._restore_runtime_progress()

        # Step 4-6: 清空队列 + 设置状态 + 发事件
        with self._queue_lock:
            self._task_queue.clear()

        with self._state_lock:
            self._status = RunState.RUNNING
        self._stop_event.clear()
        self._paused.set()
        self._consecutive_errors = 0

        self._bus.publish(Events.RUN_STARTED, source="09-运行控制中心")

        # 输出可见日志，让 UI 日志面板有反馈
        if self._monitor and hasattr(self._monitor, 'info'):
            self._monitor.info("运行已启动", module="09-运行控制中心")

    def execute(self) -> None:
        """
        运行入口（§5.3 execute）。

        Step1→Step8 顺序初始化 → 启动三线程。
        """
        self._start_run()

        # Step 6.5: 启动触发监控（TriggerWatcher，§3.6）
        self.start_trigger_watcher()

        # Step 7: 启动三线程
        self._filler_thread = threading.Thread(
            target=self._filler_loop, daemon=True, name="run_filler"
        )
        self._filler_thread.start()

        self._executor_thread = threading.Thread(
            target=self._executor_loop, daemon=True, name="run_executor"
        )
        self._executor_thread.start()

        if self._account_mgr:
            self._scanner_thread = threading.Thread(
                target=self._scanner_loop, daemon=True, name="run_scanner"
            )
            self._scanner_thread.start()

        # Step 8: 通知 UI
        if self._state_mgr:
            self._state_mgr.set_state("run_status", "running")

    def stop(self) -> None:
        """
        停止运行（§3.4 + §5.3）。

        设置 stop_event → 等待三线程退出 → 保存进度 → 清理状态
        """
        with self._state_lock:
            if self._status in (RunState.STOPPED,):
                return
            self._status = RunState.STOPPED

        self._stop_event.set()
        self._paused.set()  # 如果暂停中，先唤醒以便退出

        # 停止触发监控（§3.6）
        self.stop_trigger_watcher()

        # 等待三线程退出
        for t in [self._filler_thread, self._executor_thread, self._scanner_thread]:
            if t and t.is_alive():
                t.join(timeout=3)

        # §3.4 保存运行时进度
        self._save_runtime_progress()

        # 保存调度状态
        if self._scheduler and hasattr(self._scheduler, 'save_state'):
            self._scheduler.save_state()

        # 清理
        self._filler_thread = None
        self._executor_thread = None
        self._scanner_thread = None
        self.current_task = None
        with self._queue_lock:
            self._task_queue.clear()

        with self._state_lock:
            self._status = RunState.STOPPED

        if self._state_mgr:
            self._state_mgr.set_state("run_status", "stopped")
        self._bus.publish(Events.RUN_STOPPED, source="09-运行控制中心")

    def is_stopped(self) -> bool:
        """检查是否已停止（§5.3）"""
        return self._stop_event.is_set()

    def pause(self) -> None:
        """暂停运行（§3.9 + §5.3）"""
        with self._state_lock:
            if self._status != RunState.RUNNING:
                return
            self._status = RunState.PAUSED
            self._paused.clear()

        if self._state_mgr:
            self._state_mgr.set_state("run_status", "paused")
        self._bus.publish(Events.RUN_PAUSED, source="09-运行控制中心")

    def resume(self) -> None:
        """恢复运行（§3.9 + §5.3）"""
        with self._state_lock:
            if self._status != RunState.PAUSED:
                return
            self._status = RunState.RUNNING
            self._paused.set()

        if self._state_mgr:
            self._state_mgr.set_state("run_status", "running")
        self._bus.publish(Events.RUN_RESUMED, source="09-运行控制中心")

    def save_progress(self) -> None:
        """保存运行时进度到磁盘（§3.5 + §5.3）"""
        self._save_runtime_progress()

    def load_progress(self) -> dict[str, Any]:
        """从磁盘加载运行时进度（§3.5 + §5.3）"""
        return self._restore_runtime_progress()

    def reset_progress(self, task_name: str) -> None:
        """重置指定任务的运行时进度（§5.3）"""
        if self._state_mgr:
            progress = self._state_mgr.get_state("task_runtime_progress", {})
            if task_name in progress:
                del progress[task_name]
                self._state_mgr.set_state("task_runtime_progress", progress)

    def check_run_window(self) -> bool:
        """
        检查当前时间是否在运行时段内（§3.3 + §5.3）。

        Returns:
            True=在时段内 / False=不在时段内
        """
        if not self._config:
            return True
        run_window = None
        if hasattr(self._config, 'get'):
            run_window = self._config.get("global.run_window")
        if not run_window or len(run_window) < 2:
            return True
        now = datetime.now()
        current = now.strftime("%H:%M")
        start, end = run_window[0], run_window[1]
        return start <= current <= end

    def set_dry_mode(self, enabled: bool) -> None:
        """设置沙盒模式（§4.6 + §5.3）"""
        self._dry_run = enabled
        if self._executor and hasattr(self._executor, 'set_dry_run'):
            self._executor.set_dry_run(enabled)

    # ═══════════════════════════════════════════════════════════
    #  §3.1 三线程
    # ═══════════════════════════════════════════════════════════

    # ── ① 填充线程（§3.1 _filler_loop）─────────────────────

    def _filler_loop(self) -> None:
        """
        填充线程主循环（§3.1 ①）。

        定时启停检查 → run_window 检查 → build_schedule → get_next_task
        → 到期任务入队 → 自适应休眠
        """
        while not self._stop_event.is_set():
            self._paused.wait()  # 暂停等待

            if self._stop_event.is_set():
                break

            # §3.3 定时启停检查
            if not self.check_run_window():
                self._adaptive_delay()
                continue

            # §3.1 检查到期任务
            if self._scheduler:
                schedule = self._scheduler.build_schedule()
                next_task = self._scheduler.get_next_task()
                if next_task:
                    with self._queue_lock:
                        # 去重：已在队列 OR 正在执行中（已 popleft 出队但未 mark_done）→ 不再入队
                        if next_task in self._task_queue or next_task == self.current_task:
                            already = True
                        else:
                            self._task_queue.append(next_task)
                            already = False
                    if already:
                        # 已在队列中（executor 尚未消化）→ 短暂等待，避免重复入队
                        self._adaptive_delay()
                        continue
                    self._idle_counter = 0
                    # 输出可见日志
                    if self._monitor and hasattr(self._monitor, 'info'):
                        self._monitor.info(f"任务已入队: {next_task}", module="09-运行控制中心")
                    # 通知 UI 队列变化
                    self._bus.publish(Events.TASK_QUEUED, source="09-运行控制中心",
                                      task=next_task, queue=list(self._task_queue))
                    continue

            # 无任务 → 自适应休眠（每 5 次空闲提示一次，避免刷屏）
            self._idle_counter += 1
            if self._idle_counter == 5:
                if self._monitor and hasattr(self._monitor, 'info'):
                    self._monitor.info("暂无到期任务，调度线程空闲等待", module="09-运行控制中心")
            self._adaptive_delay()

    # ── ② 执行线程（§3.1 _executor_loop）───────────────────

    def _executor_loop(self) -> None:
        """
        执行线程主循环（§3.1 ②）。

        FIFO 出队 → 弹窗扫描 → 执行任务（含错误恢复）→ mark_done
        """
        while not self._stop_event.is_set():
            self._paused.wait()  # 暂停等待

            if self._stop_event.is_set():
                break

            task_name: str | None = None
            with self._queue_lock:
                if self._task_queue:
                    task_name = self._task_queue.popleft()
                    if task_name:
                        # 锁内设置 current_task，保证填充线程持锁检查去重时能看到最新值
                        self.current_task = task_name

            if not task_name:
                time.sleep(0.5)
                continue
            if self._monitor and hasattr(self._monitor, 'info'):
                self._monitor.info(f"开始执行任务: {task_name}", module="09-运行控制中心")
            # 通知 UI 队列/当前任务变化
            self._bus.publish(Events.TASK_QUEUED, source="09-运行控制中心",
                              task=task_name, queue=list(self._task_queue))

            # §3.6 执行前弹窗扫描
            if self._executor:
                self._scan_popups_before_exec()

            # §3.7 + §3.8 执行任务（含错误恢复）
            success = self._execute_task_with_recovery(task_name)

            # mark_done
            if self._scheduler and hasattr(self._scheduler, 'mark_done'):
                self._scheduler.mark_done(task_name, success)
            if self._monitor and hasattr(self._monitor, 'info'):
                self._monitor.info(f"任务执行收尾: {task_name} success={success} → 05.mark_done 已调用",
                                   module="09-运行控制中心")

            # 更新运行时进度
            self._update_task_progress(task_name, success)

            self.current_task = None
            self._consecutive_errors = 0

    # ── ③ 扫描线程（§3.1 ③ + §3.2）────────────────────────

    def _scanner_loop(self) -> None:
        """
        扫描线程主循环（§3.2）。

        每 30 分钟遍历小号 → 更新状态 → 执行维护 → 分析 findings
        """
        while not self._stop_event.is_set():
            # 分段休眠 30 分钟（每段检查 stop_event）
            for _ in range(int(self._scanner_interval)):
                if self._stop_event.is_set():
                    return
                time.sleep(1)

            if self._stop_event.is_set():
                break

            # 双层互斥（§3.2）
            if not self._scanner_lock.acquire(blocking=False):
                continue

            try:
                self._scanner_running.set()
                self._run_scan_cycle()
            finally:
                self._scanner_running.clear()
                self._scanner_lock.release()

    def _run_scan_cycle(self) -> None:
        """执行一轮扫描（§3.2 步骤 1-4）"""
        if not self._account_mgr:
            return

        # Step 1: 获取小号列表
        subs = []
        if hasattr(self._account_mgr, 'get_all_accounts'):
            subs = self._account_mgr.get_all_accounts()
        elif hasattr(self._account_mgr, 'list_sub_accounts'):
            subs = self._account_mgr.list_sub_accounts()

        sub_status: dict[str, SubStatus] = {}
        all_findings: dict[str, list[Finding]] = {}

        for sub in subs:
            sub_id = getattr(sub, 'account_id', '') or getattr(sub, 'name', str(sub))
            if not sub_id:
                continue

            # 更新状态 → scanning
            sub_status[sub_id] = SubStatus(account_id=sub_id, status="scanning", task="检查协作")

            try:
                # 切换设备
                dev_id = getattr(sub, 'device_id', None)
                if dev_id and self._connection and hasattr(self._connection, 'switch_device'):
                    self._connection.switch_device(dev_id)

                # 执行维护操作
                findings: list[Finding] = []
                if self._executor:
                    # 收邮件/领奖励
                    if hasattr(self._executor, 'click_if_exists'):
                        self._executor.click_if_exists("claim_reward")
                    # 查看协作
                    if hasattr(self._executor, 'detect_scene'):
                        scene = self._executor.detect_scene(["collab"])
                        if scene:
                            findings.append(Finding(
                                sub_account_id=sub_id,
                                finding_type="collab",
                                content=f"协作: {scene}",
                                value=80.0,
                                timestamp=datetime.now().isoformat(),
                            ))

                all_findings[sub_id] = findings
                sub_status[sub_id] = SubStatus(account_id=sub_id, status="idle", task="等待")

            except Exception:
                sub_status[sub_id] = SubStatus(account_id=sub_id, status="error", task=str(traceback.format_exc()))

        # Step 3: 分析 findings
        best_finding: Finding | None = None
        for sub_id, findings in all_findings.items():
            for f in findings:
                if best_finding is None or f.value > best_finding.value:
                    best_finding = f

        # Step 4: 写入状态
        if self._state_mgr:
            self._state_mgr.set_state("sub_account_status", sub_status)
            self._state_mgr.set_state("sub_account_findings", all_findings)
            if best_finding:
                self._state_mgr.set_state("best_finding", best_finding)

    # ═══════════════════════════════════════════════════════════
    #  §3.7 错误恢复
    # ═══════════════════════════════════════════════════════════

    def _execute_task_with_recovery(self, task_name: str) -> bool:
        """
        带错误恢复的任务执行（最多重试 _max_task_retries 次，§3.7）。

        执行层重试与调度层冷却的关系（§3.7）：
        - 任一次成功 → mark_done(success=True)
        - 全部失败 → mark_done(success=False)
        """
        for attempt in range(self._max_task_retries):
            if self._stop_event.is_set():
                return False

            try:
                success = self._execute_task_once(task_name)
                if success:
                    return True
            except Exception as e:
                if self._monitor and hasattr(self._monitor, 'log'):
                    self._monitor.log("error", f"任务执行异常[{task_name}]: {e}")

            # 错误恢复
            if not self._error_recovery(task_name):
                # 恢复失败 → 跳过任务
                return False

        return False

    def _execute_task_once(self, task_name: str) -> bool:
        """单次任务执行（§3.7 + §5.3）

        构造 TaskContext 并注入 executor/recognizer/stop_event/task_config 等依赖。
        """
        if not self._registry:
            return False

        try:
            task = self._registry.get(task_name)
            if not task:
                return False

            # 从 Scheduler 取任务配置，注入 context.task_config（设计书 §8.2 约定）
            task_config: dict[str, Any] = {}
            if self._scheduler and hasattr(self._scheduler, 'get_config'):
                cfg = self._scheduler.get_config(task_name)
                if cfg is not None:
                    task_config = {
                        "name": cfg.name,
                        "display_name": getattr(cfg, 'display_name', '') or cfg.name,
                        "category": getattr(cfg, 'category', 'daily'),
                        "priority": getattr(cfg, 'priority', 10),
                        "max_daily": getattr(cfg, 'max_daily', None),
                        "max_fail_streak": getattr(cfg, 'max_fail_streak', 10),
                        "time_start": getattr(cfg, 'time_start', None),
                        "time_end": getattr(cfg, 'time_end', None),
                        "time_slots": getattr(cfg, 'time_slots', None),
                        "team_id": getattr(cfg, 'team_id', None),
                        "floor": getattr(cfg, 'floor', None),
                        "execution_mode": getattr(cfg, 'execution_mode', 'daily'),
                        "repeat": None,
                        "loop_count": None,
                    }
                    repeat = getattr(cfg, 'repeat', None)
                    if repeat is not None:
                        task_config["loop_count"] = getattr(repeat, 'loop_count', None)
                        task_config["repeat"] = {
                            "type": getattr(repeat, 'type', 'daily'),
                            "value": getattr(repeat, 'value', None),
                            "loop_count": getattr(repeat, 'loop_count', None),
                        }

            # 构造 TaskContext（§5.4）
            from tasks.base.task_context import TaskContext
            context = TaskContext(
                task_id=task_name,
                task_name=task_name,
                task_config=task_config,
                executor=self._executor,
                recognizer=self._recognizer,
                stop_event=self._stop_event,
                timeout=300.0,
                state=self._state_mgr.get_state("task_runtime_progress", {}) if self._state_mgr else {},
                # 说明书 04 §BattleLoop：每场战斗结束的进度持久化回调
                progress_saver=self._on_task_progress,
            )

            # TaskStep 入口类（设计书写法）不经过 BaseTask.run，需补发任务事件
            from tasks.base.task_step import TaskStep
            from tasks.base.base_task import BaseTask
            is_step_entry = isinstance(task, TaskStep) and not isinstance(task, BaseTask)
            if is_step_entry:
                self._bus.publish(Events.TASK_STARTED, source="run_controller",
                                 task_id=task_name, task_name=task_name)

            result = task.execute(context)
            ok = bool(getattr(result, 'success', False) or getattr(result, 'status', None) == 'success')

            if is_step_entry:
                if ok:
                    self._bus.publish(Events.TASK_COMPLETED, source="run_controller",
                                     task_id=task_name,
                                     duration=getattr(result, 'duration', 0.0))
                else:
                    self._bus.publish(Events.TASK_FAILED, source="run_controller",
                                     task_id=task_name,
                                     error=getattr(result, 'message', '') or getattr(result, 'reason', ''))
            return ok
        except Exception:
            return False

    def _error_recovery(self, task_name: str) -> bool:
        """
        错误恢复（§3.7 + §5.3）。

        截图 → detect_scene → 恢复路径选择 → 保护模式
        """
        if not self._executor:
            return False

        try:
            # 1. 截图保存
            if hasattr(self._executor, 'screenshot'):
                self._executor.screenshot()
            self._bus.publish(Events.ERROR_OCCURRED, source="09-运行控制中心",
                             task=task_name, error="任务失败，尝试恢复")

            # 2. 场景检测
            scene = None
            if hasattr(self._executor, 'detect_scene'):
                scene = self._executor.detect_scene([
                    "scenes/courtyard/courtyard_main",
                    "scenes/login/enter_game",
                    "common/popup/popup_reward",
                    "common/battle/victory",
                    "common/battle/defeat",
                    "common/ui/close_btn",
                ])

            # 3. 恢复路径（用 endswith 匹配 detect_scene 返回的完整路径）
            if scene and ("courtyard" in scene):
                return True  # 已在庭院，直接重试
            elif scene and any(x in scene for x in ("victory", "defeat")):
                if hasattr(self._executor, 'click_if_exists'):
                    self._executor.click_if_exists("confirm_btn")
                self._navigate_to_courtyard()
                return True
            elif scene and any(x in scene for x in ("popup_reward", "close_btn")):
                if hasattr(self._executor, 'click_if_exists'):
                    self._executor.click_if_exists("close_btn")
                return True  # 关弹窗后重试
            elif scene and ("login" in scene or "enter_game" in scene):
                self._bus.publish(Events.ERROR_OCCURRED, source="09-运行控制中心",
                                 task=task_name, error="游戏断开连接")
                return False  # 不可恢复
            else:
                # §3.7 保护模式（通用退出序列）
                return self._protection_mode()

        except Exception:
            return False

    def _navigate_to_courtyard(self) -> bool:
        """导航回庭院"""
        if not self._executor:
            return False
        try:
            if hasattr(self._executor, 'click_if_exists'):
                self._executor.click_if_exists("close_btn")
            if hasattr(self._executor, 'input_key'):
                self._executor.input_key("BACK")
            if hasattr(self._executor, 'ensure_scene'):
                return self._executor.ensure_scene("courtyard", timeout=10)
        except Exception:
            pass
        return False

    def _protection_mode(self) -> bool:
        """
        保护模式（§3.7 通用退出序列）。

        close_btn → BACK → ensure_scene 庭院
        """
        if not self._executor:
            return False
        try:
            if hasattr(self._executor, 'click_if_exists'):
                if self._executor.click_if_exists("close_btn"):
                    return True
            if hasattr(self._executor, 'input_key'):
                self._executor.input_key("BACK")
            if hasattr(self._executor, 'ensure_scene'):
                return self._executor.ensure_scene("courtyard", timeout=10)
        except Exception:
            pass
        return False

    # ═══════════════════════════════════════════════════════════
    #  §3.6 弹窗扫描
    # ═══════════════════════════════════════════════════════════

    def _scan_popups_before_exec(self) -> None:
        """
        执行前弹窗扫描（§3.6 + §5.3）。

        遍历弹窗模板列表 → click_if_exists → 全部检查完毕 → 开始执行
        """
        if not self._executor or not hasattr(self._executor, 'click_if_exists'):
            return

        popup_templates = [
            "common/popup/popup_reward",
            "common/popup/popup_ad",
            "common/popup/popup_update",
            "common/ui/close_btn",
        ]

        for tmpl in popup_templates:
            if self._stop_event.is_set():
                break
            try:
                if self._executor.click_if_exists(tmpl):
                    time.sleep(1)  # 关弹窗后等动画
            except Exception:
                continue

    # ═══════════════════════════════════════════════════════════
    #  §3.5 运行时进度持久化
    # ═══════════════════════════════════════════════════════════

    def _save_runtime_progress(self) -> None:
        """保存运行时进度到磁盘（§3.5 + §5.3）"""
        if not self._runtime_progress_path or not self._state_mgr:
            return

        progress = self._state_mgr.get_state("task_runtime_progress", {})
        try:
            self._runtime_progress_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._runtime_progress_path, "w", encoding="utf-8") as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            if self._monitor and hasattr(self._monitor, 'log'):
                self._monitor.log("error", f"保存运行时进度失败: {e}")

    def _restore_runtime_progress(self) -> dict[str, Any]:
        """从磁盘加载运行时进度（§3.5 + §5.3）"""
        if not self._runtime_progress_path or not self._state_mgr:
            return {}

        data: dict[str, Any] = {}
        if self._runtime_progress_path.exists():
            try:
                with open(self._runtime_progress_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = {}

        if data and self._state_mgr:
            self._state_mgr.set_state("task_runtime_progress", data)
        return data

    def _update_task_progress(self, task_name: str, success: bool) -> None:
        """本轮任务结束 → 重置场次进度（下一轮从 0 开始）

        场次进度由 BattleLoop 每场战斗后维护（_on_task_progress），
        这里只在任务整轮完成后清空，使下一轮重新从 0 开始。
        """
        self._reset_task_progress(task_name)

    def _on_task_progress(self, task_id: str, completed: int, total: int) -> None:
        """
        BattleLoop 每场战斗结束回调（说明书 04 §BattleLoop）。

        更新 task_runtime_progress 并立即写盘——异常关闭时
        最多丢失最近 1 场进度（断点续跑保障）。
        """
        if not self._state_mgr:
            return
        try:
            progress = self._state_mgr.get_state("task_runtime_progress", {})
            progress[task_id] = {
                "completed": int(completed),
                "total": int(total),
                "updated": datetime.now().isoformat(),
            }
            self._state_mgr.set_state("task_runtime_progress", progress)
            self._save_runtime_progress()
        except Exception:
            pass

    def _reset_task_progress(self, task_name: str) -> None:
        """本轮任务结束 → 重置场次进度为 0（下一轮从 0 开始）"""
        if not self._state_mgr:
            return
        try:
            progress = self._state_mgr.get_state("task_runtime_progress", {})
            entry = progress.get(task_name, {})
            if isinstance(entry, dict):
                entry["completed"] = 0
                entry["updated"] = datetime.now().isoformat()
            progress[task_name] = entry
            self._state_mgr.set_state("task_runtime_progress", progress)
            self._save_runtime_progress()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    #  §4.2 自适应休眠
    # ═══════════════════════════════════════════════════════════

    def _adaptive_delay(self) -> None:
        """
        自适应休眠（§4.2 + §5.3）。

        无任务时递增 2~10s，每段检查 _stop_event 和 _state 变化。
        """
        delay = min(2 + self._idle_counter, 10)
        for _ in range(int(delay)):
            if self._stop_event.is_set() or not self._paused.is_set():
                return
            time.sleep(1)

    # ═══════════════════════════════════════════════════════════
    #  §3.9 暂停/恢复事件处理
    # ═══════════════════════════════════════════════════════════

    def start_trigger_watcher(self) -> None:
        """
        启动触发监控（§3.6 + §5.3）。

        收集 Scheduler.get_all_tasks() 中 repeat.type=trigger 的任务
        及其 trigger_templates 识别列表 → TriggerWatcher.start()。
        """
        if not self._trigger_watcher:
            return
        trigger_tasks: list[tuple[str, list[str]]] = []
        if self._scheduler and hasattr(self._scheduler, 'get_all_tasks'):
            try:
                for cfg in self._scheduler.get_all_tasks():
                    if cfg.repeat and cfg.repeat.type == 'trigger':
                        tmpls = cfg.repeat.trigger_templates or []
                        # 只监控配置了触发模板的任务（无模板=仅手动触发，不启动监控）
                        if tmpls:
                            trigger_tasks.append((cfg.name, list(tmpls)))
            except Exception:
                pass
        self._trigger_watcher.start(trigger_tasks)

    def stop_trigger_watcher(self) -> None:
        """停止触发监控（§3.6 + §5.3）。"""
        if self._trigger_watcher:
            self._trigger_watcher.stop()

    def _on_start(self) -> None:
        """接收 start_requested 事件（§5.3）"""
        if not self.is_running:
            self.execute()

    def _on_stop(self) -> None:
        """接收 stop_requested 事件（§5.3）"""
        if self.is_running or self.is_paused:
            self.stop()

    def _on_pause(self) -> None:
        """接收 pause_requested 事件（§3.9 + §5.3）"""
        if self.is_running:
            self.pause()

    def _on_resume(self) -> None:
        """接收 resume_requested 事件（§3.9 + §5.3）"""
        if self.is_paused:
            self.resume()

    def _on_shutdown(self) -> None:
        """接收关闭事件"""
        self.stop()

    def _on_run_limit_reached(self) -> None:
        """接收 run_limit_reached 事件（§5.3）"""
        if self._monitor and hasattr(self._monitor, 'notify'):
            self._monitor.notify("info", "已达今日上限，自动停止")
        self.stop()
        self._bus.publish(Events.RUN_STOPPED, source="09-运行控制中心",
                         reason="run_limit_reached")

    # ═══════════════════════════════════════════════════════════
    #  §3.10 组队协调事件处理
    # ═══════════════════════════════════════════════════════════

    def _on_task_due(self, task_name: str) -> None:
        """接收 task_due 事件（§5.3 + §5.4）：到期任务直接入队"""
        if not task_name:
            return
        with self._queue_lock:
            if task_name not in self._task_queue:
                self._task_queue.append(task_name)

    def _on_teaming_prepared(self, task_name: str, **kw: Any) -> None:
        """接收 teaming_prepared 事件（§3.10 + §5.3）"""
        # 小号已就绪，继续组队流程
        if self._state_mgr:
            self._state_mgr.set_state("current_step", f"组队就绪: {task_name}")

    def _on_coordinate_action(self, account_id: str, action: str, params: dict | None = None, **kw: Any) -> None:
        """
        接收 coordinate_action 事件（§3.10 + §5.3）。

        在指定小号上执行组队协调操作。
        """
        if not self._account_mgr or not self._executor:
            return

        try:
            # 切换账号
            if hasattr(self._account_mgr, 'switch_to'):
                self._account_mgr.switch_to(account_id)

            # 执行组队操作
            if action == "join_team":
                if hasattr(self._executor, 'click_if_exists'):
                    self._executor.click_if_exists("btn_accept_invite")
                    self._executor.click_if_exists("btn_ready")
            elif action == "create_team":
                if hasattr(self._executor, 'click_if_exists'):
                    self._executor.click_if_exists("btn_create_team")
            elif action == "start_battle":
                if hasattr(self._executor, 'click_if_exists'):
                    self._executor.click_if_exists("btn_start_battle")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════
    #  等待 + 清理
    # ═══════════════════════════════════════════════════════════

    def wait_for_stop(self, timeout: float | None = None) -> bool:
        """等待三线程退出"""
        threads = [self._filler_thread, self._executor_thread, self._scanner_thread]
        for t in threads:
            if t and t.is_alive():
                t.join(timeout=timeout)
        return self._stop_event.is_set()

    def close(self) -> None:
        """清理资源"""
        self.stop()
        self.wait_for_stop(timeout=5)
