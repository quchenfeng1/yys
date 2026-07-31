"""
03-防封策略模块

BehaviorProfile 行为档案管理（多档安全强度 + 参数渐变 + 配置热重载）。
"""
from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from core.anti_detect import PROFILES as ANTI_DETECT_PROFILES
from core.exceptions import ProfileNotFoundError


@dataclass
class ActionRecord:
    """单次操作记录"""
    action_type: str
    x: int = 0
    y: int = 0
    duration: float = 0.0
    timestamp: float = 0.0
    success: bool = True


@dataclass
class BehaviorStats:
    """行为统计数据"""
    avg_interval: float = 0.0
    std_interval: float = 0.0
    action_types: dict[str, int] = field(default_factory=dict)
    peak_hours: list[int] = field(default_factory=list)
    total_actions: int = 0


# 从 anti_detect.py 导入 PROFILES，保持单一数据源
PROFILES = ANTI_DETECT_PROFILES


class BehaviorProfile:
    """行为档案管理器（多档预设 + 参数漂移 + 持久化）"""

    def __init__(self, profile_path: str | Path | None = None, config: Any = None):
        self._lock = threading.Lock()
        self._drift_lock = threading.Lock()
        self._profile_path = Path(profile_path) if profile_path else None
        self._config = config
        self._records: list[ActionRecord] = []
        self._max_records = 10000
        self._last_drift_time: float = 0.0

        # 当前档案参数（从配置文件加载）
        self._current_profile: str = "normal"
        self._params: dict[str, float] = dict(PROFILES["normal"])

    # ── 档案管理 ──────────────────────────────────────────────

    def load_profile(self, profile_name: str) -> dict[str, float]:
        """
        根据档案名加载预设参数。
        支持 "safe"/"normal"/"fast"/"debug"。
        配合 global.anti_detect 中的自定义覆盖。
        无效档案名回退到 NORMAL 并记录警告。
        """
        if profile_name not in PROFILES:
            import logging
            logging.warning(f"行为档案不存在: {profile_name}，回退到 normal")
            profile_name = "normal"

        params = dict(PROFILES[profile_name])

        # 从配置加载自定义覆盖
        if self._config:
            try:
                ad_config = self._config.get("global.anti_detect", {})
                if isinstance(ad_config, dict):
                    for k in params:
                        if k in ad_config:
                            params[k] = float(ad_config[k])
            except Exception:
                pass

        with self._lock:
            self._current_profile = profile_name
            self._params = params
            self._last_drift_time = 0.0  # 切换档案重置漂移

        return dict(params)

    def update_drift(self, current_time: float, params: dict[str, float]) -> dict[str, float]:
        """
        检查距离上次漂移是否 >= 3600s。
        是则对各参数在 ±drift_amplitude 范围内重新随机。
        结果钳制在 [0, SAFE_value×1.2]。
        """
        with self._drift_lock:
            if current_time - self._last_drift_time < 3600:
                return dict(params)

            self._last_drift_time = current_time
            amp = params.get("drift_amplitude", 0.15)
            safe = PROFILES.get("safe", PROFILES["normal"])
            drifted = {}

            for key, base in params.items():
                if key == "drift_amplitude":
                    drifted[key] = base
                    continue
                new_val = base * (1 + random.uniform(-amp, amp))
                max_val = safe.get(key, base) * 1.2
                if key == "pause_probability":
                    new_val = max(0.0, min(1.0, new_val))
                else:
                    new_val = max(0.0, min(max_val, new_val))
                drifted[key] = new_val

            return drifted

    @property
    def current_profile_name(self) -> str:
        return self._current_profile

    @property
    def params(self) -> dict[str, float]:
        return dict(self._params)

    # ── 记录 ──────────────────────────────────────────────────

    def record_action(self, record: ActionRecord) -> None:
        with self._lock:
            self._records.append(record)
            if len(self._records) > self._max_records:
                self._records.pop(0)
        self._maybe_persist()

    def record_click(self, x: int, y: int, success: bool = True) -> None:
        self.record_action(ActionRecord(action_type="click", x=x, y=y, timestamp=time.time(), success=success))

    def record_swipe(self, x1: int, y1: int, duration: float, success: bool = True) -> None:
        self.record_action(ActionRecord(action_type="swipe", x=x1, y=y1, duration=duration, timestamp=time.time(), success=success))

    def get_recent_actions(self, count: int = 50) -> list[ActionRecord]:
        with self._lock:
            return list(self._records[-count:])

    # ── 统计 ──────────────────────────────────────────────────

    def get_stats(self) -> BehaviorStats:
        with self._lock:
            if len(self._records) < 2:
                return BehaviorStats()
            intervals = []
            action_types: dict[str, int] = {}
            prev_time = 0.0
            for r in self._records:
                action_types[r.action_type] = action_types.get(r.action_type, 0) + 1
                if prev_time > 0:
                    intervals.append(r.timestamp - prev_time)
                prev_time = r.timestamp
            if not intervals:
                return BehaviorStats()
            avg_interval = sum(intervals) / len(intervals)
            variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
            return BehaviorStats(
                avg_interval=avg_interval,
                std_interval=variance ** 0.5,
                action_types=action_types,
                total_actions=len(self._records),
            )

    # ── 模拟生成 ──────────────────────────────────────────────

    def generate_action_sequence(self, count: int = 10) -> list[tuple[str, int, int]]:
        seq: list[tuple[str, int, int]] = []
        for _ in range(count):
            if random.random() < 0.9:
                seq.append(("click", random.randint(100, 980), random.randint(100, 1800)))
            else:
                seq.append(("swipe", random.randint(100, 980), random.randint(100, 1800)))
        return seq

    def get_suggested_interval(self) -> float:
        return random.uniform(self._params.get("min_interval", 1.0), self._params.get("max_interval", 3.0))

    # ── 持久化 ────────────────────────────────────────────────

    def persist(self) -> None:
        if not self._profile_path:
            return
        stats = self.get_stats()
        data = {
            "profile": self._current_profile,
            "stats": {
                "avg_interval": stats.avg_interval,
                "std_interval": stats.std_interval,
                "total_actions": stats.total_actions,
                "action_types": stats.action_types,
            },
            "updated_at": datetime.now().isoformat(),
        }
        self._profile_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._profile_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _maybe_persist(self) -> None:
        if self._profile_path and len(self._records) % 100 == 0:
            self.persist()

    def load_persisted(self) -> bool:
        """加载持久化的行为档案"""
        if not self._profile_path or not self._profile_path.exists():
            return False
        try:
            with open(self._profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return True
        except Exception:
            return False
