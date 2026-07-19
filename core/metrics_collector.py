"""
运行指标收集器（12-日志与监控模块 子模块）

自动统计各任务执行次数、成功率、平均耗时。
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TaskStats:
    """单个任务的运行统计。"""
    name: str
    total_runs: int = 0
    success_runs: int = 0
    fail_runs: int = 0
    total_duration: float = 0.0
    avg_duration: float = 0.0
    last_run_time: str = ""

    def record_start(self):
        self._start_time = datetime.now()

    def record_done(self, success: bool, duration: float = 0):
        self.total_runs += 1
        if success:
            self.success_runs += 1
        else:
            self.fail_runs += 1
        self.total_duration += duration
        self.avg_duration = self.total_duration / self.total_runs if self.total_runs > 0 else 0
        self.last_run_time = datetime.now().isoformat()

    def summary(self) -> dict:
        return {
            "name": self.name,
            "total_runs": self.total_runs,
            "success_runs": self.success_runs,
            "fail_runs": self.fail_runs,
            "success_rate": round(self.success_runs / self.total_runs * 100, 1) if self.total_runs > 0 else 0,
            "avg_duration": round(self.avg_duration, 2),
            "total_duration": round(self.total_duration, 2),
            "last_run_time": self.last_run_time,
        }


class MetricsCollector:
    """运行指标收集与统计。"""

    def __init__(self):
        self._task_stats: dict[str, TaskStats] = {}

    def record_start(self, task_name: str):
        if task_name not in self._task_stats:
            self._task_stats[task_name] = TaskStats(task_name)
        self._task_stats[task_name].record_start()

    def record_done(self, task_name: str, success: bool, duration: float = 0):
        if task_name not in self._task_stats:
            self._task_stats[task_name] = TaskStats(task_name)
        self._task_stats[task_name].record_done(success, duration)

    def get(self, task_name: str) -> dict:
        return self._task_stats[task_name].summary() if task_name in self._task_stats else {}

    def get_all(self) -> dict:
        return {name: stats.summary() for name, stats in self._task_stats.items()}
