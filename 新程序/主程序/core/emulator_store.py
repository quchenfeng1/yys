"""
模拟器配置存储（2026-08-16）。

config/emulators.yaml：模拟器条目库（全局共享，多窗口可见）。
条目结构：
  emulators:
    - id: mumu_01        # 唯一标识（自动生成：emu_<n> 或用户指定）
      name: MuMu主号      # 显示名
      host: 127.0.0.1     # ADB 主机
      port: 16384         # ADB 端口
      remark: ""          # 备注（可选）

serial = host:port（连接时直接用，不依赖端口扫描）。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml


class EmulatorStore:
    """模拟器条目库（yaml CRUD + 内存缓存，线程安全）。"""

    def __init__(self, config_dir: str | Path):
        self._path = Path(config_dir) / "emulators.yaml"
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self.load()

    # ── 读写 ──────────────────────────────────────────────

    def load(self) -> None:
        with self._lock:
            if self._path.exists():
                try:
                    raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
                    self._entries = list(raw.get("emulators", []) or [])
                except Exception:
                    self._entries = []
            else:
                self._entries = []
                self._save_locked()

    def _save_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                yaml.dump({"emulators": self._entries},
                          default_flow_style=False,
                          allow_unicode=True, sort_keys=False),
                encoding="utf-8")
        except Exception:
            pass

    # ── 查询 ──────────────────────────────────────────────

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._entries]

    def get(self, emu_id: str) -> dict[str, Any] | None:
        with self._lock:
            for e in self._entries:
                if e.get("id") == emu_id:
                    return dict(e)
        return None

    def serial_of(self, emu_id: str) -> str | None:
        e = self.get(emu_id)
        if not e:
            return None
        return f"{e.get('host', '127.0.0.1')}:{e.get('port', 0)}"

    # ── 变更 ──────────────────────────────────────────────

    def _next_id(self) -> str:
        max_n = 0
        for e in self._entries:
            try:
                prefix, _, n = str(e.get("id", "")).rpartition("_")
                if prefix == "emu":
                    max_n = max(max_n, int(n))
            except ValueError:
                continue
        return f"emu_{max_n + 1}"

    def add(self, name: str, host: str, port: int,
            emu_id: str | None = None, remark: str = "") -> dict[str, Any] | None:
        """新增条目（id 冲突返回 None）。"""
        with self._lock:
            emu_id = (emu_id or "").strip() or self._next_id()
            for e in self._entries:
                if e.get("id") == emu_id:
                    return None
            entry = {"id": emu_id, "name": (name or "").strip() or emu_id,
                     "host": host.strip() or "127.0.0.1", "port": int(port)}
            if remark:
                entry["remark"] = remark
            self._entries.append(entry)
            self._save_locked()
            return dict(entry)

    def update(self, emu_id: str, **fields: Any) -> bool:
        with self._lock:
            for e in self._entries:
                if e.get("id") == emu_id:
                    e.update({k: v for k, v in fields.items() if v is not None})
                    self._save_locked()
                    return True
        return False

    def remove(self, emu_id: str) -> bool:
        with self._lock:
            for i, e in enumerate(self._entries):
                if e.get("id") == emu_id:
                    self._entries.pop(i)
                    self._save_locked()
                    return True
        return False
