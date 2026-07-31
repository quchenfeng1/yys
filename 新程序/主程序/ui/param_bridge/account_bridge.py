"""
10-参数桥接模块

账号传参（§5.3 AccountBridge）。
桥接 AccountManager 与 UI/任务。
"""
from __future__ import annotations

from typing import Any

from core.account_manager import AccountManager


class AccountBridge:
    """账号参数桥接（§5.3）"""

    def __init__(self, account_mgr: AccountManager | None):
        self._mgr = account_mgr

    # ── §5.3 方法 ────────────────────────────────────────

    def switch_to(self, account_id: str) -> bool:
        """切换当前操作账号（§5.3）"""
        if not self._mgr:
            return False
        try:
            self._mgr.switch_to(account_id)
            return True
        except Exception:
            return False

    def get_all_accounts(self) -> list[Any]:
        """获取全部账号列表（§5.3）"""
        if not self._mgr:
            return []
        return list(getattr(self._mgr, 'accounts', []) or [])

    # ── 兼容旧名 ─────────────────────────────────────────

    def get_current_account_name(self) -> str:
        if not self._mgr:
            return ""
        return self._mgr.current or ""

    def get_account_list(self) -> list[dict[str, Any]]:
        if not self._mgr:
            return []
        return [
            {
                "name": a.name,
                "enabled": a.enabled,
                "region": a.region,
                "remark": a.remark,
            }
            for a in self._mgr.accounts
        ]

    switch_account = switch_to

    def get_login_status(self) -> str:
        if not self._mgr:
            return "unknown"
        return self._mgr.get_login_status(self._mgr.current or "")

    def get_account_params(self) -> dict[str, Any]:
        if not self._mgr:
            return {}
        account = self._mgr.get_current_account()
        if not account:
            return {}
        return {
            "account_name": account.name,
            "region": account.region,
            "cookies": account.cookies,
        }
