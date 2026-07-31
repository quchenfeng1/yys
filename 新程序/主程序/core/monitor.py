"""
12-日志监控中心

Monitor 主入口（§5.1 聚合入口）。
对应设计书 §2/§3/§4/§5/§6。

聚合子模块：
- LoggerEngine（底层日志引擎）
- MetricsCollector（运行指标收集器）
- SnapshotManager（异常截图管理器）
- ReportGenerator（运行报告生成器）
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.logger import LoggerEngine
from core.metrics_collector import MetricsCollector
from core.snapshot_manager import SnapshotManager
from core.report_generator import ReportGenerator


# ═══════════════════════════════════════════════════════════════
#  §5.2 数据结构
# ═══════════════════════════════════════════════════════════════

class LogLevel:
    """日志级别枚举（§5.2）"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"

    _ORDER = {DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3}

    @classmethod
    def should_log(cls, level: str, min_level: str) -> bool:
        return cls._ORDER.get(level, 1) >= cls._ORDER.get(min_level, 1)


@dataclass
class LogEntry:
    """结构化日志条目（§5.2）"""
    timestamp: float = field(default_factory=time.time)
    level: str = "INFO"
    message: str = ""
    module: str = ""
    task: str | None = None
    step: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class TaskStats:
    """任务运行统计（§5.2）"""
    total: int = 0
    success: int = 0
    fail: int = 0
    avg_duration: float = 0.0
    total_duration: float = 0.0
    last_run: float = 0.0


@dataclass
class TaskRecord:
    """任务执行记录（§5.2）"""
    task_name: str = ""
    start_time: float = 0.0
    duration: float = 0.0
    success: bool = False
    error: str | None = None


# ═══════════════════════════════════════════════════════════════
#  Monitor 主入口
# ═══════════════════════════════════════════════════════════════

class Monitor:
    """
    可观测性中心（§5.3 方法定义）。

    聚合 LoggerEngine + MetricsCollector + SnapshotManager + ReportGenerator。
    外部模块只需引入 Monitor，通过统一入口调用所有可观测性功能。
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        config: Any = None,
        connection: Any = None,
        log_dir: str | Path = "logs",
        snapshot_dir: str | Path = "logs/snapshots",
        structured_log_dir: str | Path = "logs/structured",
        notify_callback: Callable[[str, str], None] | None = None,
        max_log_queue: int = 5000,
    ):
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名
        self._config = config       # §2.1 ConfigManager
        self._connection = connection  # §2.1 ConnectionManager
        self._state_mgr: Any = None    # §2.1 StateManager（构造函数或 set_state_manager 注入）

        # §2.3 异步日志队列
        self._log_queue: queue.Queue = queue.Queue(maxsize=max_log_queue)
        self._log_thread: threading.Thread | None = None
        self._log_stop = threading.Event()
        self._min_level: str = "DEBUG"

        # §2.3 任务统计
        self._task_stats: dict[str, TaskStats] = {}
        self._stats_lock = threading.Lock()
        self._task_timers: dict[str, float] = {}  # task_name → start_time

        # §2.3 聚合子模块
        self._logger = LoggerEngine()
        self._metrics = MetricsCollector()
        self._snapshot_mgr = SnapshotManager(snapshot_dir=snapshot_dir, event_bus=self._bus)
        # 传入真实的 metrics，确保报告有实际数据（§3.4）
        self._report_gen = ReportGenerator(metrics=self._metrics)

        # 结构化日志目录
        self._structured_dir = Path(structured_log_dir)
        self._structured_dir.mkdir(parents=True, exist_ok=True)

        # §2.2 metrics 属性
        self._metrics_cache: dict[str, Any] = {}

        # 通知回调
        self._notify_cb = notify_callback
        self._alert_count = 0
        self._error_count = 0

        # 初始化日志引擎
        self._init_logger(log_dir)

        # §3.1 启动异步日志线程
        self._start_log_thread()

        # §4.4 订阅事件记录
        self._bus.subscribe(Events.RUN_ERROR, self._on_run_error)
        self._bus.subscribe(Events.DEVICE_ERROR, self._on_device_error)
        self._bus.subscribe(Events.ANTI_DETECT_HUMAN_CHECK, self._on_human_check)

    def _init_logger(self, log_dir: str | Path) -> None:
        """初始化日志引擎"""
        level = "DEBUG"
        if self._config and hasattr(self._config, 'get'):
            level = self._config.get("global.log.level", "DEBUG")
        self._min_level = level
        self._logger.configure(log_dir=log_dir, level=level, structured=True)

    # ═══════════════════════════════════════════════════════════
    #  §3.1 结构化日志（异步）
    # ═══════════════════════════════════════════════════════════

    def _start_log_thread(self) -> None:
        """启动异步日志写入线程（§3.1 + §5.4）"""
        self._log_stop.clear()
        self._log_thread = threading.Thread(
            target=self._log_worker, daemon=True, name="monitor_log"
        )
        self._log_thread.start()

    def _log_worker(self) -> None:
        """日志后台工作线程（§5.4）"""
        while not self._log_stop.is_set():
            try:
                entry: LogEntry = self._log_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                # 写入文本日志（loguru）
                log_method = getattr(self._logger, entry.level.lower(), None)
                if log_method:
                    log_method(f"[{entry.module}] {entry.message}")

                # 写入结构化 JSONL
                self._write_structured_log(entry)

                # §4.4 发布 log_record 事件
                self._bus.publish(Events.LOG_RECORD, source="monitor",
                                 level=entry.level, message=entry.message,
                                 module=entry.module, task=entry.task,
                                 step=entry.step, tags=entry.tags,
                                 timestamp=entry.timestamp)
            except Exception:
                # §5.4 降级处理
                import sys
                print(f"[monitor] 日志写入失败: {entry.message}", file=sys.stderr)

    def _write_structured_log(self, entry: LogEntry) -> None:
        """写入结构化 JSONL 文件（按日期归档）"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self._structured_dir / f"{date_str}.jsonl"
        data = {
            "timestamp": datetime.fromtimestamp(entry.timestamp).isoformat(),
            "level": entry.level,
            "message": entry.message,
            "module": entry.module,
            "task": entry.task,
            "step": entry.step,
            "tags": entry.tags,
        }
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── §5.3 公开日志方法 ──────────────────────────────────

    def log(
        self,
        level: str,
        message: str,
        module: str = "",
        task: str | None = None,
        step: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """
        记录结构化日志（§3.1 + §5.3）。

        级别预过滤 → 封装 LogEntry → 入队 → 立即返回。
        """
        if not LogLevel.should_log(level, self._min_level):
            return

        entry = LogEntry(
            timestamp=time.time(),
            level=level,
            message=message,
            module=module,
            task=task,
            step=step,
            tags=tags or [],
        )

        try:
            self._log_queue.put(entry, block=True, timeout=0.5)
        except queue.Full:
            # §2.3 队列满降级
            import sys
            print(f"[monitor] 日志队列满，丢弃: {message}", file=sys.stderr)

    def debug(self, message: str, **kw: Any) -> None:
        self.log(LogLevel.DEBUG, message, **kw)

    def info(self, message: str, **kw: Any) -> None:
        self.log(LogLevel.INFO, message, **kw)

    def warning(self, message: str, **kw: Any) -> None:
        self.log(LogLevel.WARNING, message, **kw)

    def error(self, message: str, **kw: Any) -> None:
        self.log(LogLevel.ERROR, message, **kw)

    # ═══════════════════════════════════════════════════════════
    #  §3.2 运行指标收集
    # ═══════════════════════════════════════════════════════════

    def record_task_start(self, task_name: str) -> None:
        """
        记录任务开始时间（§3.2 + §5.3）。
        """
        self._task_timers[task_name] = time.time()

    def record_task_done(self, task_name: str, success: bool, duration: float | None = None) -> None:
        """
        记录任务完成统计（§3.2 + §5.3）。

        更新 _task_stats → 追加 execution_history → 记录指标
        """
        if duration is None:
            start = self._task_timers.pop(task_name, None)
            duration = time.time() - start if start else 0.0

        with self._stats_lock:
            stats = self._task_stats.setdefault(task_name, TaskStats())
            stats.total += 1
            stats.total_duration += duration
            stats.last_run = time.time()
            if success:
                stats.success += 1
            else:
                stats.fail += 1
            stats.avg_duration = stats.total_duration / stats.total if stats.total > 0 else 0.0

        # 记录到 MetricsCollector
        self._metrics.record_task_completed(duration=duration, success=success)

        # 追加到 execution_history（§6.2 → 07）
        self._append_execution_history(task_name, success, duration)

    def set_state_manager(self, state_mgr: Any) -> None:
        """注入 StateManager 引用（§2.1）"""
        self._state_mgr = state_mgr

    def _append_execution_history(self, task_name: str, success: bool, duration: float) -> None:
        """
        向 StateManager 的 execution_history 追加执行记录（§6.2）。

        读取现有列表 → 追加新记录 → 截断 100 条 → 写回。
        """
        if not self._state_mgr or not hasattr(self._state_mgr, 'get_state'):
            return

        try:
            history = self._state_mgr.get_state("execution_history", [])
            if not isinstance(history, list):
                history = []
            history.append({
                "task_name": task_name,
                "success": success,
                "duration": duration,
                "timestamp": datetime.now().isoformat(),
            })
            # 最多保留最近 100 条
            if len(history) > 100:
                history = history[-100:]
            self._state_mgr.set_state("execution_history", history)
        except Exception:
            pass

    def get_metrics(self, task_name: str) -> dict[str, Any]:
        """查询单个任务指标（§5.3）"""
        with self._stats_lock:
            stats = self._task_stats.get(task_name)
            if not stats:
                return {}
            return {
                "total": stats.total,
                "success": stats.success,
                "fail": stats.fail,
                "avg_duration": stats.avg_duration,
                "total_duration": stats.total_duration,
                "last_run": stats.last_run,
                "success_rate": stats.success / stats.total if stats.total > 0 else 0.0,
            }

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """查询全部任务指标（§5.3）"""
        with self._stats_lock:
            return {
                name: {
                    "total": s.total,
                    "success": s.success,
                    "fail": s.fail,
                    "avg_duration": s.avg_duration,
                    "total_duration": s.total_duration,
                    "last_run": s.last_run,
                    "success_rate": s.success / s.total if s.total > 0 else 0.0,
                }
                for name, s in self._task_stats.items()
            }

    @property
    def metrics(self) -> dict[str, Any]:
        """对外暴露指标（§2.2）"""
        return self.get_all_metrics()

    # ═══════════════════════════════════════════════════════════
    #  §3.3 异常截图
    # ═══════════════════════════════════════════════════════════

    def capture_on_error(self, task: str = "", step: str = "", error: str = "") -> str | None:
        """
        异常截图并保存上下文（§3.3 + §5.3）。

        文件名: {task}_{step}_{timestamp}
        保存截图 + 上下文 JSON。
        """
        # 截图
        image = None
        if self._connection and hasattr(self._connection, 'screenshot'):
            try:
                image = self._connection.screenshot()
            except Exception:
                self.warning("截图失败", module="monitor", task=task)

        path = self._snapshot_mgr.take_error_snapshot(error=error)

        # 保存上下文 JSON
        context = {
            "task": task,
            "step": step,
            "error": error,
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now().isoformat(),
            "screenshot": path or "",
        }
        ctx_dir = Path(self._snapshot_mgr.directory) / "context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ctx_file = ctx_dir / f"{task}_{step}_{ts}.json"
        try:
            with open(ctx_file, "w", encoding="utf-8") as f:
                json.dump(context, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return path

    # ═══════════════════════════════════════════════════════════
    #  §3.4 运行报告
    # ═══════════════════════════════════════════════════════════

    def generate_daily_report(self) -> str:
        """生成当日运行报告（Markdown，§3.4 + §5.3）"""
        return self._report_gen.generate(
            title=f"运行报告 {datetime.now().strftime('%Y-%m-%d')}",
            format="markdown",
        )

    def generate_weekly_report(self) -> str:
        """生成本周运行报告（Markdown，§3.4 + §5.3）"""
        return self._report_gen.generate(
            title=f"周报 {datetime.now().strftime('%Y-W%W')}",
            format="markdown",
        )

    # ═══════════════════════════════════════════════════════════
    #  §3.1 日志检索
    # ═══════════════════════════════════════════════════════════

    def query_logs(
        self,
        level: str | None = None,
        module: str | None = None,
        task: str | None = None,
        time_range: tuple[float, float] | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        检索历史日志（§5.3 + §5.5）。

        读取 logs/structured/{YYYY-MM-DD}.jsonl 逐行解析并过滤。
        """
        results: list[dict[str, Any]] = []
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self._structured_dir / f"{today}.jsonl"

        if not log_file.exists():
            return results

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # 过滤
                    if level and entry.get("level") != level:
                        continue
                    if module and module not in entry.get("module", ""):
                        continue
                    if task and entry.get("task") != task:
                        continue
                    if time_range:
                        ts = entry.get("timestamp", "")
                        try:
                            dt = datetime.fromisoformat(ts).timestamp()
                            if dt < time_range[0] or dt > time_range[1]:
                                continue
                        except (ValueError, TypeError):
                            continue
                    if keyword and keyword.lower() not in entry.get("message", "").lower():
                        continue

                    results.append(entry)
        except Exception:
            pass

        return results

    # ═══════════════════════════════════════════════════════════
    #  §4.5 通知推送
    # ═══════════════════════════════════════════════════════════

    def notify(self, level: str, title: str, message: str) -> None:
        """
        推送通知（§4.5 + §5.3）。

        level: "info" / "warning" / "error" / "success"
        内部发布 notify_alert 事件，UI 订阅后根据 level 执行对应操作。
        """
        self._bus.publish(Events.NOTIFY_ALERT, source="monitor",
                         level=level, title=title, message=message)

        if self._notify_cb:
            try:
                self._notify_cb(title, message)
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════
    #  §5.3 + §6.1 附加方法
    # ═══════════════════════════════════════════════════════════

    def query_task_history(self, task_name: str, date: str | None = None) -> list[TaskRecord]:
        """
        查询指定任务在指定日期的执行历史明细（§5.3）。

        从 structured JSONL 中按任务名和时间过滤。
        """
        records: list[TaskRecord] = []
        date_str = date or datetime.now().strftime("%Y-%m-%d")
        log_file = self._structured_dir / f"{date_str}.jsonl"

        if not log_file.exists():
            return records

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("task") != task_name:
                        continue
                    records.append(TaskRecord(
                        task_name=entry.get("task", ""),
                        duration=0.0,
                        success=entry.get("level") != "ERROR",
                    ))
        except Exception:
            pass

        return records

    def estimate_eta(self, queue_list: list[str]) -> str:
        """
        根据历史平均耗时估算队列预计完成时间（§5.3）。

        Args:
            queue_list: 任务名列表

        Returns:
            格式如 "约 15 分钟"
        """
        if not queue_list:
            return "无待执行任务"

        total_seconds = 0.0
        with self._stats_lock:
            for name in queue_list:
                stats = self._task_stats.get(name)
                if stats and stats.avg_duration > 0:
                    total_seconds += stats.avg_duration
                else:
                    total_seconds += 120.0  # 默认 2 分钟

        if total_seconds < 60:
            return f"约 {int(total_seconds)} 秒"
        elif total_seconds < 3600:
            return f"约 {int(total_seconds / 60)} 分钟"
        else:
            return f"约 {total_seconds / 3600:.1f} 小时"

    # ═══════════════════════════════════════════════════════════
    #  事件处理
    # ═══════════════════════════════════════════════════════════

    def _on_run_error(self, error: str, **kw: Any) -> None:
        self._error_count += 1
        self.error(f"运行错误: {error}", module="monitor")

    def _on_device_error(self, **kw: Any) -> None:
        self._error_count += 1
        self.error("设备错误", module="monitor")

    def _on_human_check(self, reason: str, **kw: Any) -> None:
        self.notify("warning", "人工验证", f"检测到人工验证: {reason}")

    # ═══════════════════════════════════════════════════════════
    #  查询 + 生命周期
    # ═══════════════════════════════════════════════════════════

    def get_status_summary(self) -> dict[str, Any]:
        """获取状态摘要"""
        return {
            "alerts": self._alert_count,
            "errors": self._error_count,
            "metrics": self.metrics,
        }

    def set_notify_callback(self, callback: Callable[[str, str], None]) -> None:
        """设置通知回调"""
        self._notify_cb = callback

    def close(self) -> None:
        """清理资源"""
        self._log_stop.set()
        if self._log_thread and self._log_thread.is_alive():
            self._log_thread.join(timeout=2)
        # 清空日志队列
        while not self._log_queue.empty():
            try:
                self._log_queue.get_nowait()
            except queue.Empty:
                break
