"""
10-参数桥接模块：SystemBridge（游戏/模拟器切换，2026-08-16 B方案）。

职责：
- 游戏切换：委托 bootstrap.switch_game（后端整体重建：调度器/注册表/素材库/
  运行控制/触发器全部换到新游戏）
- 模拟器切换：委托 bootstrap.switch_emulator（断开旧设备 → 连接新模拟器）
- 模拟器条目库 CRUD（EmulatorStore）+ 在线模拟器扫描（EmulatorDetector）

UI（MainWindow / 模拟器管理面板）只与本桥交互，不直连核心。
"""
from __future__ import annotations

from typing import Any, Callable

from core.event_bus import EventBus, get_global_bus


class SystemBridge:
    """系统级桥接：游戏与模拟器切换。"""

    def __init__(self, event_bus: EventBus | None = None):
        self._bus = event_bus or get_global_bus()
        # 注入（bootstrap）
        self._game_switcher: Callable[[str], bool] | None = None
        self._emulator_switcher: Callable[[str], bool] | None = None
        self._store: Any = None          # EmulatorStore
        self._connection: Any = None     # ConnectionManager

    # ── 注入 ─────────────────────────────────────────────

    def set_game_switcher(self, fn: Callable[[str], bool]) -> None:
        """注入后端游戏切换回调（bootstrap.switch_game）"""
        self._game_switcher = fn

    def set_emulator_switcher(self, fn: Callable[[str], bool]) -> None:
        """注入后端模拟器切换回调（bootstrap.switch_emulator）"""
        self._emulator_switcher = fn

    def set_emulator_store(self, store: Any) -> None:
        self._store = store

    def set_connection(self, conn: Any) -> None:
        self._connection = conn

    # ── 游戏切换 ─────────────────────────────────────────

    def switch_game(self, game_id: str) -> bool:
        if not game_id or self._game_switcher is None:
            return False
        try:
            return bool(self._game_switcher(game_id))
        except Exception:
            return False

    # ── 模拟器切换/连接 ──────────────────────────────────

    def switch_emulator(self, emu_id: str) -> bool:
        """切换到指定模拟器：断开旧设备 → 连接新设备。"""
        if not emu_id or self._emulator_switcher is None:
            return False
        try:
            return bool(self._emulator_switcher(emu_id))
        except Exception:
            return False

    def connect_current(self) -> bool:
        """按当前选中模拟器连接（无选择时走 ConnectionManager 自动发现）"""
        if self._connection is None:
            return False
        try:
            return bool(self._connection.connect())
        except Exception:
            return False

    def disconnect(self) -> bool:
        if self._connection is None:
            return False
        try:
            self._connection.disconnect()
            return True
        except Exception:
            return False

    # ── 模拟器条目 CRUD ──────────────────────────────────

    def emulator_list(self) -> list[dict]:
        if self._store is None:
            return []
        try:
            return self._store.list()
        except Exception:
            return []

    def get_emulator(self, emu_id: str) -> dict | None:
        if self._store is None:
            return None
        try:
            return self._store.get(emu_id)
        except Exception:
            return None

    def save_emulator(self, entry: dict) -> bool:
        """新增或更新：entry 含 id 且存在 → 更新；否则新增。"""
        if self._store is None:
            return False
        try:
            emu_id = entry.get("id", "")
            if emu_id and self._store.get(emu_id):
                return bool(self._store.update(
                    emu_id,
                    name=entry.get("name"),
                    host=entry.get("host"),
                    port=entry.get("port"),
                    remark=entry.get("remark"),
                ))
            return self._store.add(
                name=entry.get("name", ""),
                host=entry.get("host", "127.0.0.1"),
                port=int(entry.get("port", 0)),
                emu_id=emu_id or None,
                remark=entry.get("remark", ""),
            ) is not None
        except Exception:
            return False

    def delete_emulator(self, emu_id: str) -> bool:
        if self._store is None:
            return False
        try:
            return bool(self._store.remove(emu_id))
        except Exception:
            return False

    def scan_emulators(self) -> list[dict]:
        """扫描在线模拟器：[{serial, type, port}]（EmulatorDetector）"""
        try:
            from device.emulator import EmulatorDetector
            det = EmulatorDetector()
            out = []
            for info in det.detect_all(timeout=0.3):
                out.append({
                    "serial": info.serial,
                    "type": info.emulator_type,
                    "port": info.adb_port,
                    "name": info.name or info.serial,
                })
            return out
        except Exception:
            return []
