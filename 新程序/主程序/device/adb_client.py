"""
01-设备连接模块

ADBClient ADB 命令封装。
职责:
- 执行 ADB 命令
- 设备发现与状态查询
- 输入模拟（点击/滑动/文本）
"""
from __future__ import annotations

import subprocess
import threading
from typing import Any

from core.exceptions import (
    ADBError, DeviceConfigError, DeviceNotFoundError,
    DeviceOfflineError, DeviceTimeoutError, DevicePermissionError,
)


class ADBClient:
    """ADB 命令封装（每个实例绑定一个设备 serial）"""

    def __init__(
        self,
        adb_path: str = "adb",
        serial: str = "",
        platform: str = "generic",
        screenshot_timeout: float = 15.0,
        input_timeout: float = 10.0,
    ):
        self._adb_path = adb_path
        self._serial: str | None = serial or None
        self._platform = platform
        self._screenshot_timeout = screenshot_timeout
        self._input_timeout = input_timeout
        self._lock = threading.Lock()

    # ── 属性 ──────────────────────────────────────────────────

    @property
    def serial(self) -> str | None:
        return self._serial

    @serial.setter
    def serial(self, value: str) -> None:
        self._serial = value

    @property
    def adb_path(self) -> str:
        return self._adb_path

    @property
    def platform(self) -> str:
        return self._platform

    # ── 统一命令出口 ──────────────────────────────────────────

    def build_cmd(self, args: list[str]) -> list[str]:
        """构造完整 ADB 命令列表"""
        cmd = [self._adb_path]
        if self._serial:
            cmd.extend(["-s", self._serial])
        cmd.extend(args)
        return cmd

    def run(self, args: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
        """
        统一命令执行入口。
        封装子进程创建、超时控制、返回码检查、异常转换。
        """
        cmd = self.build_cmd(args)
        to = timeout if timeout is not None else self._input_timeout
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=to,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode(errors="replace").strip()
                if "device offline" in stderr.lower():
                    raise DeviceOfflineError(f"设备离线: {self._serial}")
                if "permission" in stderr.lower():
                    raise DevicePermissionError(f"ADB 权限不足: {stderr}")
                raise ADBError(f"ADB 命令失败: {' '.join(cmd)}\n{stderr}")
            return result
        except subprocess.TimeoutExpired:
            raise DeviceTimeoutError(f"ADB 命令超时({to}s): {' '.join(cmd)}")
        except FileNotFoundError:
            raise DeviceConfigError(f"ADB 未找到: {self._adb_path}")

    def raw(self, command: str, serial: str | None = None) -> str:
        """执行原始 ADB 命令（兼容旧接口）"""
        with self._lock:
            old_serial = self._serial
            if serial:
                self._serial = serial
            try:
                result = self.run(command.split())
                return result.stdout.decode(errors="replace").strip()
            finally:
                if serial:
                    self._serial = old_serial

    def shell(self, command: str, serial: str | None = None) -> str:
        """执行 shell 命令"""
        return self.raw(f"shell {command}", serial=serial)

    # ── 连接 ──────────────────────────────────────────────────

    def connect(self, serial: str | None = None) -> bool:
        """连接到设备"""
        if serial:
            self._serial = serial
        # echo() 内部带 timeout=5s 与异常兜底，返回连通性 bool
        return self.echo()

    def disconnect(self) -> None:
        """断开连接"""
        self._serial = None

    def echo(self) -> bool:
        """连通性检测（adb shell echo ok, timeout=5s）"""
        try:
            result = self.run(["shell", "echo", "ok"], timeout=5.0)
            return result.stdout.decode(errors="replace").strip() == "ok"
        except Exception:
            return False

    # ── 设备发现 ──────────────────────────────────────────────

    def list_devices(self) -> list[dict[str, str]]:
        """列出所有设备"""
        try:
            result = self.run(["devices", "-l"])
            output = result.stdout.decode(errors="replace")
            devices = []
            for line in output.split("\n")[1:]:
                if not line.strip() or "offline" in line:
                    continue
                parts = line.strip().split()
                if parts and parts[0]:
                    devices.append({
                        "serial": parts[0],
                        "status": parts[1] if len(parts) > 1 else "device",
                    })
            return devices
        except Exception:
            return []

    def get_first_device(self) -> str | None:
        devices = self.list_devices()
        for d in devices:
            if d["status"] == "device":
                return d["serial"]
        return None

    def connect_tcp(self, host: str, port: int, timeout: float = 8.0) -> bool:
        """主动 adb connect（设备不在 adb devices 中时用）。

        模拟器重启后端口可能变化（如 16416→5557），且 adb server 残留旧连接：
        仅查 adb devices 会误判"无设备"。这里对候选地址执行 connect，
        返回是否连上（connected / already connected）。
        """
        try:
            result = subprocess.run(
                [self._adb_path, "connect", f"{host}:{port}"],
                capture_output=True, timeout=timeout)
            out = (result.stdout or b"").decode(errors="replace")
            err = (result.stderr or b"").decode(errors="replace")
            text = (out + " " + err).lower()
            return ("connected to" in text or "already connected" in text)
        except Exception:
            return False

    # ── 输入模拟 ──────────────────────────────────────────────

    def tap(self, x: int, y: int) -> None:
        """点击坐标"""
        self.run(["shell", "input", "tap", str(x), str(y)], timeout=self._input_timeout)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """滑动（duration_ms 毫秒）"""
        self.run(
            ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            timeout=self._input_timeout,
        )

    def text(self, text: str) -> None:
        """输入文本（自动转义 shell 特殊字符）"""
        escaped = (
            text
            .replace("\\", "\\\\")
            .replace("$", "\\$")
            .replace('"', '\\"')
            .replace("`", "\\`")
            .replace("&", "\\&")
            .replace("!", "\\!")
            .replace(" ", "%s")
        )
        self.run(["shell", "input", "text", escaped], timeout=self._input_timeout)

    def keyevent(self, key: int) -> None:
        """发送按键事件"""
        self.run(["shell", "input", "keyevent", str(key)], timeout=self._input_timeout)

    def am_start(self, package: str, activity: str) -> bool:
        """启动 App"""
        try:
            self.run(["shell", "am", "start", "-n", f"{package}/{activity}"], timeout=15.0)
            return True
        except Exception:
            return False

    def foreground_package(self) -> str | None:
        """获取前台包名"""
        try:
            result = self.run(["shell", "dumpsys", "activity", "activities"], timeout=10.0)
            output = result.stdout.decode(errors="replace")
            for line in output.split("\n"):
                if "mResumedActivity" in line:
                    import re
                    m = re.search(r'([\w.]+)/[\w.]+', line)
                    if m:
                        return m.group(1)
            return None
        except Exception:
            return None

    # ── 系统信息 ──────────────────────────────────────────────

    def wm_size(self) -> tuple[int, int]:
        """获取屏幕分辨率"""
        try:
            result = self.run(["shell", "wm", "size"], timeout=10.0)
            output = result.stdout.decode(errors="replace")
            if "Physical size:" in output:
                size = output.split("Physical size:")[-1].strip().split("x")
                return (int(size[0]), int(size[1]))
        except Exception:
            pass
        raise DeviceConfigError("无法获取屏幕分辨率")

    def get_device_model(self) -> str:
        try:
            result = self.run(["shell", "getprop", "ro.product.model"], timeout=5.0)
            return result.stdout.decode(errors="replace").strip()
        except Exception:
            return ""

    def get_android_version(self) -> str:
        try:
            result = self.run(["shell", "getprop", "ro.build.version.release"], timeout=5.0)
            return result.stdout.decode(errors="replace").strip()
        except Exception:
            return ""

    # ── 截图 ──────────────────────────────────────────────────

    def screencap(self) -> bytes:
        """截屏（adb exec-out screencap -p 二进制流）"""
        result = self.run(["exec-out", "screencap", "-p"], timeout=self._screenshot_timeout)
        return result.stdout

    def screenshot(self, output_path: str = "/sdcard/screenshot.png") -> bytes:
        """兼容旧方法"""
        self.run(["shell", "screencap", "-p", output_path], timeout=self._screenshot_timeout)
        result = self.run(["pull", output_path, "-"], timeout=self._screenshot_timeout)
        return result.stdout

    def pull_screenshot(self, local_path: str) -> bool:
        """截屏并拉取到本地"""
        try:
            data = self.screencap()
            with open(local_path, "wb") as f:
                f.write(data)
            return True
        except Exception:
            try:
                remote = "/sdcard/screenshot_temp.png"
                self.shell(f"screencap -p {remote}")
                result = self.raw(f"pull {remote} {local_path}")
                self.shell(f"rm {remote}")
                return True
            except Exception:
                return False
