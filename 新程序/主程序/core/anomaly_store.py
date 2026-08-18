"""
异常记录与异常任务状态（2026-08-16 信号体系）。

存储：games/{game}/runtime/anomalies.json
- 每次任务异常（重复场景/等待超时等）追加一条记录（含已处理标记）
- 任务存在"未确认修复"的异常 → 该任务被标记为异常任务，不进入任何队列，
  直到用户在「异常任务」面板确认修复

异常任务面板交互（设计 v7）：
- 任务列表带「已修复」按钮（全部异常已处理才能点）
- 点任务看异常履历（最新在上），每条带「处理」按钮 → 点击后变「已处理」
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class AnomalyStore:
    """异常记录存储（线程安全，原子写盘）。"""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"anomalies": [], "unfixed": []}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if self._path.exists():
                try:
                    self._data = json.loads(self._path.read_text(encoding="utf-8"))
                except Exception:
                    self._data = {"anomalies": [], "unfixed": []}
            self._data.setdefault("anomalies", [])
            self._data.setdefault("unfixed", [])

    def _save_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self._path)
        except Exception:
            pass

    # ── 记录 ──────────────────────────────────────────────

    def record(self, task_name: str, reason: str, node_id: str = "",
               signal: str = "", at: float | None = None) -> dict:
        """追加一条异常记录，并把任务加入未确认修复列表。"""
        entry = {
            "id": uuid.uuid4().hex[:12],
            "task": task_name,
            "time": time.strftime("%Y-%m-%d %H:%M:%S",
                                  time.localtime(at or time.time())),
            "reason": reason,
            "node_id": node_id,
            "signal": signal,
            "handled": False,
        }
        with self._lock:
            self._data["anomalies"].append(entry)
            if task_name not in self._data["unfixed"]:
                self._data["unfixed"].append(task_name)
            self._save_locked()
        return dict(entry)

    # ── 查询 ──────────────────────────────────────────────

    def list(self, task_name: str | None = None) -> list[dict]:
        """异常履历（新→旧，按插入倒序）；可按任务过滤。"""
        with self._lock:
            items = [dict(a) for a in self._data["anomalies"]]
        if task_name:
            items = [a for a in items if a.get("task") == task_name]
        return list(reversed(items))

    def is_task_abnormal(self, task_name: str) -> bool:
        with self._lock:
            return task_name in self._data["unfixed"]

    def abnormal_tasks(self) -> list[str]:
        with self._lock:
            return list(self._data["unfixed"])

    # ── 处理/修复 ─────────────────────────────────────────

    def mark_handled(self, anomaly_id: str) -> bool:
        """标记单条异常为已处理。"""
        with self._lock:
            for a in self._data["anomalies"]:
                if a.get("id") == anomaly_id:
                    a["handled"] = True
                    self._save_locked()
                    return True
        return False

    def confirm_fixed(self, task_name: str) -> bool:
        """确认修复：任务退出异常列表（重新可被调度）。"""
        with self._lock:
            if task_name not in self._data["unfixed"]:
                return False
            self._data["unfixed"].remove(task_name)
            self._save_locked()
            return True

    def unresolved_count(self, task_name: str) -> int:
        """任务尚未处理的异常条数（确认修复的前置检查）。"""
        with self._lock:
            return sum(1 for a in self._data["anomalies"]
                       if a.get("task") == task_name and not a.get("handled"))
