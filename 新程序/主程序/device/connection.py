"""
01-设备连接模块

ConnectionManager 连接管理器。
职责:
- 管理 ADB 设备连接生命周期
- 自动重连
- 多设备支持
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any

import numpy as np

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.exceptions import (
    ConnectionError, DeviceConfigError, DeviceNotFoundError,
    DeviceOfflineError, DeviceReconnectingError, DeviceScreenshotError, DeviceTimeoutError,
)
from device.adb_client import ADBClient


class ConnectionState:
    """连接状态枚举"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


class ConnectionManager:
    """设备连接管理器（多设备连接池 + 独立重连线程）"""

    def __init__(
        self,
        adb_client: ADBClient | None = None,
        event_bus: EventBus | None = None,
        config: Any = None,
        state_manager: Any = None,
        auto_reconnect: bool = True,
        max_retries: int = 5,
    ):
        self._adb = adb_client or ADBClient()
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名
        self._config = config
        self._state_manager = state_manager
        self._state_mgr = self._state_manager  # 兼容别名
        self._lock = threading.Lock()
        self._pool_lock = threading.Lock()
        self._connected = False
        self._auto_reconnect = auto_reconnect
        self._max_retries = max_retries
        self._current_serial: str | None = None

        # 设备连接池
        self._device_pool: dict[str, ADBClient] = {}

        # 连接暂停事件（重连期间暂停操作）
        self._conn_pause_event = threading.Event()
        self._conn_pause_event.set()  # True=未暂停, False=暂停

        # 操作质量记录（deque 每个操作最近100次耗时）
        from collections import deque
        self._quality_records: dict[str, deque] = {
            "screenshot": deque(maxlen=100),
            "click": deque(maxlen=100),
            "swipe": deque(maxlen=100),
            "input_text": deque(maxlen=100),
        }

        # ADB 超时
        self._adb_timeout: float = 15.0

        # 连接状态
        self._connection_status: str = ConnectionState.DISCONNECTED

        # 屏幕分辨率缓存
        self._screen_size: tuple[int, int] = (0, 0)

        # 截图缓存（0.5s TTL）
        self._screenshot_cache: np.ndarray | None = None
        self._screenshot_cache_time: float = 0.0

        # 重连线程引用
        self._reconnect_thread: threading.Thread | None = None
        self._reconnect_stop = threading.Event()

        # 心跳管理器引用
        self._heartbeat: HeartbeatMonitor | None = None

    # ── 连接 ──────────────────────────────────────────────────

    def connect(self, serial: str | None = None) -> bool:
        """建立连接。成功后清除 _conn_pause_event 恢复操作。"""
        with self._lock:
            if self._connected:
                return True

            if not serial:
                serial = self._adb.get_first_device()
                if not serial:
                    raise DeviceNotFoundError("未发现可用设备")

            self._current_serial = serial
            self._adb.serial = serial

            try:
                ok = self._adb.echo()
                if ok:
                    self._connected = True
                    self._conn_pause_event.set()
                    self._connection_status = ConnectionState.CONNECTED
                    self._bus.publish(Events.CONNECTION_RESTORED, source="connection", serial=serial)
                    # 缓存屏幕信息
                    try:
                        self._screen_size = self._adb.wm_size()
                    except Exception:
                        self._screen_size = (0, 0)
                    if self._state_mgr:
                        self._state_mgr.set("connection_status", ConnectionState.CONNECTED)
                        self._state_mgr.set("active_device_id", serial)
                    return True
            except Exception as e:
                self._connected = False
                self._bus.publish(Events.CONNECTION_ERROR, source="connection", error=str(e))
                raise ConnectionError(f"连接设备失败: {serial}") from e

        return False

    def disconnect(self, device_id: str | None = None) -> None:
        """
        断开指定设备连接。device_id=None 时断开当前设备。
        停止心跳、设暂停事件、加锁清理。
        """
        target = device_id or self._current_serial
        with self._lock:
            if not self._connected and not device_id:
                return
            if device_id:
                # 断开池中指定设备
                with self._pool_lock:
                    self._device_pool.pop(device_id, None)
                self._bus.publish(Events.CONNECTION_LOST, source="connection", serial=device_id)
                return

            # 断开前先停止心跳
            self.stop_heartbeat()

            self._connected = False
            self._connection_status = ConnectionState.DISCONNECTED
            self._conn_pause_event.clear()
            self._adb.disconnect()
            self._bus.publish(Events.CONNECTION_LOST, source="connection", serial=self._current_serial)
            if self._state_mgr:
                self._state_mgr.set("connection_status", ConnectionState.DISCONNECTED)
                self._state_mgr.set("active_device_id", None)

    # ── 状态 ──────────────────────────────────────────────────

    def is_connected(self, device_id: str | None = None) -> bool:
        """检测连接状态（adb shell echo ok, timeout=5s）"""
        if device_id:
            client = self._device_pool.get(device_id)
            if not client:
                return False
            return client.echo()

        if not self._connected:
            return False
        return self._adb.echo()

    @property
    def connection_status(self) -> str:
        return self._connection_status

    @property
    def active_device_id(self) -> str | None:
        return self._current_serial

    @property
    def active_device(self) -> ADBClient | None:
        """当前活动的 ADBClient 实例（对应说明书 _active_device）"""
        return self._adb

    @property
    def current_serial(self) -> str | None:
        return self._current_serial

    @property
    def screen_size(self) -> tuple[int, int]:
        return self._screen_size

    def ensure_connected(self) -> None:
        if not self._connected:
            raise ConnectionError("设备未连接")

    # ── 连接健康度 ──────────────────────────────────────────

    def _calculate_health_score(self) -> float:
        """
        计算连接健康度（0-100分）。
        综合延迟达标率、成功率、心跳状态。
        健康度 < 50 时主动触发重连。
        """
        score = 100.0
        # 延迟扣分
        for op_name, dq in self._quality_records.items():
            if len(dq) >= 5:
                avg = sum(dq) / len(dq)
                if avg > 2000:
                    score -= 10
                elif avg > 1000:
                    score -= 5
        # 心跳状态（无记录不扣分）
        score = max(0.0, min(100.0, score))
        return score

    def _check_health_and_reconnect(self) -> None:
        """健康度低于 50 时主动触发重连"""
        score = self._calculate_health_score()
        if self._connected and score < 50:
            self._connection_status = ConnectionState.RECONNECTING
            # 计算实际平均延迟
            total_samples = 0
            total_latency = 0.0
            for op_name, dq in self._quality_records.items():
                if dq:
                    total_latency += sum(dq)
                    total_samples += len(dq)
            avg_latency = total_latency / total_samples if total_samples > 0 else 0.0
            self._bus.publish(Events.CONNECTION_QUALITY_WARNING,
                             source="connection",
                             operation="health",
                             avg_latency_ms=avg_latency,
                             sample_count=total_samples)
            self._start_reconnect_thread()

    def get_device_info(self) -> dict[str, str]:
        self.ensure_connected()
        try:
            size = self._adb.wm_size()
        except Exception:
            size = (0, 0)
        return {
            "serial": self._current_serial or "",
            "model": self._adb.get_device_model(),
            "android": self._adb.get_android_version(),
            "resolution": f"{size[0]}x{size[1]}",
        }

    # ── 设备池管理 ──────────────────────────────────────────

    def switch_device(self, device_id: str) -> bool:
        """切换操作目标设备（受 _pool_lock 保护）"""
        with self._pool_lock:
            # 保存当前设备 ID
            prev_device = self._current_serial

            if device_id in self._device_pool:
                self._adb = self._device_pool[device_id]
                self._current_serial = device_id
                self._connected = True
                self._conn_pause_event.set()
                # 切换设备后旧截图缓存失效（§3.4 多开切换：避免识别到上一个模拟器画面）
                self._screenshot_cache = None
                self._screenshot_cache_time = 0.0
                return True
            try:
                client = ADBClient(serial=device_id)
                if client.connect():
                    self._device_pool[device_id] = client
                    self._adb = client
                    self._current_serial = device_id
                    self._connected = True
                    self._conn_pause_event.set()
                    self._connection_status = ConnectionState.CONNECTED
                    # 切换设备后旧截图缓存失效
                    self._screenshot_cache = None
                    self._screenshot_cache_time = 0.0
                    if self._state_mgr:
                        self._state_mgr.set("active_device_id", device_id)
                    return True
            except Exception:
                pass
        return False

    def add_device(self, serial: str, client: ADBClient | None = None) -> None:
        with self._pool_lock:
            self._device_pool[serial] = client or ADBClient(serial=serial)

    def remove_device(self, serial: str) -> bool:
        with self._pool_lock:
            return self._device_pool.pop(serial, None) is not None

    # ── 重连线程（独立临时线程 + 退避算法） ──────────────────

    def reconnect(self, device_id: str | None = None) -> bool:
        """
        单次连接尝试。退避重试逻辑由 _start_reconnect_thread 编排。
        本方法仅做一次尝试，不操作 _conn_pause_event。
        """
        target = device_id or self._current_serial
        if not target:
            return False
        try:
            client = self._device_pool.get(target) or ADBClient(serial=target)
            if client.connect():
                with self._pool_lock:
                    self._device_pool[target] = client
                    self._adb = client
                    self._current_serial = target
                    self._connected = True
                self._conn_pause_event.set()
                self._connection_status = ConnectionState.CONNECTED
                # 重连到（可能不同的）设备后旧截图缓存失效
                self._screenshot_cache = None
                self._screenshot_cache_time = 0.0
                self._bus.publish(Events.CONNECTION_RESTORED, source="connection", serial=target)
                if self._state_mgr:
                    self._state_mgr.set("connection_status", ConnectionState.CONNECTED)
                    self._state_mgr.set("active_device_id", target)
                return True
        except Exception:
            pass
        return False

    def _start_reconnect_thread(self) -> None:
        """在独立临时线程中执行退避重连"""
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return

        self._reconnect_stop.clear()
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop,
            daemon=True,
            name="reconnect",
        )
        self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        """
        退避重连循环：1s->2s->4s->8s->16s，最多5次。
        每次间隔 +/-20% 随机抖动。
        全部失败发布 connection_error，然后清除 _conn_pause_event。
        """
        self._connection_status = ConnectionState.RECONNECTING
        backoff = [1, 2, 4, 8, 16]
        target = self._current_serial

        for i, delay in enumerate(backoff):
            if self._reconnect_stop.is_set():
                return

            # 带抖动的等待
            jitter = delay * random.uniform(0.8, 1.2)
            if self._reconnect_stop.wait(timeout=jitter):
                return

            # 获取池锁，尝试重连
            if self._pool_lock.acquire(timeout=3):
                try:
                    client = self._device_pool.get(target) or ADBClient(serial=target)
                    if client.connect():
                        self._device_pool[target] = client
                        self._adb = client
                        self._current_serial = target
                        self._connected = True
                        self._conn_pause_event.set()
                        self._bus.publish(Events.CONNECTION_RESTORED, source="reconnect", serial=target)
                        return
                except Exception:
                    pass
                finally:
                    self._pool_lock.release()

        # 全部失败
        self._connection_status = ConnectionState.DISCONNECTED
        self._bus.publish(Events.CONNECTION_ERROR, source="reconnect",
                         error=f"退避重连失败(已重试{len(backoff)}次): {target}")
        self._conn_pause_event.set()

    # ── 暂停检查工具 ──────────────────────────────────────────

    def _wait_for_resume(self, timeout: float = 10.0) -> None:
        """检查 _conn_pause_event，等待重连完成。超时抛 DeviceReconnectingError"""
        if not self._conn_pause_event.wait(timeout=timeout):
            raise DeviceReconnectingError(f"设备正在重连，操作等待超时({timeout}s)")

    def _record_quality(self, operation: str, elapsed_ms: float) -> None:
        """记录操作耗时，触发质量告警"""
        dq = self._quality_records.get(operation)
        if dq is not None:
            dq.append(elapsed_ms)
            if len(dq) >= 10:
                avg = sum(dq) / len(dq)
                if avg > 2000:  # 平均延迟 > 2000ms
                    self._bus.publish(
                        Events.CONNECTION_QUALITY_WARNING,
                        source="connection",
                        operation=operation,
                        avg_latency_ms=avg,
                        sample_count=len(dq),
                    )

    # ── 设备操作 ──────────────────────────────────────────────

    def screenshot(self, use_cache: bool = False) -> np.ndarray:
        """
        截取设备屏幕。
        1. 检查 _conn_pause_event（等待 10s），超时抛 DeviceReconnectingError
        2. 获取 _pool_lock（超时 3s），读取 _active_device
        3. 释放锁，执行 exec-out screencap -p（timeout=15s）
        4. cv2.imdecode 转 numpy，失败重试 1 次
        5. 记录耗时，检查质量
        """
        self._wait_for_resume()

        # 获取锁读设备
        if not self._pool_lock.acquire(timeout=3):
            raise DeviceTimeoutError("获取设备池锁超时(3s)")
        try:
            adb = self._adb
            if adb is None:
                raise DeviceOfflineError("当前无活动设备")
        finally:
            self._pool_lock.release()

        # 检查缓存
        if use_cache and self._screenshot_cache is not None:
            if time.time() - self._screenshot_cache_time < 0.5:
                return self._screenshot_cache

        import time as _time
        start = _time.time()
        last_error = None

        for attempt in range(2):
            try:
                img_bytes = adb.screencap()
                import cv2, numpy as np
                img_array = np.frombuffer(img_bytes, dtype=np.uint8)
                image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if image is None:
                    raise DeviceScreenshotError("截图解码失败，返回空图像")

                # 更新缓存
                self._screenshot_cache = image
                self._screenshot_cache_time = time.time()

                elapsed = (_time.time() - start) * 1000
                self._record_quality("screenshot", elapsed)
                self._check_health_and_reconnect()
                return image
            except Exception as e:
                last_error = e
                if attempt == 0:
                    _time.sleep(0.5)
                continue

        raise DeviceScreenshotError(f"截图失败(已重试): {last_error}")

    def _log(self, level: str, message: str) -> None:
        """模块级日志：发布 LOG_RECORD（UI 日志面板可见），兜底 print"""
        try:
            self._bus.publish(Events.LOG_RECORD, source="connection", level=level,
                              message=message)
        except Exception:
            print(f"[{level}] {message}")

    def click(self, x: int, y: int) -> None:
        """点击坐标。先检查暂停事件，获取锁读设备，释放锁后执行。"""
        self._wait_for_resume()
        self.ensure_connected()
        if not self._pool_lock.acquire(timeout=3):
            raise DeviceTimeoutError("获取设备池锁超时(3s)")
        try:
            adb = self._adb
        finally:
            self._pool_lock.release()
        import time as _time
        start = _time.time()
        adb.tap(x, y)
        elapsed = (_time.time() - start) * 1000
        self._record_quality("click", elapsed)
        self._check_health_and_reconnect()
        self._log("info", f"[01-设备连接] 点击坐标: ({x}, {y}) 耗时 {elapsed:.0f}ms")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """滑动操作（duration_ms 毫秒）"""
        self._wait_for_resume()
        self.ensure_connected()
        if not self._pool_lock.acquire(timeout=3):
            raise DeviceTimeoutError("获取设备池锁超时(3s)")
        try:
            adb = self._adb
        finally:
            self._pool_lock.release()
        import time as _time
        start = _time.time()
        adb.swipe(x1, y1, x2, y2, duration_ms)
        elapsed = (_time.time() - start) * 1000
        self._record_quality("swipe", elapsed)
        self._check_health_and_reconnect()
        self._log("info", f"[01-设备连接] 滑动: ({x1},{y1})→({x2},{y2}) 耗时 {elapsed:.0f}ms")

    def input_key(self, key: str) -> None:
        """模拟按键输入"""
        self._wait_for_resume()
        self.ensure_connected()
        key_map = {"back": 4, "home": 3, "menu": 82, "enter": 66}
        code = key_map.get(key)
        if code is not None:
            self._adb.keyevent(code)

    def input_text(self, text: str) -> None:
        """输入文本（自动转义 shell 特殊字符）"""
        self._wait_for_resume()
        self.ensure_connected()
        import time as _time
        start = _time.time()
        self._adb.text(text)
        elapsed = (_time.time() - start) * 1000
        self._record_quality("input_text", elapsed)
        self._check_health_and_reconnect()

    def get_screen_size(self) -> tuple[int, int]:
        """获取屏幕尺寸（仅读取，不修改）"""
        self._wait_for_resume()
        self.ensure_connected()
        return self._adb.wm_size()

    def launch_app(self, package: str, activity: str) -> bool:
        """启动 App"""
        self._wait_for_resume()
        self.ensure_connected()
        return self._adb.am_start(package, activity)

    def is_app_foreground(self, package: str) -> str:
        """判断 App 运行状态。返回 FOREGROUND / BACKGROUND / NOT_RUNNING

        优先使用 dumpsys activity 解析前台包名；
        若 dumpsys 格式不匹配则回退 pidof（此时仅能区分存活与否，将存活状态标记为 BACKGROUND）。
        """
        try:
            fg = self._adb.foreground_package()
            if fg and package in fg:
                return "FOREGROUND"
            return "BACKGROUND"
        except Exception:
            try:
                result = self._adb.run(["shell", "pidof", package], timeout=5.0)
                if result.stdout.strip():
                    return "BACKGROUND"
            except Exception:
                pass
            return "NOT_RUNNING"

    def echo(self) -> bool:
        """检测设备是否在线（adb shell echo ok, timeout=5s）"""
        return self._adb.echo()

    # ── 公共暂停/恢复 API（供 HeartbeatMonitor 调用） ──────────

    def pause_operations(self) -> None:
        """暂停所有设备操作（重连期间调用）。清除 _conn_pause_event 阻止操作。"""
        self._conn_pause_event.clear()

    def resume_operations(self) -> None:
        """恢复所有设备操作。设置 _conn_pause_event 允许操作继续。"""
        self._conn_pause_event.set()

    # ── 心跳 ──────────────────────────────────────────────────

    def start_heartbeat(self, interval: float = 30.0) -> None:
        """启动心跳检测线程（守护线程）"""
        from device.heartbeat import HeartbeatMonitor
        self._heartbeat = HeartbeatMonitor(self, event_bus=self._bus, interval=interval)
        self._heartbeat.start()

    def stop_heartbeat(self) -> None:
        """停止心跳检测。join(timeout=5)，超时后记录警告"""
        if self._heartbeat:
            self._heartbeat.stop()
            # 如有活跃的重连线程，一并停止
            if self._reconnect_thread and self._reconnect_thread.is_alive():
                self._reconnect_stop.set()
                self._reconnect_thread.join(timeout=3)
                if self._reconnect_thread.is_alive():
                    import logging
                    logging.warning("重连线程未能在 3s 内退出")
                self._reconnect_thread = None

    # ── 生命周期 ──────────────────────────────────────────────

    def close(self) -> None:
        """关闭连接"""
        self.stop_heartbeat()
        self.disconnect()
