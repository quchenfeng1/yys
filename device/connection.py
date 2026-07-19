"""
连接模块主入口（01-连接模块）

封装 ADB 连接与底层设备操作，统一连接异常的抛出口。
v2.0 新增：心跳检测、自动重连、多开设备管理、连接质量监控。

对应解耦文档：模块说明/01-连接模块.md
"""

import time
import threading
from typing import Optional

import numpy as np

from core.event_bus import event_bus, Events
from core.state_manager import state_manager
from core.state_schema import StateKeys
from core.exceptions import DeviceConnectError
from device.adb_client import ADBClient
from device.heartbeat import HeartbeatMonitor


class ConnectionManager:
    """连接模块统一入口。管理多设备连接，提供设备操作。"""

    def __init__(self, config):
        self._config = config
        self._adb_clients: dict[str, ADBClient] = {}   # device_id → ADBClient
        self._active_device_id: Optional[str] = None
        self._heartbeat: Optional[HeartbeatMonitor] = None

        # 质量监控
        self._quality = ConnectionQuality()

    # ==================== 连接管理 ====================

    def connect(self, device_id: str = None) -> bool:
        """连接指定设备。未指定则连接配置中的默认设备。"""
        if device_id is None:
            device_id = self._config.get("global.adb.device_id", "127.0.0.1:16384")

        if device_id not in self._adb_clients:
            adb_path = self._config.get("global.adb.path", "adb")
            port = int(device_id.split(":")[-1]) if ":" in device_id else 5555
            client = ADBClient(device_id=device_id, adb_path=adb_path)
            self._adb_clients[device_id] = client

        client = self._adb_clients[device_id]
        if not client.connect():
            raise DeviceConnectError(f"连接设备失败: {device_id}")

        self._active_device_id = device_id
        state_manager.set_state(StateKeys.CONNECTION_STATUS, "connected")
        state_manager.set_state(StateKeys.ACTIVE_DEVICE_ID, device_id)
        return True

    def disconnect(self, device_id: str = None):
        """断开连接。"""
        did = device_id or self._active_device_id
        if did and did in self._adb_clients:
            self._adb_clients[did].disconnect()
        state_manager.set_state(StateKeys.CONNECTION_STATUS, "disconnected")

    def is_connected(self, device_id: str = None) -> bool:
        """检测连接状态。"""
        did = device_id or self._active_device_id
        if did and did in self._adb_clients:
            return self._adb_clients[did].is_connected()
        return False

    def get_active_device(self) -> ADBClient:
        """获取当前操作的设备客户端。"""
        if self._active_device_id and self._active_device_id in self._adb_clients:
            return self._adb_clients[self._active_device_id]
        raise DeviceConnectError("无活跃设备连接")

    def switch_device(self, device_id: str) -> bool:
        """切换操作目标设备（多开账号切换时调用）。"""
        if device_id not in self._adb_clients:
            return self.connect(device_id)
        if not self._adb_clients[device_id].is_connected():
            return self.connect(device_id)
        self._active_device_id = device_id
        state_manager.set_state(StateKeys.ACTIVE_DEVICE_ID, device_id)
        event_bus.publish(Events.ACCOUNT_SWITCHED, account_id=device_id)
        return True

    def preconnect(self, device_ids: list[str]):
        """预热连接多个设备（启动时调用，加速后续切换）。"""
        for did in device_ids:
            try:
                self.connect(did)
            except DeviceConnectError:
                pass  # 预热失败不阻断启动

    def get_all_device_ids(self) -> list[str]:
        """获取所有已注册的设备 ID 列表。"""
        return list(self._adb_clients.keys())

    # ==================== 设备操作（委托给当前 ADBClient）====================

    def screenshot(self) -> np.ndarray:
        start = time.time()
        img = self.get_active_device().screenshot()
        self._quality.record("screenshot", time.time() - start)
        return img

    def click(self, x: int, y: int):
        start = time.time()
        self.get_active_device().click(x, y)
        self._quality.record("click", time.time() - start)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int):
        start = time.time()
        self.get_active_device().swipe(x1, y1, x2, y2, duration)
        self._quality.record("swipe", time.time() - start)

    def input_key(self, key: str):
        self.get_active_device().input_key(key)

    def get_screen_size(self) -> tuple:
        return self.get_active_device().get_screen_size()

    # ==================== App 管理 ====================

    def launch_app(self, package: str, activity: str = None) -> bool:
        return self.get_active_device().launch_app(package, activity)

    def is_app_running(self, package: str) -> bool:
        return self.get_active_device().is_app_running(package)

    def is_app_foreground(self, package: str) -> bool:
        return self.get_active_device().is_app_foreground(package)

    # ==================== 心跳检测 ====================

    def start_heartbeat(self, interval: float = 30):
        """启动心跳检测线程。"""
        self._heartbeat = HeartbeatMonitor(
            connection=self,
            interval=interval,
            auto_reconnect=True,
        )
        self._heartbeat.start()

    def stop_heartbeat(self):
        """停止心跳检测。"""
        if self._heartbeat:
            self._heartbeat.stop()

    # ==================== 重连 ====================

    def reconnect(self, device_id: str = None) -> bool:
        """尝试重连（按退避策略 1s→2s→4s→8s→16s 重试）。"""
        did = device_id or self._active_device_id
        if not did:
            return False
        state_manager.set_state(StateKeys.CONNECTION_STATUS, "reconnecting")
        for attempt, delay in enumerate([1, 2, 4, 8, 16], start=1):
            try:
                if self.connect(did):
                    event_bus.publish(Events.CONNECTION_RESTORED, device_id=did)
                    return True
            except DeviceConnectError:
                if attempt < 5:
                    time.sleep(delay)
        return False

    # ==================== 质量监控 ====================

    def get_quality(self) -> dict:
        """获取连接质量报告。"""
        return self._quality.get_quality()


class ConnectionQuality:
    """连接质量监控。记录各操作的响应延迟。"""

    def __init__(self):
        self._latency_history: dict[str, list[float]] = {
            "screenshot": [],
            "click": [],
            "swipe": [],
        }
        self._max_history = 100

    def record(self, operation: str, duration: float):
        hist = self._latency_history.setdefault(operation, [])
        hist.append(duration)
        if len(hist) > self._max_history:
            hist.pop(0)

    def get_quality(self) -> dict:
        return {
            op: {
                "avg": sum(h) / len(h) if h else 0,
                "max": max(h) if h else 0,
                "count": len(h),
            }
            for op, h in self._latency_history.items()
        }
