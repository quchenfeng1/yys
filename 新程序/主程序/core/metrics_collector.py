"""
12-日志监控中心

运行指标收集器。
职责:
- 收集运行时性能指标
- 操作频率/成功率统计
- 提供指标查询接口
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricsSnapshot:
    """指标快照"""
    timestamp: float
    task_count: int
    success_count: int
    fail_count: int
    avg_duration: float
    action_rate: float


class MetricsCollector:
    """运行指标收集器"""

    def __init__(self, window_size: int = 3600):
        self._lock = threading.Lock()
        self._window_size = window_size  # 统计窗口（秒）

        # 操作统计 {action_name: [(timestamp, success)]}
        self._actions: dict[str, list[tuple[float, bool]]] = defaultdict(list)

        # 任务耗时
        self._durations: list[float] = []
        self._max_durations = 1000

        # 系统指标
        self._start_time = time.time()

    # ── 记录 ──────────────────────────────────────────────────

    def record_action(self, action: str, success: bool = True) -> None:
        """记录一次操作"""
        with self._lock:
            self._actions[action].append((time.time(), success))
            self._trim()

    def record_duration(self, duration: float) -> None:
        """记录耗时"""
        with self._lock:
            self._durations.append(duration)
            if len(self._durations) > self._max_durations:
                self._durations.pop(0)

    def record_task_completed(self, duration: float, success: bool = True) -> None:
        """记录任务完成"""
        self.record_action("task", success)
        self.record_duration(duration)

    def _trim(self) -> None:
        """清理超时窗口外的数据"""
        cutoff = time.time() - self._window_size
        for action in self._actions:
            self._actions[action] = [
                (t, s) for t, s in self._actions[action] if t > cutoff
            ]

    # ── 查询 ──────────────────────────────────────────────────

    def get_action_count(self, action: str | None = None) -> int:
        """获取操作次数"""
        with self._lock:
            self._trim()
            if action:
                return len(self._actions.get(action, []))
            return sum(len(v) for v in self._actions.values())

    def get_success_rate(self, action: str | None = None) -> float:
        """获取成功率"""
        with self._lock:
            self._trim()
            if action:
                records = self._actions.get(action, [])
            else:
                records = [r for rs in self._actions.values() for r in rs]

            if not records:
                return 1.0
            success = sum(1 for _, s in records if s)
            return success / len(records)

    def get_action_rate(self, action: str | None = None) -> float:
        """获取操作频率（次/分钟）"""
        with self._lock:
            self._trim()
            if action:
                count = len(self._actions.get(action, []))
            else:
                count = sum(len(v) for v in self._actions.values())
            return count / (self._window_size / 60)

    def get_avg_duration(self) -> float:
        """获取平均耗时"""
        with self._lock:
            if not self._durations:
                return 0.0
            return sum(self._durations) / len(self._durations)

    def get_snapshot(self) -> MetricsSnapshot:
        """获取当前指标快照"""
        return MetricsSnapshot(
            timestamp=time.time(),
            task_count=self.get_action_count("task"),
            success_count=int(self.get_action_count("task") * self.get_success_rate("task")),
            fail_count=int(self.get_action_count("task") * (1 - self.get_success_rate("task"))),
            avg_duration=self.get_avg_duration(),
            action_rate=self.get_action_rate(),
        )

    def get_summary(self) -> dict[str, Any]:
        """获取汇总数据"""
        snap = self.get_snapshot()
        return {
            "uptime": time.time() - self._start_time,
            "total_actions": self.get_action_count(),
            "task_count": snap.task_count,
            "success_rate": self.get_success_rate(),
            "avg_duration": snap.avg_duration,
            "action_rate": snap.action_rate,
        }

    def reset(self) -> None:
        """重置所有指标"""
        with self._lock:
            self._actions.clear()
            self._durations.clear()
            self._start_time = time.time()
