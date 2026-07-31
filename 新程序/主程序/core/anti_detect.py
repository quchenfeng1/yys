"""
03-防封策略模块

AntiDetect 安全策略引擎（档案驱动 + 参数漂移 + 审计日志）。
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from collections import deque
from typing import Any

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.exceptions import ProfileNotFoundError, RateLimitError, RunLimitExceeded


# 四档预设参数
PROFILES: dict[str, dict[str, float]] = {
    "safe": {
        "offset_radius": 15, "jitter_range": 1.0, "pause_probability": 0.15,
        "drift_amplitude": 0.15, "min_interval": 1.5, "max_interval": 5.0,
    },
    "normal": {
        "offset_radius": 10, "jitter_range": 0.5, "pause_probability": 0.08,
        "drift_amplitude": 0.15, "min_interval": 0.8, "max_interval": 3.0,
    },
    "fast": {
        "offset_radius": 5, "jitter_range": 0.2, "pause_probability": 0.03,
        "drift_amplitude": 0.10, "min_interval": 0.3, "max_interval": 1.5,
    },
    "debug": {
        "offset_radius": 0, "jitter_range": 0.0, "pause_probability": 0.0,
        "drift_amplitude": 0.0, "min_interval": 0.1, "max_interval": 0.3,
    },
}


class AntiDetect:
    """防封策略引擎（档案驱动）"""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        monitor: Any = None,
        config: Any = None,
        max_actions_per_minute: int = 60,
        max_daily_duration: float = 28800,
        min_interval: float | None = None,
        max_interval: float | None = None,
        action_jitter: bool = True,
        random_fail_rate: float = 0.02,
    ):
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名
        self._monitor = monitor
        self._config = config
        self._lock = threading.Lock()
        self._action_lock = threading.Lock()
        self._audit_log_lock = threading.Lock()
        self._drift_lock = threading.Lock()

        # 会话标识
        self._session_id: str = uuid.uuid4().hex[:12]

        # 行为档案
        self._profile_name: str = "normal"
        self._profile_params: dict[str, float] = dict(PROFILES["normal"])

        # 运行时参数（从 profile_params 加载，受漂移影响）
        self._offset_radius: float = self._profile_params["offset_radius"]
        self._jitter_range: float = self._profile_params["jitter_range"]
        self._pause_probability: float = self._profile_params["pause_probability"]
        self._drift_amplitude: float = self._profile_params["drift_amplitude"]
        self._min_interval: float = min_interval if min_interval is not None else self._profile_params["min_interval"]
        self._max_interval: float = max_interval if max_interval is not None else self._profile_params["max_interval"]

        # 附加配置
        self._action_jitter: bool = action_jitter
        self._random_fail_rate: float = random_fail_rate
        self._drift_enabled: bool = self._get_config_drift_enabled()

        # 运行限制
        self._max_actions_per_minute = max_actions_per_minute
        self._max_daily_duration = max_daily_duration

        # 状态
        self._last_action_time: float = 0.0
        self._action_times: list[float] = []
        self._action_count: int = 0
        self._risk_level: int = 0
        self._run_start_time: float = 0.0
        self._last_drift_time: float = 0.0

        # 审计日志
        self._audit_log: deque[dict] = deque(maxlen=5000)

        # 订阅事件
        _self = self
        self._config_sub_id: str | None = self._bus.subscribe(
            Events.CONFIG_CHANGED,
            lambda source, **kw: _self.reload_profile() if source == "global" else None,
        )

    def _get_config_drift_enabled(self) -> bool:
        """从配置读取 drift_enabled 标志"""
        if not self._config:
            return True
        try:
            ad_config = self._config.get("global.anti_detect", {})
            if isinstance(ad_config, dict):
                return bool(ad_config.get("drift_enabled", True))
        except Exception:
            pass
        return True

    # ── 属性 ──────────────────────────────────────────────────

    @property
    def current_profile(self) -> str:
        return self._profile_name

    @property
    def risk_level(self) -> int:
        return self._risk_level

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def session_id(self) -> str:
        return self._session_id

    # ── 位置随机化 ───────────────────────────────────────────

    def random_offset(self, cx: int, cy: int, radius: int | None = None) -> tuple[int, int]:
        """正态分布偏移（钳制 ±2σ），入口自动调 _check_drift()"""
        self._check_drift()
        r = radius if radius is not None else int(self._offset_radius)
        if r <= 0:
            return (cx, cy)
        sigma = r / 2.0
        dx = int(random.gauss(0, sigma))
        dy = int(random.gauss(0, sigma))
        dx = max(-r, min(r, dx))
        dy = max(-r, min(r, dy))
        return (cx + dx, cy + dy)

    def random_offset_in_bounds(self, cx: int, cy: int, w: int, h: int) -> tuple[int, int]:
        """在图标矩形内均匀分布（不调用 _check_drift）
        参数 cx, cy 为矩形中心坐标，w, h 为矩形宽高。
        """
        x1 = cx - w // 2
        y1 = cy - h // 2
        x = random.randint(x1, x1 + w - 1) if w > 0 else cx
        y = random.randint(y1, y1 + h - 1) if h > 0 else cy
        return (x, y)

    # ── 滑动轨迹 ─────────────────────────────────────────────

    def generate_trajectory(
        self, from_x: int, from_y: int, to_x: int, to_y: int, steps: int = 12
    ) -> list[tuple[int, int]]:
        """
        三次贝塞尔曲线路径点（4 控制点：起点 P0，终点 P3，两个中间控制点 P1、P2）。
        FAST/DEBUG 返回空列表跳过轨迹。
        """
        if self._profile_name in ("fast", "debug") or steps <= 0:
            return []
        # 两个中间控制点：P1 偏向起点的前进方向，P2 偏向终点的后退方向
        dx = to_x - from_x
        dy = to_y - from_y
        dist = max(abs(dx), abs(dy), 1)
        # P1: 从起点沿方向 1/3 处 + 垂直偏移
        p1x = from_x + dx // 3 + random.randint(-dist // 6, dist // 6)
        p1y = from_y + dy // 3 - abs(dx) // 4
        # P2: 从终点反向 1/3 处 + 垂直偏移
        p2x = to_x - dx // 3 + random.randint(-dist // 6, dist // 6)
        p2y = to_y - dy // 3 + abs(dx) // 4

        points = []
        for i in range(steps + 1):
            t = i / steps
            u = 1.0 - t
            # 三次贝塞尔: B(t) = u³P0 + 3u²tP1 + 3ut²P2 + t³P3
            x = u ** 3 * from_x + 3 * u ** 2 * t * p1x + 3 * u * t ** 2 * p2x + t ** 3 * to_x
            y = u ** 3 * from_y + 3 * u ** 2 * t * p1y + 3 * u * t ** 2 * p2y + t ** 3 * to_y
            points.append((int(x), int(y)))
        return points

    # ── 时间相关 ─────────────────────────────────────────────

    def random_swipe_duration(self, base_ms: int) -> int:
        """随机滑动时长"""
        self._check_drift()
        return int(base_ms * random.uniform(0.8, 1.2))

    def random_delay(self, base_sec: float, jitter_sec: float | None = None) -> float:
        """计算随机延迟值（不执行休眠）"""
        self._check_drift()
        j = jitter_sec if jitter_sec is not None else self._jitter_range
        return base_sec + random.uniform(-j, j)

    def sleep(self, base_sec: float, jitter_sec: float | None = None,
              stop_event: threading.Event | None = None) -> bool:
        """
        可打断休眠。使用 stop_event.wait(timeout) 替代 time.sleep()。
        返回 True=正常完成, False=被打断。
        """
        self._check_drift()
        j = jitter_sec if jitter_sec is not None else self._jitter_range
        duration = base_sec + random.uniform(-j, j)
        duration = max(0.1, duration)

        if stop_event is not None:
            return not stop_event.wait(timeout=duration)
        else:
            time.sleep(duration)
            return True

    def maybe_long_pause(self, stop_event: threading.Event | None = None) -> bool:
        """
        按概率触发长暂停（5~15s），分段休眠每 3s 检查 stop_event。
        走神概率来自档案参数。
        """
        self._check_drift()
        if random.random() >= self._pause_probability:
            return True

        total = random.uniform(5.0, 15.0)
        elapsed = 0.0
        while elapsed < total:
            if stop_event and stop_event.is_set():
                return False
            chunk = min(3.0, total - elapsed)
            if stop_event:
                if stop_event.wait(timeout=chunk):
                    return False
            else:
                time.sleep(chunk)
            elapsed += chunk
        return True

    def random_typing_delay(self) -> float:
        """模拟打字间隔（80~250ms，5%概率额外停顿1~3s）"""
        self._check_drift()
        delay = random.uniform(0.08, 0.25)
        if random.random() < 0.05:
            delay += random.uniform(1.0, 3.0)
        return delay

    # ── 操作控制 ─────────────────────────────────────────────

    def wait_if_needed(self) -> float:
        """等待操作间隔"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_action_time
            interval = random.uniform(self._min_interval, self._max_interval)
            jitter = 0.1 if self._action_jitter else 0.0
            wait_time = max(0.05, interval - elapsed + random.uniform(-jitter, jitter)) if elapsed < interval else 0.0
        if wait_time > 0:
            time.sleep(wait_time)
        self.record_action()
        return wait_time

    def check_run_limit(self) -> None:
        """检查运行时长上限"""
        if self._run_start_time <= 0:
            return
        elapsed = time.time() - self._run_start_time
        if elapsed > self._max_daily_duration:
            raise RunLimitExceeded(f"运行时长超限: {elapsed:.0f}s")

    def record_action(self) -> None:
        """记录操作计数（_action_lock 保护）到审计日志"""
        with self._action_lock:
            self._last_action_time = time.time()
            self._action_count += 1
            self._action_times.append(time.time())
            self._clean_action_times()
            self._audit_log.append({
                "time": time.time(),
                "type": "action",
                "count": self._action_count,
                "profile": self._profile_name,
            })

    def check_rate_limit(self) -> None:
        """检查操作频率"""
        with self._lock:
            self._clean_action_times()
            count = len(self._action_times)
        if count > self._max_actions_per_minute:
            self._bus.publish(Events.ANTI_DETECT_RATE_LIMITED, source="anti_detect", count=count)
            raise RateLimitError(f"操作频率超限: {count}/分钟")

    def _clean_action_times(self) -> None:
        cutoff = time.time() - 60
        self._action_times = [t for t in self._action_times if t > cutoff]

    def should_random_fail(self) -> bool:
        return random.random() < self._random_fail_rate

    # ── 审计日志 ─────────────────────────────────────────────

    def export_log(self) -> list[dict]:
        """导出审计日志快照拷贝"""
        with self._audit_log_lock:
            return list(self._audit_log)

    # ── 行为档案 ─────────────────────────────────────────────

    def reload_profile(self) -> None:
        """
        从配置重新加载行为档案。
        由 config_changed 事件触发。
        切换档案重置漂移计时器。
        """
        if not self._config:
            return
        with self._lock:
            try:
                ad_config = self._config.get("global.anti_detect", {})
                if not isinstance(ad_config, dict):
                    ad_config = {}
                name = ad_config.get("profile", "normal")
            except Exception:
                name = "normal"

            if name not in PROFILES:
                import logging
                logging.warning(f"档案不存在: {name}，回退到 normal")
                name = "normal"

            self._profile_name = name
            base = dict(PROFILES[name])
            # 允许配置覆盖
            if isinstance(ad_config, dict):
                for k in base:
                    if k in ad_config:
                        base[k] = float(ad_config[k])

            self._profile_params = base
            self._offset_radius = base["offset_radius"]
            self._jitter_range = base["jitter_range"]
            self._pause_probability = base["pause_probability"]
            self._drift_amplitude = base["drift_amplitude"]
            self._min_interval = base["min_interval"]
            self._max_interval = base["max_interval"]
            # 重置漂移计时器（新档案从头开始漂移）
            self._last_drift_time = 0.0

    # ── 参数漂移 ─────────────────────────────────────────────

    def _check_drift(self) -> None:
        """
        惰性兜底检查。双重检查锁定（_drift_lock）。
        每小时执行一次漂移，幅度由 drift_amplitude 控制。
        漂移结果钳制在 [0, SAFE_value*1.2]。
        若 drift_enabled 为 False 则跳过漂移。
        """
        if not self._drift_enabled:
            return
        now = time.time()
        if now - self._last_drift_time < 3600:
            return
        with self._drift_lock:
            if now - self._last_drift_time < 3600:
                return
            self._last_drift_time = now
            self._apply_drift()

    def _apply_drift(self) -> None:
        """执行参数漂移（同时更新 _profile_params 和运行期属性）"""
        amp = self._drift_amplitude
        safe = PROFILES.get("safe", PROFILES["normal"])

        for key in ("offset_radius", "jitter_range", "min_interval", "max_interval"):
            if key in self._profile_params:
                base = self._profile_params[key]
                new_val = base * (1 + random.uniform(-amp, amp))
                # 钳制：不低于 0，不超过 SAFE 值 × 1.2
                max_val = safe.get(key, base) * 1.2
                new_val = max(0.0, min(max_val, new_val))
                self._profile_params[key] = new_val
                setattr(self, f"_{key}", new_val)

        # pause_probability 特殊处理（概率不能超过 1.0）
        base_p = self._profile_params.get("pause_probability", 0.08)
        new_p = base_p * (1 + random.uniform(-amp, amp))
        new_p = max(0.0, min(1.0, new_p))
        self._profile_params["pause_probability"] = new_p
        self._pause_probability = new_p

    # ── 事件 ─────────────────────────────────────────────────

    def trigger_human_check(self, reason: str = "") -> None:
        self._bus.publish(Events.ANTI_DETECT_HUMAN_CHECK, source="anti_detect", reason=reason)
        self._risk_level = 2

    def trigger_block(self, reason: str = "") -> None:
        self._bus.publish(Events.ANTI_DETECT_BLOCKED, source="anti_detect", reason=reason)
        self._risk_level = 2

    def reset(self) -> None:
        with self._lock:
            self._action_times.clear()
            self._action_count = 0
            self._risk_level = 0
            self._last_action_time = 0.0
