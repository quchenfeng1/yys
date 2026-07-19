"""
账号传参（10-传参模块 子模块）
"""


class AccountBridge:
    """账号传参。"""

    def __init__(self, config_manager, state_manager):
        self._config = config_manager
        self._state_mgr = state_manager
