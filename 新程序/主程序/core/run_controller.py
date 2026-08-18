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

        # §识图信号映射（scene/ 素材 → 信号名），由启动引导加载 manifest 后注入
        self._signal_map: dict[str, str] = {}
        self._rel_by_signal: dict[str, list[str]] = {}  # 信号 → [模板,...]（1:N）
        self._scene_store = None  # SceneStore（触发素材开关动态刷新，2026-08-16）

        # ── 信号体系（2026-08-16）──
        self._executing: dict[str, dict] = {}   # 正在执行队列：暂停/待唤醒任务记录
        self._executing_lock = threading.Lock()
        self._trigger_index: dict[str, list[str]] = {}  # 任务信号名 → [触发任务]
        self._task_pause: dict | None = None   # 本次执行产生的暂停快照

        # §3.4 订阅启停控制
        self._bus.subscribe(Events.START_REQUESTED, lambda **kw: self._on_start())
        self._bus.subscribe(Events.STOP_REQUESTED, lambda **kw: self._on_stop())
        self._bus.subscribe(Events.PAUSE_REQUESTED, lambda **kw: self._on_pause())
        self._bus.subscribe(Events.RESUME_REQUESTED, lambda **kw: self._on_resume())
        self._bus.subscribe(Events.RUN_SHUTDOWN, lambda **kw: self._on_shutdown())
        self._bus.subscribe(Events.TASK_DUE, lambda **kw: self._on_task_due(kw.get('task_name', '')))
        self._bus.subscribe(Events.SCHEDULER_TASK_DUE, lambda **kw: self._on_task_due(kw.get('task_name', '')))
        # 任务信号（2026-08-16）：触发任务激活 + 暂停任务唤醒
        self._bus.subscribe(Events.TASK_SIGNAL, self._on_task_signal)

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
        # 跨日检查：周期进度中 cycle_date != 今天 → 重置 completed=0
        # （一日 100 次执行 20 次中断，次日启动从第 1 次开始）
        self._reset_cycle_if_new_day()

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
        执行线程主循环（§3.1 ② + 2026-08-16 信号体系）。

        取任务：就绪暂停任务（信号→优先级→随机）→ 待执行队列
        → 弹窗扫描 → 执行（含错误恢复/恢复执行）→ 暂停留存 / mark_done
        """
        while not self._stop_event.is_set():
            self._paused.wait()  # 全局暂停等待

            if self._stop_event.is_set():
                break

            kind, payload = self._pick_next_task()
            if kind is None:
                self._check_paused_timeouts()
                time.sleep(0.5)
                continue

            self._task_pause = None
            if kind == "resume":
                rec = payload
                task_name = rec.get("name", "")
                self.current_task = task_name
                resume_payload = {
                    "entry": rec.get("entry"),
                    "vars": rec.get("vars") or {},
                    "data": dict(rec.get("data") or {}),
                    "resume_wait": True,
                }
                if self._monitor and hasattr(self._monitor, 'info'):
                    outcome = rec.get("data", {}).get("wait_outcome", "resume")
                    self._monitor.info(
                        f"恢复执行任务: {task_name}（{outcome}）",
                        module="09-运行控制中心")
                success = self._execute_task_with_recovery(
                    task_name, resume=resume_payload)
                with self._executing_lock:
                    self._executing.pop(task_name, None)
            else:
                task_name = payload
                if self._monitor and hasattr(self._monitor, 'info'):
                    self._monitor.info(f"开始执行任务: {task_name}",
                                       module="09-运行控制中心")
                # 通知 UI 队列/当前任务变化
                self._bus.publish(Events.TASK_QUEUED, source="09-运行控制中心",
                                  task=task_name, queue=list(self._task_queue))
                # §3.6 执行前弹窗扫描
                if self._executor:
                    self._scan_popups_before_exec()
                # 记录任务开始（指标统计）
                if self._monitor and hasattr(self._monitor, 'record_task_start'):
                    try:
                        self._monitor.record_task_start(task_name)
                    except Exception:
                        pass
                success = self._execute_task_with_recovery(task_name)

            # 本次执行产生暂停快照 → 留存到正在执行队列，不 mark_done
            if self._task_pause:
                self._store_pause_record(task_name)
                self.current_task = None
                continue

            # 区分中断类型：系统停止中断（stop_event 置位且任务未成功）
            # → mark_done(interrupted=True)：下次执行=当前时间（立即到期重跑），不算失败
            # 异常失败（识别错误等）→ 走冷却推迟 + 队列标注
            interrupted = (not success) and self._stop_event.is_set()

            # mark_done
            if self._scheduler and hasattr(self._scheduler, 'mark_done'):
                self._scheduler.mark_done(task_name, success, interrupted=interrupted)
            # 记录任务完成（指标统计）
            if self._monitor and hasattr(self._monitor, 'record_task_done'):
                try:
                    self._monitor.record_task_done(task_name, success)
                except Exception:
                    pass
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

    def _execute_task_with_recovery(self, task_name: str,
                                    resume: dict | None = None) -> bool:
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
                success = self._execute_task_once(task_name, resume=resume)
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

    def _execute_task_once(self, task_name: str,
                           resume: dict | None = None) -> bool:
        """单次任务执行（§3.7 + §5.3）

        构造 TaskContext 并注入 executor/recognizer/stop_event/task_config 等依赖。
        resume（2026-08-16）：暂停任务恢复执行快照
        {entry, vars, data, resume_wait}。
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
                        "teaming": getattr(cfg, 'teaming', None),
                        "images": getattr(cfg, 'images', None),
                        "soul_setup": getattr(cfg, 'soul_setup', None),
                        "lock_team": bool(getattr(cfg, 'lock_team', False)),
                        "change_team": bool(getattr(cfg, 'change_team', False)),
                        "stamina_required": getattr(cfg, 'stamina_required', None),
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
                account_manager=self._account_mgr,
                state=self._state_mgr.get_state("task_runtime_progress", {}) if self._state_mgr else {},
            )
            # 信号体系（2026-08-16）：暂停任务恢复快照
            if resume:
                try:
                    context.resume = resume
                except Exception:
                    pass

            # TaskStep 入口类（设计书写法）不经过 BaseTask.run，需补发任务事件
            from tasks.base.task_step import TaskStep
            from tasks.base.base_task import BaseTask
            is_step_entry = isinstance(task, TaskStep) and not isinstance(task, BaseTask)
            if is_step_entry:
                self._bus.publish(Events.TASK_STARTED, source="run_controller",
                                 task_id=task_name, task_name=task_name)

            # §5.2 任务图片映射（逻辑名→素材路径）注入 Executor，供任务代码识别解析
            try:
                self._executor.set_asset_aliases(task_config.get("images") or {})
            except Exception:
                pass

            result = task.execute(context)
            ok = bool(getattr(result, 'success', False) or getattr(result, 'status', None) == 'success')

            # 暂停快照（2026-08-16）：执行到暂停节点 → 挂起，不 mark_done
            try:
                rdata = getattr(result, 'data', None) or {}
                if isinstance(rdata, dict) and rdata.get("paused"):
                    self._task_pause = rdata
                    return True
            except Exception:
                pass

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
        """本轮任务结束 → 保留周期进度（断点续跑，不清 0）。

        周期进度（task_runtime_progress.completed）由 BattleLoop 逐场累计
        （_on_task_progress 每场持久化）。任务完成后**不**清 0：
        - 同周期内再次执行 → 任务从 completed 续跑（执行 20/100 中断后从 20 继续）
        - 跨日 → _reset_cycle_if_new_day 在启动时重置为 0（从第 1 次开始）
        - 手动改配置 → reset_task_cycle 重置为 0（从第 1 次开始）
        """
        pass

    def _on_task_progress(self, task_id: str, completed: int, total: int) -> None:
        """
        BattleLoop 每场战斗结束回调（2026-08-16 退役）。

        BattleLoop 已随老任务体系删除，可视化任务进度由
        ProgressTracker + VISUAL_PROGRESS 缩略图体系承担；
        活动循环次数改为图内「可调用变量 + 参数处理 + 判断」实现。
        保留此空壳仅为兼容旧任务代码的 progress_saver 引用。
        """
        return None

    def reset_task_cycle(self, task_name: str) -> None:
        """重置指定任务的周期进度（手动更改配置后调用，下次从第 1 次开始）。"""
        if not self._state_mgr:
            return
        try:
            progress = self._state_mgr.get_state("task_runtime_progress", {})
            progress[task_name] = {
                "completed": 0,
                "total": 0,
                "cycle_date": datetime.now().strftime("%Y-%m-%d"),
                "updated": datetime.now().isoformat(),
            }
            self._state_mgr.set_state("task_runtime_progress", progress)
            self._save_runtime_progress()
        except Exception:
            pass

    def _reset_cycle_if_new_day(self) -> None:
        """跨日检查：周期进度中 cycle_date != 今天 → 重置 completed=0（从第 1 次开始）。

        由 _start_run 每次启动时调用（用户描述：执行 20 次中断，下次启动已是
        第二天 → 从第 1 次执行）。
        """
        if not self._state_mgr:
            return
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            progress = self._state_mgr.get_state("task_runtime_progress", {})
            changed = False
            for entry in list(progress.values()):
                if isinstance(entry, dict) and entry.get("cycle_date") != today:
                    entry["completed"] = 0
                    entry["cycle_date"] = today
                    changed = True
            if changed:
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

    def set_scene_store(self, scene_store) -> None:
        """注入 SceneStore（2026-08-16）：触发素材开关可在素材管理中修改，
        启动触发监控前重建信号索引（旧 manifest 映射保留 + 场景信号叠加）。"""
        self._scene_store = scene_store

    def _rebuild_signal_index(self) -> None:
        """在已注入映射基础上叠加最新 SceneStore 信号，重建 1:N 反向索引。

        _signal_map 中的旧 manifest 映射由 bootstrap 注入，这里只做增量更新，
        不覆盖（旧脚本任务 wait_signal 依赖）。
        """
        ss = getattr(self, "_scene_store", None)
        if ss is None or not hasattr(ss, 'signal_map'):
            return
        try:
            fresh = ss.signal_map()
        except Exception:
            return
        # 移除已失效的旧场景信号键，再叠加新映射（信号改空=非触发素材）
        for k in list(self._signal_map.keys()):
            if k in fresh:
                self._signal_map[k] = fresh[k]
        for k, v in fresh.items():
            self._signal_map[k] = v
        self._rel_by_signal = {}
        for k, v in self._signal_map.items():
            self._rel_by_signal.setdefault(v, []).append(k)

    def start_trigger_watcher(self) -> None:
        """
        启动触发监控（§3.6 + §5.3，2026-08-16 多对多索引重构）。

        收集 Scheduler.get_all_tasks() 中 repeat.type=trigger 的任务，
        构建反向索引 {模板路径: [任务,...]}：
          - 信号名 → 展开为场景全部特征块模板（1:N）
          - 旧素材路径原样透传
        模板**去重**成一份全局列表 → TriggerWatcher 每轮只扫描一次，
        命中后按索引激活全部关联任务。
        """
        if not self._trigger_watcher:
            return
        # 触发素材开关可能在素材管理中修改 → 重建信号索引后收集
        self._rebuild_signal_index()
        tpl_tasks: dict[str, list[str]] = {}
        if self._scheduler and hasattr(self._scheduler, 'get_all_tasks'):
            try:
                for cfg in self._scheduler.get_all_tasks():
                    if cfg.repeat and cfg.repeat.type == 'trigger':
                        tmpls = cfg.repeat.trigger_templates or []
                        # 只监控配置了触发模板的任务（无模板=仅手动触发，不启动监控）
                        if not tmpls:
                            continue
                        for t in tmpls:
                            # 支持信号名触发：信号名 → 多特征块模板展开
                            resolved = (self._rel_by_signal.get(t) or [t])
                            for tpl in resolved:
                                tpl_tasks.setdefault(tpl, []).append(cfg.name)
            except Exception:
                pass
        # 去重模板列表：全局只扫一次（索引键天然去重）
        self._trigger_watcher.start(tpl_tasks, sorted(tpl_tasks))

    def stop_trigger_watcher(self) -> None:
        """停止触发监控（§3.6 + §5.3）。"""
        if self._trigger_watcher:
            self._trigger_watcher.stop()

    def set_signal_map(self, signal_map: dict | None) -> None:
        """注入识图信号映射 {素材/特征块相对路径: 信号名}（启动引导加载）。

        用途：
        ① 转发给 Executor（detect_scene/ensure_scene/wait_signal 发布 SCENE_SIGNAL）；
        ② 触发式任务的 trigger_templates 可填**信号名**，收集时解析为素材路径。

        2026-08-16 素材库重构：场景 = 多蓝框×多连通域特征块，一个信号对应
        **多个**特征块模板路径 → _rel_by_signal 改为 1:N（信号→[模板,...]），
        触发监控对每个信号展开全部特征块，命中任一即触发。
        """
        self._signal_map = {str(k): str(v) for k, v in (signal_map or {}).items() if v}
        self._rel_by_signal: dict[str, list[str]] = {}
        for k, v in self._signal_map.items():
            self._rel_by_signal.setdefault(v, []).append(k)
        try:
            self._executor.set_signal_map(self._signal_map)
        except Exception:
            pass

    # ── 游戏切换（2026-08-16 B方案）───────────────────────

    def switch_game(self, runtime_progress_path: str | Path | None = None,
                    signal_map: dict | None = None,
                    scene_store: Any = None) -> None:
        """切换到新游戏：进度持久化路径 + 触发信号映射 + 场景素材库。

        前提：脚本已停止（bootstrap 调用前已校验）。
        清理旧游戏的运行残留（队列/当前任务/进度状态），防止串游戏。
        """
        with self._queue_lock:
            self._task_queue.clear()
        self.current_task = None
        self._recover_count.clear()
        self._idle_counter = 0
        self._consecutive_errors = 0
        self._last_error = ""
        if runtime_progress_path:
            self._runtime_progress_path = Path(runtime_progress_path)
        # 清掉旧游戏的任务进度（新进度按新路径懒恢复）
        if self._state_mgr is not None and hasattr(self._state_mgr, 'set_state'):
            try:
                self._state_mgr.set_state("task_runtime_progress", {})
            except Exception:
                pass
        if scene_store is not None:
            self.set_scene_store(scene_store)
        if signal_map is not None:
            self.set_signal_map(signal_map)

    def _scheduler_op_from_task(self, op: str, task_id: str) -> None:
        """调度器分支运行期回调（VisualTask._scheduler_op_cb，2026-08-16）。

        触发任务图执行到「调度器分支」节点时执行对应调度器操作；
        running 无需动作（执行流继续走到暂停节点 → 暂停快照留存）。
        """
        if not task_id or self._scheduler is None:
            return
        try:
            if op == "pending":
                self._scheduler.enqueue_pending(task_id)
            elif op == "skip":
                self._scheduler.skip_cycle(task_id)
            elif op == "invalidate":
                self._scheduler.invalidate(task_id)
        except Exception:
            pass

    def _on_start(self) -> None:
        """接收 start_requested 事件（§5.3）"""
        # 运行中或暂停中均不重启：暂停时 is_running=False，若不拦截会重新
        # execute() 创建重复线程并绕过暂停语义
        if not self.is_running and not self.is_paused:
            self._rebuild_trigger_index()
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

    # ═══════════════════════════════════════════════════════════
    #  信号体系（2026-08-16）：触发索引 / 信号分发 / 暂停唤醒
    # ═══════════════════════════════════════════════════════════

    def _rebuild_trigger_index(self) -> None:
        """重建「任务信号名 → 触发任务」索引（注册表扫描）+ 注入调度器检查器。"""
        idx: dict[str, list[str]] = {}
        names: set[str] = set()
        if self._registry is not None:
            for name, cls in getattr(self._registry, "_registry", {}).items():
                try:
                    sigs = cls.trigger_signal_names()
                except Exception:
                    sigs = []
                if sigs:
                    names.add(name)
                    for s in sigs:
                        idx.setdefault(s, []).append(name)
        self._trigger_index = idx
        if self._scheduler is not None:
            try:
                self._scheduler.set_trigger_checker(lambda n: n in names)
                self._scheduler.set_anomaly_checker(self._is_task_abnormal)
            except Exception:
                pass

    def _is_task_abnormal(self, task_name: str) -> bool:
        """任务是否被标记异常（AnomalyStore：不进任何队列直到确认修复）。"""
        try:
            from visual.visual_task import VisualTask
            store = VisualTask._anomaly_store
            if store is not None and hasattr(store, "is_task_abnormal"):
                return bool(store.is_task_abnormal(task_name))
        except Exception:
            pass
        return False

    def _on_task_signal(self, signal: str = "", payload: str = "", **kw) -> None:
        """任务信号分发（2026-08-16）：触发任务激活 + 暂停任务唤醒。

        - 发送方（任务/全局任务内任务信号输出节点）不暂停自己，继续执行
        - 触发任务：只有待触发区中的任务会被触发（不在队列/执行中才激活）
        - 暂停任务：仅收到信号的任务脱离暂停（信号 → 优先级 → 随机）
        """
        if not signal:
            return
        for name in list(self._trigger_index.get(signal, [])):
            try:
                self._activate_trigger_task(signal, name)
            except Exception:
                pass
        with self._executing_lock:
            for name, rec in self._executing.items():
                if rec.get("signal") == signal and not rec.get("ready"):
                    rec["ready"] = True
                    rec["data"] = dict(rec.get("data") or {})
                    rec["data"]["wait_outcome"] = "resume"
                    rec["wake_signal"] = signal
        try:
            self._bus.publish(Events.TASK_RESUMED, task="", signal=signal)
        except Exception:
            pass

    def _activate_trigger_task(self, signal: str, task_name: str) -> None:
        """激活触发任务：走其「任务信号触发器 → 调度器分支」。

        - enqueue_pending → 加入待执行队列（之后按顺序从 start 正常执行）
        - enqueue_running → 加入正在执行队列（暂停态，等调度轮到才执行）
        - skip / invalidate → 对应调度器操作
        去重：已在队列/正在执行/当前执行中的任务不再触发。
        """
        if task_name == self.current_task:
            return
        with self._queue_lock:
            if task_name in self._task_queue:
                return
        with self._executing_lock:
            if task_name in self._executing:
                return
        cls = None
        if self._registry is not None:
            cls = getattr(self._registry, "_registry", {}).get(task_name)
        if cls is None:
            return
        defn = getattr(cls, "_definition", None) or {}
        graph = defn.get("graph", {}) or {}
        ops_id: str | None = None
        for n in graph.get("nodes", []):
            if n.get("type") == "scheduler_ops":
                ops_id = n.get("id")
                break
        port: str | None = None
        entry: str | None = None
        for c in graph.get("connections", []):
            if ops_id and c.get("out_node") == ops_id and \
                    c.get("out_port") in ("enqueue_pending", "enqueue_running",
                                          "skip", "invalidate"):
                port = c.get("out_port")
                if port == "enqueue_running":
                    entry = c.get("in_node")
                break
        if self._scheduler is None:
            return
        if port == "skip":
            self._scheduler.skip_cycle(task_name)
        elif port == "invalidate":
            self._scheduler.invalidate(task_name)
        elif port == "enqueue_running":
            with self._executing_lock:
                self._executing[task_name] = {
                    "name": task_name,
                    "entry": entry,
                    "vars": {},
                    "data": {"wait_outcome": "resume"},
                    "signal": "",
                    "ready": False,
                    "active": False,
                    "priority": self._scheduler.get_priority(task_name),
                    "timeout_at": None,
                }
            self._bus.publish(Events.TASK_QUEUED, source="09-运行控制中心",
                              task=task_name, queue=list(self._task_queue))
        else:
            # enqueue_pending 或旧式无调度器节点 → 按到期触发逻辑入待执行
            self._scheduler.enqueue_pending(task_name)
        if self._monitor and hasattr(self._monitor, "info"):
            self._monitor.info(f"任务信号 [{signal}] → 触发 {task_name}（{port or 'enqueue_pending'}）",
                               module="09-运行控制中心")

    def _store_pause_record(self, task_name: str) -> None:
        """把本次执行的暂停快照存入正在执行队列记录。"""
        d = self._task_pause or {}
        self._task_pause = None
        try:
            seconds = float(d.get("pause_seconds", 60))
        except (TypeError, ValueError):
            seconds = 60.0
        with self._executing_lock:
            old = self._executing.get(task_name) or {}
            ready = bool(old.get("ready")) if old.get("signal") == d.get("pause_signal", "") else False
            self._executing[task_name] = {
                "name": task_name,
                "entry": d.get("pause_node") or old.get("entry"),
                "vars": d.get("vars") or {},
                "data": d.get("graph_data") or {},
                "signal": d.get("pause_signal", ""),
                "seconds": seconds,
                "ready": ready,
                "active": False,
                "priority": old.get("priority")
                or (self._scheduler.get_priority(task_name)
                    if self._scheduler else 10),
                "timeout_at": time.time() + seconds,
            }
        try:
            self._bus.publish(Events.TASK_PAUSED, task=task_name,
                              signal=d.get("pause_signal", ""))
        except Exception:
            pass

    def _check_paused_timeouts(self) -> None:
        """暂停任务超时（等待超时 → 唤醒走 timeout 分支）。"""
        now = time.time()
        with self._executing_lock:
            for rec in self._executing.values():
                if not rec.get("ready") and rec.get("timeout_at") \
                        and now >= rec["timeout_at"]:
                    rec["ready"] = True
                    rec["data"] = dict(rec.get("data") or {})
                    rec["data"]["wait_outcome"] = "timeout"

    def _pick_next_task(self):
        """挑选下一个执行单元：(kind, payload)。

        优先：已就绪（收到信号/超时）的暂停任务（信号 → 优先级 → 随机）；
        其次：待执行队列。返回 (None, None) = 无任务。
        """
        with self._executing_lock:
            ready = [r for r in self._executing.values()
                     if r.get("ready") and not r.get("active")]
            if ready:
                import random
                random.shuffle(ready)
                ready.sort(key=lambda r: int(r.get("priority", 10) or 10))
                rec = ready[0]
                rec["active"] = True
                return ("resume", rec)
        with self._queue_lock:
            if self._task_queue:
                name = self._task_queue.popleft()
                self.current_task = name
                return ("normal", name)
        return (None, None)

    def paused_snapshot(self) -> list[dict]:
        """正在执行队列中的暂停任务快照（UI 展示）。"""
        with self._executing_lock:
            return [dict(r) for r in self._executing.values()]

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
