"""
01-设备连接模块

模拟器检测器（仅检测发现，不管理生命周期）。
职责:
- 扫描检测模拟器类型
- 定位 ADB 路径（macOS/Windows 平台差异化）
- 枚举多开端口
"""
from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.exceptions import DeviceNotFoundError


@dataclass
class DeviceInfo:
    """设备信息"""
    serial: str
    emulator_type: str = "unknown"  # mumu | bluestacks | ldplayer | other
    adb_port: int = 0
    name: str = ""


class EmulatorDetector:
    """模拟器检测器（只检测不管理）"""

    # 已知模拟器 ADB 端口基址（基址 + 偏移算法）
    PORT_BASES: dict[str, dict] = {
        "mumu": {"base": 16384, "count": 4, "extra": [7555]},
        "bluestacks": {"base": 5555, "count": 3, "extra": []},
        "ldplayer": {"base": 5555, "count": 2, "extra": []},
        "nox": {"base": 62001, "count": 2, "extra": []},
    }

    def __init__(self, config: Any = None):
        self._config = config
        self._adb_path: str = self._find_adb()
        self._detected_devices: list[DeviceInfo] = []

    def enumerate_ports(self, emulator_type: str) -> list[int]:
        """
        根据模拟器类型返回多开端口列表。
        使用基址+偏移算法生成（MuMu 基址 16384 每开 +1）。
        兼容固定端口列表（extra）。
        """
        info = self.PORT_BASES.get(emulator_type)
        if not info:
            return []
        ports = list(info.get("extra", []))
        base = info["base"]
        for i in range(info["count"]):
            ports.append(base + i)
        return sorted(set(ports))

    # ── ADB 路径检测 ─────────────────────────────────────────

    @staticmethod
    def _find_adb() -> str:
        """自动检测 ADB 路径（平台差异化）"""
        # 优先 PATH 中的 adb
        try:
            subprocess.run(["adb", "version"], capture_output=True, timeout=5)
            return "adb"
        except Exception:
            pass

        system = platform.system()
        if system == "Darwin":
            # macOS: MuMu 模拟器路径
            candidates = [
                "/Applications/MuMuPlayer.app/Contents/MacOS/adb",
                "/Applications/MuMuPlayerPro.app/Contents/MacOS/adb",
                "/usr/local/bin/adb",
                "/opt/homebrew/bin/adb",
            ]
        elif system == "Windows":
            candidates = [
                "C:\\Program Files\\MuMu\\emulator\\nemu\\adb.exe",
                "C:\\Program Files\\BlueStacks\\HD-Player.exe",
            ]
        else:
            candidates = ["/usr/bin/adb"]

        for path in candidates:
            if os.path.exists(path):
                return path
        return "adb"  # fallback

    def get_adb_path(self) -> str:
        """获取检测到的 ADB 路径"""
        return self._adb_path

    # ── 模拟器检测 ────────────────────────────────────────────

    def detect_all(self) -> list[DeviceInfo]:
        """检测所有模拟器设备"""
        devices = []
        for emu_type in self.PORT_BASES:
            ports = self.enumerate_ports(emu_type)
            for port in ports:
                info = self._check_port(emu_type, port)
                if info:
                    devices.append(info)
        self._detected_devices = devices
        return devices

    def _check_port(self, emu_type: str, port: int) -> DeviceInfo | None:
        """检查指定端口的模拟器"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            if result == 0:
                serial = f"127.0.0.1:{port}"
                return DeviceInfo(serial=serial, emulator_type=emu_type, adb_port=port)
        except Exception:
            pass
        return None



    @property
    def detected_devices(self) -> list[DeviceInfo]:
        return list(self._detected_devices)
