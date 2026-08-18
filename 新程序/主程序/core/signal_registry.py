"""
信号注册表（2026-08-16 信号体系）：信号管理面板数据源。

三类信号：
- 场景信号：场景素材（SceneStore）附带的 signal 字段（{scene_id, signal}）
- 任务信号：可视化任务图内「任务信号输出/接收」节点的 signal 参数（{task, signal}）
- 触发信号：可视化任务图内「任务信号触发器」节点的 signal 参数（{task, signal}）

自定义信号（用户手工添加、不绑定任务的信号名）持久化在
games/{game}/runtime/signals.json 的 custom 列表，供节点下拉候选。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class SignalRegistry:
    """信号注册表（扫描式 + 自定义信号持久化）。"""

    def __init__(self, runtime_dir: str | Path,
                 scene_store: Any = None,
                 visual_store: Any = None):
        self._path = Path(runtime_dir) / "signals.json"
        self._scene_store = scene_store
        self._visual_store = visual_store
        self._lock = threading.Lock()
        self._custom: list[str] = []
        self._load_custom()

    def _load_custom(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._custom = [str(x) for x in data.get("custom", [])]
        except Exception:
            self._custom = []

    def _save_custom_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"custom": self._custom},
                                      ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self._path)
        except Exception:
            pass

    # ── 扫描 ──────────────────────────────────────────────

    @staticmethod
    def _graph_signals(defn: dict, node_type: str) -> set[str]:
        out: set[str] = set()
        try:
            for n in (defn.get("graph", {}) or {}).get("nodes", []):
                if n.get("type") != node_type:
                    continue
                sig = str((n.get("params", {}) or {}).get("signal", "") or "")
                if sig:
                    out.add(sig)
        except Exception:
            pass
        return out

    def scene_signals(self) -> list[dict]:
        """场景信号 [{scene_id, signal}]（signal 为空的不计，非触发素材）。"""
        out: list[dict] = []
        if self._scene_store is None:
            return out
        try:
            for sc in self._scene_store.list():
                sig = (sc.get("signal") or "").strip()
                if sig:
                    out.append({"scene_id": sc.get("id", ""), "signal": sig})
        except Exception:
            pass
        return out

    def task_signals(self) -> list[dict]:
        """任务信号 [{task, signal}]：任务信号输出/接收节点。"""
        out: list[dict] = []
        if self._visual_store is None:
            return out
        try:
            for meta in self._visual_store.list():
                try:
                    defn = self._visual_store.load(meta["name"])
                except Exception:
                    continue
                for t in ("task_signal_out", "task_signal_in"):
                    for sig in self._graph_signals(defn, t):
                        out.append({"task": meta["name"], "signal": sig})
        except Exception:
            pass
        return out

    def trigger_signals(self) -> list[dict]:
        """触发信号 [{task, signal}]：任务信号触发器节点。"""
        out: list[dict] = []
        if self._visual_store is None:
            return out
        try:
            for meta in self._visual_store.list():
                try:
                    defn = self._visual_store.load(meta["name"])
                except Exception:
                    continue
                for sig in self._graph_signals(defn, "task_signal_trigger"):
                    out.append({"task": meta["name"], "signal": sig})
        except Exception:
            pass
        return out

    def task_signal_names(self) -> list[str]:
        """全部任务信号名（去重，供节点下拉/信号管理展示）。"""
        names: set[str] = set()
        for r in self.task_signals():
            names.add(r["signal"])
        return sorted(names)

    def trigger_signal_names(self) -> list[str]:
        names: set[str] = set()
        for r in self.trigger_signals():
            names.add(r["signal"])
        return sorted(names)

    # ── 自定义信号 ────────────────────────────────────────

    def custom_signals(self) -> list[str]:
        with self._lock:
            return list(self._custom)

    def add_custom(self, signal: str) -> bool:
        signal = (signal or "").strip()
        if not signal:
            return False
        with self._lock:
            if signal in self._custom:
                return False
            self._custom.append(signal)
            self._save_custom_locked()
            return True

    def remove_custom(self, signal: str) -> bool:
        with self._lock:
            if signal not in self._custom:
                return False
            self._custom.remove(signal)
            self._save_custom_locked()
            return True
