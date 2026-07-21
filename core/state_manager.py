"""
全局状态管理器（07-状态管理模块）

集中管理脚本运行时所有跨模块共享的全局状态。
通过事件总线广播状态变化，订阅者无需轮询。

设计原则：
  - 单一数据源：全局状态只在 StateManager 中维护
  - 变化即广播：set_state 自动通过事件总线广播
  - 只管运行时态：配置归 ConfigManager，持久化记录归 Scheduler
  - 非持久化：运行时状态不写盘（重启即重置）
"""

from datetime import datetime
from typing import Any, Callable

from core.event_bus import event_bus, Events
from core.state_schema import StateKeys


class StateManager:
    """全局运行时状态管理中心。"""

    def __init__(self):
        self._states: dict[str, Any] = self._defaults()

    # ==================== 读写 ====================

    def get_state(self, key: str, default: Any = None) -> Any:
        """读取状态值。"""
        return self._states.get(key, default)

    def set_state(self, key: str, value: Any):
        """设置状态值，并自动通过事件总线广播变化。"""
        old_value = self._states.get(key)
        if old_value == value:
            return
        self._states[key] = value
        event_bus.publish(
            Events.STATE_CHANGED,
            key=key,
            old_value=old_value,
            new_value=value,
        )

    def set_states(self, mapping: dict):
        """批量设置状态，仅发布一次广播。

        与 update_states(**kwargs) 功能相同，接受字典参数。
        符合 07-运行时状态管理.md 的接口规范。

        Args:
            mapping: {key: value, ...} 状态字典
        """
        self.update_states(**mapping)

    def update_states(self, **kwargs):
        """批量设置状态，仅发布一次广播。"""
        changed = {}
        for key, value in kwargs.items():
            old = self._states.get(key)
            if old != value:
                self._states[key] = value
                changed[key] = (old, value)
        if changed:
            event_bus.publish(Events.STATE_CHANGED, changes=changed)

    # ==================== 快照 ====================

    def get_snapshot(self) -> dict:
        """获取全部状态快照（调试/日志/UI 刷新用）。"""
        return dict(self._states)

    # ==================== 生命周期 ====================

    def reset(self):
        """重置所有状态为初始值。"""
        self._states = self._defaults()
        event_bus.publish(Events.STATE_CHANGED, key="*", old_value="*", new_value="reset")

    # ==================== 便捷方法 ====================

    def subscribe(self, key: str, callback: Callable):
        """便捷订阅特定状态的变化（内部走事件总线）。"""
        def _handler(**data):
            if data.get("key") == key:
                callback(data.get("new_value"), data.get("old_value"))
        event_bus.subscribe(Events.STATE_CHANGED, _handler)

    # ==================== 内部 ====================

    @staticmethod
    def _defaults() -> dict:
        return {
            StateKeys.RUN_STATUS: "stopped",
            StateKeys.RUN_START_TIME: None,
            StateKeys.TODAY_RUN_DURATION: 0,
            StateKeys.CURRENT_ACCOUNT: "main",
            StateKeys.ACCOUNT_ROLE: "main",
            StateKeys.CONNECTION_STATUS: "disconnected",
            StateKeys.ACTIVE_DEVICE_ID: None,
            StateKeys.CURRENT_SCENE: "unknown",
            StateKeys.CURRENT_TASK: None,
            StateKeys.CURRENT_STEP: None,
            StateKeys.TASK_PROGRESS: None,
            StateKeys.TASK_STATUS: {},
            StateKeys.TASK_RUNTIME_PROGRESS: {},
            StateKeys.LAST_KNOWN_SCENE: None,
            StateKeys.SCHEDULE_QUEUE: [],
            StateKeys.SUB_ACCOUNT_FINDINGS: {},
            StateKeys.BEST_FINDING: None,
            StateKeys.SUB_ACCOUNT_STATUS: {},
            StateKeys.TODAY_OPERATION_COUNT: 0,
            StateKeys.RUN_LIMIT_REACHED: False,
            StateKeys.SAFETY_PROFILE: "normal",
        }


# 全局单例（main.py 中初始化）
state_manager = StateManager()
