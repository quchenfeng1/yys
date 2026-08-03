"""
07-运行时状态管理

StateManager 主入口（§5.1 + §5.2 方法定义）。
对应设计书 §2/§3/§4/§5。

职责:
- 线程安全的键值状态存储（单一数据源）
- 状态变更自动广播（锁外发事件）
- 状态校验器 + 重置白名单
- 状态快照（深拷贝 get_snapshot）
- 环形历史缓冲（deque maxlen=1000）
- 方法别名兼容设计书命名（get_state/set_state/set_states/get_snapshot）

设计原则：
- 非持久化（§4.3）：运行时状态不写盘，重启即重置
- 变化即广播（§4.2）：set_state 自动发事件
- 锁外发事件：防止订阅者 handler 持同一锁导致死锁
"""
from __future__ import annotations

import copy
import json
import threading
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.exceptions import StateError, StateKeyNotFoundError
from core.state_schema import StateKeys


class StateManager:
    """运行时状态管理器（§5.2 方法定义）"""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        persist_path: str | Path | None = None,
        auto_persist: bool = False,  # 默认非持久化（§4.3）
    ):
        self._lock = threading.RLock()
        self._store: dict[str, Any] = {}
        self._state = self._store  # 说明书 §2.3 要求名
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名

        # 场景感知：订阅 scene_updated（14-执行器 detect_scene/probe_scene 命中发布）
        self._bus.subscribe(Events.SCENE_UPDATED, self._on_scene_updated)

        # §4.3 非持久化：persist 为可选功能，默认关闭
        self._persist_path = Path(persist_path) if persist_path else None
        self._auto_persist = auto_persist

        # 快照
        self._snapshots: list[dict[str, Any]] = []
        self._max_snapshots = 50

        # §2.3 校验器注册表
        self._validators: dict[str, list[callable]] = {}

        # §2.3 本地订阅
        self._subscribers: dict[str, list[callable]] = {}
        self._subscriber_id_counter = 0

        # §2.3 重置白名单
        self._reset_whitelist: set[str] = set()

        # §3.5 环形历史缓冲
        self._history: dict[str, deque] = {}
        self._history_enabled: bool = False  # 默认关闭，通过 set_state("_history_enabled", True) 开启

    # ── 读取（§3.1 + §5.2）────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取状态值（§5.2 get_state 的实现）。

        不持锁（Python GIL 保证单次 dict 读取的原子性，§3.1）。
        返回值是内部对象的**内存引用**（非拷贝），必须视为只读快照：
        - 禁止直接修改返回值（如 get("x").append(1)）
        - 如需修改，调 set_state(key, new_value)
        """
        return self._store.get(key, default)

    def get_state(self, key: str, default: Any = None) -> Any:
        """§5.2 get_state 兼容别名"""
        return self.get(key, default)

    def get_states_safe(self, keys: list[str] | None = None) -> dict[str, Any]:
        """
        安全获取多个键的**加锁浅拷贝**（§5.2 + §3.1）。

        获取 _lock → 逐项 copy.copy(_state[k]) → 释放锁 → 返回。
        适用于需遍历列表或读取自定义类实例的场景，调用方获得独立副本。

        Args:
            keys: 键名列表，或 None（返回全部键的浅拷贝）
        """
        with self._lock:
            if keys is None:
                keys = list(self._store.keys())
            result = {}
            for k in keys:
                val = self._store.get(k)
                if val is not None:
                    result[k] = copy.copy(val)
            return result

    def get_snapshot(self) -> dict[str, Any]:
        """
        获取全部状态的深拷贝副本（§3.4 + §5.2）。

        获取 _lock → copy.deepcopy(_state) → 释放锁 → 返回。
        调用方修改副本不影响全局运行状态。
        """
        with self._lock:
            return copy.deepcopy(self._store)

    def get_str(self, key: str, default: str = "") -> str:
        """获取字符串状态值"""
        val = self.get(key, default)
        return str(val) if val is not None else default

    def get_int(self, key: str, default: int = 0) -> int:
        """获取整数状态值"""
        val = self.get(key, default)
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """获取浮点数状态值"""
        val = self.get(key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔状态值"""
        val = self.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    def require(self, key: str) -> Any:
        """获取状态值，不存在则抛异常"""
        val = self.get(key)
        if val is None and key not in self._store:
            raise StateKeyNotFoundError(f"状态键不存在: {key}")
        return val

    def get_all(self, prefix: str | None = None) -> dict[str, Any]:
        """获取所有状态（可按前缀过滤）"""
        with self._lock:
            if prefix:
                return {k: v for k, v in self._store.items() if k.startswith(prefix)}
            return dict(self._store)

    # ── 场景感知（§2.2 场景状态 + 说明书 07）────────────────

    def set_current_scene(self, name: str | None) -> None:
        """设置当前场景：写 current_scene；name 非 None 时同步写 last_known_scene。"""
        self.set_state(StateKeys.CURRENT_SCENE, name)
        if name:
            self.set_state(StateKeys.LAST_KNOWN_SCENE, name)

    def get_current_scene(self) -> str | None:
        """读取当前场景名（current_scene）。"""
        return self.get(StateKeys.CURRENT_SCENE)

    def get_last_known_scene(self) -> str | None:
        """读取最后已知场景名（last_known_scene），供 09 误触/弹窗后恢复定位。"""
        return self.get(StateKeys.LAST_KNOWN_SCENE)

    def _on_scene_updated(self, scene=None, **kw) -> None:
        """场景感知命中（14-执行器 发布 scene_updated）→ 维护 current_scene/last_known_scene。"""
        if scene:
            self.set_current_scene(str(scene))

    # ── 校验器 ────────────────────────────────────────────────

    def add_validator(self, key: str, validator: callable) -> None:
        """注册状态值校验器。validator(key, value) -> bool"""
        self._validators.setdefault(key, []).append(validator)

    def _validate(self, key: str, value: Any) -> bool:
        """运行所有匹配的校验器"""
        validators = self._validators.get(key, [])
        return all(v(key, value) for v in validators)

    # ── 本地订阅（§5.2 subscribe）────────────────────────────

    def subscribe(self, key: str, callback: callable) -> str:
        """
        订阅特定状态变化（§5.2 + §5.4）。

        Returns:
            订阅 ID（可用于 unsubscribe_by_id）
        """
        sub_id = f"sub_{self._subscriber_id_counter}"
        self._subscriber_id_counter += 1
        self._subscribers.setdefault(key, []).append((sub_id, callback))
        return sub_id

    def unsubscribe(self, key: str, callback: callable) -> bool:
        """取消订阅（按回调引用）"""
        subs = self._subscribers.get(key, [])
        for i, (sid, cb) in enumerate(subs):
            if cb is callback:
                subs.pop(i)
                return True
        return False

    def unsubscribe_by_id(self, sub_id: str) -> bool:
        """取消订阅（按订阅 ID）"""
        for key, subs in list(self._subscribers.items()):
            for i, (sid, cb) in enumerate(subs):
                if sid == sub_id:
                    subs.pop(i)
                    return True
        return False

    def _notify_subscribers(self, key: str, value: Any) -> None:
        """通知本地订阅者（锁外调用）"""
        for _sid, cb in self._subscribers.get(key, []):
            try:
                cb(key, value)
            except Exception:
                pass

    # ── 重置白名单（§2.3 + §5.2）────────────────────────────

    def add_reset_whitelist(self, key: str) -> None:
        """添加重置白名单（reset 时保留，§5.2）"""
        with self._lock:
            self._reset_whitelist.add(key)

    # ── 写入（§3.1 + §5.2）────────────────────────────────────

    def _record_history(self, key: str, old_value: Any, new_value: Any) -> None:
        """记录变更历史（§3.5 环形缓冲）"""
        if not self._history_enabled:
            return
        if key not in self._history:
            self._history[key] = deque(maxlen=1000)
        self._history[key].append({
            "timestamp": datetime.now().isoformat(),
            "old": old_value,
            "new": new_value,
        })

    def set(self, key: str, value: Any) -> None:
        """
        设置状态值（§3.1 + §5.2 set_state）。

        流程：校验 → 对比旧值 → 同引用检测 → 更新 → 记录历史 → 锁外发事件
        """
        if not self._validate(key, value):
            raise StateError(f"状态值校验失败: {key}={value}")

        with self._lock:
            old = self._store.get(key)

            # §3.1 同引用检测：警告可能通过 get_state 直接修改了可变对象
            if value is old:
                import logging
                logging.warning(
                    "状态键 '%s' 的 set_state 收到了与旧值相同的对象引用，"
                    "可能通过 get_state 直接修改了可变对象",
                    key,
                )
                return
            if old == value:
                return

            self._store[key] = value
            self._record_history(key, old, value)

            # §3.5 通过 set_state("_history_enabled", True) 启用历史记录
            if key == "_history_enabled":
                self._history_enabled = bool(value)

        # §3.1 锁外发布事件
        self._bus.publish(Events.STATE_CHANGED, source="state_manager",
                         key=key, old_value=old, new_value=value)
        self._notify_subscribers(key, value)
        self._maybe_persist()

    def set_state(self, key: str, value: Any) -> None:
        """§5.2 set_state 兼容别名"""
        self.set(key, value)

    def set_states(self, mapping: dict[str, Any]) -> None:
        """
        批量更新多个键（§3.1 + §5.2 set_states）。

        逐项校验 → 收集变化键 → 统一更新 → 统一历史 → 一次合并事件
        """
        # 先全部校验
        for key, value in mapping.items():
            if not self._validate(key, value):
                raise StateError(f"状态值校验失败: {key}={value}")

        changes: list[tuple[str, Any, Any]] = []

        with self._lock:
            for key, value in mapping.items():
                old = self._store.get(key)
                if value is old or old == value:
                    continue
                self._store[key] = value
                self._record_history(key, old, value)
                changes.append((key, old, value))

                # §3.5 通过 set_states 启用历史记录
                if key == "_history_enabled":
                    self._history_enabled = bool(value)

        if not changes:
            return

        # 锁外发布一次合并事件
        self._bus.publish(Events.STATE_CHANGED, source="state_manager",
                         keys=[c[0] for c in changes],
                         mapping={c[0]: {"old": c[1], "new": c[2]} for c in changes})
        for key, _old, value in changes:
            self._notify_subscribers(key, value)
        self._maybe_persist()

    # 兼容旧名
    set_many = set_states

    def update(self, key: str, **updates: Any) -> None:
        """更新字典类型状态的字段"""
        with self._lock:
            current = self._store.get(key, {})
            if not isinstance(current, dict):
                current = {}
            current.update(updates)
            self._store[key] = current
        self._bus.publish(Events.STATE_KEY_UPDATED, key=key, value=current)
        self._maybe_persist()

    def delete(self, key: str) -> bool:
        """删除状态键"""
        with self._lock:
            if key not in self._store:
                return False
            del self._store[key]
        self._bus.publish(Events.STATE_CHANGED, key=key, value=None)
        self._maybe_persist()
        return True

    def increment(self, key: str, amount: int = 1) -> int:
        """原子自增"""
        with self._lock:
            val = self._store.get(key, 0)
            if not isinstance(val, (int, float)):
                val = 0
            val += amount
            self._store[key] = val
        self._bus.publish(Events.STATE_KEY_UPDATED, key=key, value=val)
        return val

    def has(self, key: str) -> bool:
        """检查键是否存在"""
        return key in self._store

    # ── 快照（§3.4 + §5.2）────────────────────────────────────

    def snapshot(self, name: str = "") -> int:
        """创建当前状态快照，返回快照 ID（使用 deepcopy）"""
        with self._lock:
            snap = {
                "name": name,
                "timestamp": datetime.now().isoformat(),
                "data": copy.deepcopy(self._store),
            }
            self._snapshots.append(snap)
            if len(self._snapshots) > self._max_snapshots:
                self._snapshots.pop(0)
            self._bus.publish(Events.STATE_SNAPSHOT, name=name, index=len(self._snapshots) - 1)
            return len(self._snapshots) - 1

    def restore(self, snapshot_index: int) -> None:
        """恢复到指定快照"""
        with self._lock:
            if snapshot_index < 0 or snapshot_index >= len(self._snapshots):
                raise StateError(f"快照索引无效: {snapshot_index}")
            self._store = copy.deepcopy(self._snapshots[snapshot_index]["data"])

    def list_snapshots(self) -> list[dict[str, str]]:
        """列出所有快照"""
        with self._lock:
            return [
                {"index": i, "name": s["name"], "timestamp": s["timestamp"]}
                for i, s in enumerate(self._snapshots)
            ]

    # ── 持久化（§4.3 非持久化设计，persist 为可选扩展）───────

    def persist(self) -> None:
        """
        保存状态到 JSON 文件（§4.3 非持久化：默认不启用）。

        运行时状态不写磁盘（重启即重置）。如需持久化，
        在构造函数中传入 persist_path 并设 auto_persist=True。
        """
        if not self._persist_path:
            return
        with self._lock:
            data = copy.deepcopy(self._store)
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception:
            traceback.print_exc()

    def load_persisted(self) -> bool:
        """从 JSON 文件恢复状态（§4.3：可选）"""
        if not self._persist_path or not self._persist_path.exists():
            return False
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._store.update(data)
            return True
        except Exception:
            traceback.print_exc()
            return False

    def _maybe_persist(self) -> None:
        """自动持久化（若启用）"""
        if self._auto_persist and self._persist_path:
            self.persist()

    # ── 生命周期（§5.2 reset + close）────────────────────────

    def reset(self) -> None:
        """重置状态（保留白名单键，§5.2 + §3.5）"""
        with self._lock:
            whitelisted = {k: self._store[k] for k in self._reset_whitelist if k in self._store}
            self._store.clear()
            self._store.update(whitelisted)
            self._snapshots.clear()
            self._history.clear()
        self._bus.publish(Events.STATE_RESET, source="state_manager", whitelist=list(self._reset_whitelist))

    def close(self) -> None:
        """关闭管理器，持久化最终状态"""
        if self._persist_path:
            self.persist()
