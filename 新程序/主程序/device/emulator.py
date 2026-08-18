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
    # MuMu 新版（nx_device）：每开一个实例端口 +32（16384/16416/16448...），
    # 部分版本/环境还见过 7555、5557（模拟器重启后端口可能漂移）。
    PORT_BASES: dict[str, dict] = {
        "mumu": {"base": 16384, "count": 4, "step": 32,
                 "extra": [7555, 5557]},
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
        使用基址+步长算法生成（MuMu 新版每开 +32），并兼容固定端口（extra）。
        同类型若存在旧版 +1 方案（step>1 时），一并生成 base+i 防漏。
        """
        info = self.PORT_BASES.get(emulator_type)
        if not info:
            return []
        ports = list(info.get("extra", []))
        base = info["base"]
        step = info.get("step", 1)
        for i in range(info["count"]):
            ports.append(base + step * i)
            if step != 1:
                ports.append(base + i)
        return sorted(set(ports))

    # ── ADB 路径检测 ─────────────────────────────────────────

    @staticmethod
    def _find_adb() -> str:
        """自动检测 ADB 路径（平台差异化）

        Windows 下不探测 PATH：System32 可能存在残缺 adb.exe（缺 AdbWinApi.dll），
        执行时会弹系统错误框；直接走模拟器候选路径。
        """
        system = platform.system()
        # 非 Windows：优先 PATH 中的 adb（必须真正可执行）
        if system != "Windows":
            try:
                r = subprocess.run(["adb", "version"], capture_output=True,
                                   timeout=5)
                if r.returncode == 0 and (r.stdout or b"").strip():
                    return "adb"
            except Exception:
                pass

        if system == "Darwin":
            # macOS: MuMu 模拟器路径
            # 说明书：/Applications/MuMu.app/Contents/MacOS/tools/adb
            candidates = [
                "/Applications/MuMu.app/Contents/MacOS/tools/adb",
                "/Applications/MuMuPlayer.app/Contents/MacOS/adb",
                "/Applications/MuMuPlayerPro.app/Contents/MacOS/adb",
                "/usr/local/bin/adb",
                "/opt/homebrew/bin/adb",
            ]
        elif system == "Windows":
            # MuMu 12/15：nx_device shell adb / nx_main adb；老版本 emulator\nemu
            candidates = [
                "C:\\Program Files\\Netease\\MuMu\\nx_device\\15.0\\shell\\adb.exe",
                "C:\\Program Files\\Netease\\MuMu\\nx_main\\adb.exe",
                "C:\\Program Files\\MuMu\\emulator\\nemu\\EmulatorShell\\adb.exe",
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

    def detect_all(self, timeout: float = 0.3) -> list[DeviceInfo]:
        """检测所有模拟器设备（并行探测，未监听端口在虚拟网卡上会吃满超时，
        串行最坏 30s+ 会把启动卡住 → 2026-08-16 改为 0.3s 超时 + 线程池）。"""
        devices: list[DeviceInfo] = []
        targets: list[tuple[str, int]] = []
        for emu_type in self.PORT_BASES:
            for port in self.enumerate_ports(emu_type):
                targets.append((emu_type, port))
        if not targets:
            return devices
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=8) as ex:
                for info in ex.map(
                        lambda t: self._check_port(t[0], t[1], timeout),
                        targets):
                    if info:
                        devices.append(info)
        except Exception:
            for emu_type, port in targets:
                info = self._check_port(emu_type, port, timeout)
                if info:
                    devices.append(info)
        self._detected_devices = devices
        return devices

    def _check_port(self, emu_type: str, port: int,
                    timeout: float = 0.3) -> DeviceInfo | None:
        """检查指定端口的模拟器"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
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
