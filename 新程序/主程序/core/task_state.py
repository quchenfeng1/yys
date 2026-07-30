"""
05-时间调度模块

TaskState 执行记录持久化。
负责记录每个任务的执行历史、状态、耗时等。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TaskExecutionRecord:
    """单次任务执行记录"""
    task_id: str
    task_name: str
    status: str = "pending"  # pending | running | success | failed | skipped
    started_at: str = ""
    ended_at: str = ""
    duration: float = 0.0
    error: str = ""
    retry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskState:
    """任务执行记录管理器"""

    def __init__(self, persist_path: str | Path | None = None):
        self._lock = threading.Lock()
        self._records: dict[str, list[TaskExecutionRecord]] = {}  # task_id -> [records]
        self._current: dict[str, TaskExecutionRecord] = {}  # task_id -> current running
        self._persist_path = Path(persist_path) if persist_path else None
        self._max_records_per_task = 100

    # ── 当前运行 ──────────────────────────────────────────────

    def start_run(self, task_id: str, task_name: str = "") -> str:
        """记录任务开始执行"""
        record = TaskExecutionRecord(
            task_id=task_id,
            task_name=task_name,
            status="running",
            started_at=datetime.now().isoformat(),
        )
        with self._lock:
            self._current[task_id] = record
        return task_id

    def complete_run(
        self,
        task_id: str,
        status: str = "success",
        error: str = "",
        retry_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> TaskExecutionRecord:
        """完成任务记录"""
        with self._lock:
            record = self._current.pop(task_id, None)
            if not record:
                record = TaskExecutionRecord(task_id=task_id, task_name="")

            record.status = status
            record.ended_at = datetime.now().isoformat()
            if record.started_at:
                try:
                    start = datetime.fromisoformat(record.started_at)
                    end = datetime.fromisoformat(record.ended_at)
                    record.duration = (end - start).total_seconds()
                except Exception:
                    record.duration = 0.0
            record.error = error
            record.retry_count = retry_count
            if metadata:
                record.metadata.update(metadata)

            self._records.setdefault(task_id, []).append(record)
            if len(self._records[task_id]) > self._max_records_per_task:
                self._records[task_id].pop(0)

        self._maybe_persist()
        return record

    def fail_run(self, task_id: str, error: str = "", retry_count: int = 0) -> TaskExecutionRecord:
        """记录任务失败"""
        return self.complete_run(task_id, status="failed", error=error, retry_count=retry_count)

    def skip_run(self, task_id: str, reason: str = "") -> TaskExecutionRecord:
        """记录任务跳过"""
        return self.complete_run(task_id, status="skipped", error=reason)

    def get_current(self, task_id: str) -> TaskExecutionRecord | None:
        """获取当前运行中的记录"""
        return self._current.get(task_id)

    # ── 查询 ──────────────────────────────────────────────────

    def get_history(
        self,
        task_id: str | None = None,
        limit: int = 50,
        status: str | None = None,
    ) -> list[TaskExecutionRecord]:
        """获取执行历史"""
        with self._lock:
            if task_id:
                records = list(self._records.get(task_id, []))
            else:
                records = []
                for recs in self._records.values():
                    records.extend(recs)

            records.sort(key=lambda r: r.started_at, reverse=True)

            if status:
                records = [r for r in records if r.status == status]

            return records[:limit]

    def get_last_run(self, task_id: str) -> TaskExecutionRecord | None:
        """获取某任务最后一次执行记录"""
        records = self._records.get(task_id, [])
        return records[-1] if records else None

    def get_success_rate(self, task_id: str) -> float:
        """获取任务成功率"""
        records = self._records.get(task_id, [])
        if not records:
            return 0.0
        success = sum(1 for r in records if r.status == "success")
        return success / len(records)

    def get_total_stats(self) -> dict[str, Any]:
        """获取全局统计"""
        total = 0
        success = 0
        failed = 0
        skipped = 0
        for recs in self._records.values():
            for r in recs:
                total += 1
                if r.status == "success":
                    success += 1
                elif r.status == "failed":
                    failed += 1
                elif r.status == "skipped":
                    skipped += 1

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "success_rate": success / total if total > 0 else 0.0,
        }

    # ── 持久化 ────────────────────────────────────────────────

    def persist(self) -> None:
        """保存执行记录"""
        if not self._persist_path:
            return
        with self._lock:
            data = {}
            for task_id, records in self._records.items():
                data[task_id] = [
                    {
                        "task_id": r.task_id,
                        "task_name": r.task_name,
                        "status": r.status,
                        "started_at": r.started_at,
                        "ended_at": r.ended_at,
                        "duration": r.duration,
                        "error": r.error,
                        "retry_count": r.retry_count,
                        "metadata": r.metadata,
                    }
                    for r in records
                ]

        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._persist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def load_persisted(self) -> bool:
        """加载执行记录"""
        if not self._persist_path or not self._persist_path.exists():
            return False
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                for task_id, records_data in data.items():
                    self._records[task_id] = [
                        TaskExecutionRecord(**r) for r in records_data
                    ]
            return True
        except Exception:
            return False

    def _maybe_persist(self) -> None:
        if self._persist_path:
            self.persist()


# ═══════════════════════════════════════════════════════════════
#  TaskStateStore（§5.3 + §4.3 原子持久化）
#  设计书要求：task_state.py ← TaskState + TaskStateStore
# ═══════════════════════════════════════════════════════════════

class TaskStateStore:
    """
    调度状态持久化（§5.3 + §4.3 原子持久化）。

    路径：config/runtime/task_state.json
    写策略：tempfile.mkstemp() + os.replace() 原子写盘
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self.data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        """从磁盘加载执行记录（§3.6 异常恢复①②）"""
        if not self._path.exists():
            self.data = {}
            return self.data
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except json.JSONDecodeError:
            # §3.6 ① JSON 损坏 → 初始化空状态
            self.data = {}
        return self.data

    def get(self, task_name: str) -> dict[str, Any] | None:
        """获取单个任务状态"""
        return self.data.get(task_name)

    def get_or_create(self, task_name: str) -> dict[str, Any]:
        """获取或创建任务状态"""
        if task_name not in self.data:
            self.data[task_name] = {
                "task_name": task_name,
                "next_run_time": "",
                "today_count": 0,
                "fail_streak": 0,
                "last_done": "",
                "last_status": "",
                "skip_reason": "",
                "updated": datetime.now().isoformat(),
            }
        return self.data[task_name]

    def update(self, task_name: str, **kwargs: Any) -> None:
        """更新任务状态字段"""
        entry = self.get_or_create(task_name)
        entry.update(kwargs)
        entry["updated"] = datetime.now().isoformat()

    def save(self, data: dict[str, Any] | None = None) -> None:
        """原子写盘（§4.3 tempfile.mkstemp + os.replace）"""
        if data is not None:
            self.data = data

        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            suffix=".json", prefix=f".{self._path.name}.",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(self._path))
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise
