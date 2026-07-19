"""
监控主入口（12-日志与监控模块）

可观测性中心：统一管理结构化日志、运行指标、异常截图和运行报告。

对应解耦文档：模块说明/12-日志与监控模块.md
"""

import json
import os
from datetime import datetime, date
from typing import Optional

from core.event_bus import event_bus, Events
from core.metrics_collector import MetricsCollector
from core.snapshot_manager import SnapshotManager
from core.report_generator import ReportGenerator


class Monitor:
    """日志与监控中心。"""

    def __init__(self, config):
        self._config = config
        self._metrics = MetricsCollector()
        self._snapshot = SnapshotManager(config)
        self._report = ReportGenerator(config, self._metrics)

        # 日志目录
        self._logs_dir = "logs"
        self._structured_dir = os.path.join(self._logs_dir, "structured")
        os.makedirs(self._structured_dir, exist_ok=True)

        # 订阅任务事件自动记录指标
        event_bus.subscribe(Events.TASK_STARTED, self.record_task_start)
        event_bus.subscribe(Events.TASK_DONE, self._on_task_done)

    # ==================== 结构化日志 ====================

    def log(self, level: str, message: str, *,
            module: str = "", task: str = "", step: str = "", tags: list = None):
        """记录结构化日志。

        同时：① 写入文件 ② 结构化 JSON 存储 ③ 通过事件总线发布供 UI 显示。
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "module": module,
            "task": task,
            "step": step,
            "tags": tags or [],
        }

        # 1. 写入结构化 JSON
        self._write_structured(level, entry)

        # 2. 通过事件总线发布（UI 日志面板订阅）
        event_bus.publish(Events.LOG_RECORD, **entry)

    def debug(self, msg, **kw): self.log("DEBUG", msg, **kw)
    def info(self, msg, **kw): self.log("INFO", msg, **kw)
    def warning(self, msg, **kw): self.log("WARNING", msg, **kw)
    def error(self, msg, **kw): self.log("ERROR", msg, **kw)

    # ==================== 运行指标 ====================

    def record_task_start(self, task_name: str):
        self._metrics.record_start(task_name)

    def record_task_done(self, task_name: str, success: bool, duration: float):
        self._metrics.record_done(task_name, success, duration)

    def get_metrics(self, task_name: str = None) -> dict:
        if task_name:
            return self._metrics.get(task_name)
        return self._metrics.get_all()

    def get_all_metrics(self) -> dict:
        return self._metrics.get_all()

    # ==================== 异常截图 ====================

    def capture_on_error(self, task_name: str, step_name: str,
                         error: Exception, screenshot=None):
        """异常时自动截图+保存上下文。"""
        self._snapshot.capture(task_name, step_name, error, screenshot)

    # ==================== 运行报告 ====================

    def generate_daily_report(self, report_date=None) -> str:
        return self._report.generate_daily(report_date)

    def generate_weekly_report(self, week_end=None) -> str:
        return self._report.generate_weekly(week_end)

    # ==================== 内部 ====================

    def _on_task_done(self, task_name: str, success: bool, **kw):
        self.record_task_done(task_name, success, getattr(kw, "duration", 0))

    def _write_structured(self, level: str, entry: dict):
        """追加一条结构化日志到当日 JSON 文件。"""
        today = date.today().isoformat()
        filepath = os.path.join(self._structured_dir, f"{today}.jsonl")
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass  # 日志写入失败不阻断业务
