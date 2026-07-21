"""
账号传参（10-传参模块 子模块）

账号切换 ↔ ConfigManager + StateManager。
"""

from core.event_bus import event_bus, Events
from core.state_schema import StateKeys


class AccountBridge:
    """账号传参。UI 账号操作 ↔ 配置 + 状态。"""

    def __init__(self, config_manager, state_manager):
        self._config = config_manager
        self._state_mgr = state_manager

    def bind_account_combo(self, combo, account_key: str = "main"):
        """账号下拉框 ↔ 当前选中账号。"""
        accounts = self._config.get("accounts", {})
        names = list(accounts.keys()) if accounts else ["主号"]
        combo.addItems(names)
        current = self._state_mgr.get_state(StateKeys.CURRENT_ACCOUNT, "main")
        idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.currentTextChanged.connect(
            lambda name: self._state_mgr.set_state(StateKeys.CURRENT_ACCOUNT, name)
        )

    def bind_account_label(self, label):
        """账号标签 ← 订阅 CURRENT_ACCOUNT 变化。"""
        def _on_change(new_val, _):
            label.setText(f"👤  {new_val}" if new_val else "👤  —")
        self._state_mgr.subscribe(StateKeys.CURRENT_ACCOUNT, _on_change)
        # 初始值
        current = self._state_mgr.get_state(StateKeys.CURRENT_ACCOUNT, "main")
        label.setText(f"👤  {current}" if current else "👤  —")

    def switch_to(self, account_name: str):
        """切换到指定账号。"""
        self._state_mgr.set_state(StateKeys.CURRENT_ACCOUNT, account_name)
        event_bus.publish(Events.ACCOUNT_SWITCHED, account=account_name)
