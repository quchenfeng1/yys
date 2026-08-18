"""17-可视化构建模块：可调用变量持久化（2026-08-16）。

可调用变量 = 变量组中勾选「可调用」的变量，由「参数处理」节点在运行时
改变。值跨运行保留（不按日期重置，无累计/失效语义），所见即所得。

- 存储：每任务一个 JSON（runtime/callable_vars/{task}.json）
- 写盘：内存即时更新 + 节流写盘（默认 1s 一次）+ flush() 兜底
  （任务结束/异常时调用，崩溃最多丢最近 1s 的累计）
- UI 同步：update() 时经事件总线发布 CALLABLE_VAR_CHANGED
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable


class CallableVarStore:
    """单任务可调用变量存储（内存 + 节流持久化）。"""

    def __init__(self, task_id: str, storage_dir: str | Path,
                 flush_interval: float = 1.0,
                 publish: Callable | None = None):
        self.task_id = task_id
        self._path = Path(storage_dir) / f"{task_id}.json"
        self._interval = flush_interval
        self._publish = publish   # (task_id, key, value) -> None
        self._values: dict[str, Any] = {}
        self._dirty = False
        self._last_flush = 0.0
        self._lock = threading.Lock()
        self.load()

    def load(self) -> dict:
        """从磁盘读入（不存在/损坏 → 空）。"""
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    with self._lock:
                        self._values = data
        except Exception:
            with self._lock:
                self._values = {}
        with self._lock:
            return dict(self._values)

    def snapshot(self) -> dict:
        """当前值副本（供任务启动时作为外部参数覆盖注入）。"""
        with self._lock:
            return dict(self._values)

    def update(self, key: str, value: Any) -> None:
        """更新一个变量：内存即时 + 节流写盘 + 发布 UI 同步事件。"""
        with self._lock:
            self._values[key] = value
            self._dirty = True
        self._maybe_flush()
        if self._publish is not None:
            try:
                self._publish(self.task_id, key, value)
            except Exception:
                pass

    def _maybe_flush(self) -> None:
        now = time.time()
        if now - self._last_flush >= self._interval:
            self.flush()

    def flush(self) -> None:
        """强制写盘（任务结束/异常时兜底）。"""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".json.tmp")
                tmp.write_text(
                    json.dumps(self._values, ensure_ascii=False, indent=2),
                    encoding="utf-8")
                tmp.replace(self._path)
                self._dirty = False
                self._last_flush = time.time()
            except Exception:
                pass
