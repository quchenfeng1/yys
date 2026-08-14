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

    def set_manager(self, account_mgr: AccountManager | None) -> None:
        """运行后注入/更新 AccountManager（bootstrap L5 初始化后回注入）"""
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

    # ── 账号增删改（小号管理面板使用）──────────────────────

    def add_account(self, account_id: str, name: str = "", role: str = "sub",
                    device_id: str = "", region: str = "cn",
                    enabled: bool = True, remark: str = "",
                    team_group: str = "") -> bool:
        """添加账号（默认 sub 角色）并持久化"""
        if not self._mgr:
            return False
        return bool(self._mgr.add_account({
            "account_id": account_id,
            "name": name or account_id,
            "role": role,
            "enabled": enabled,
            "region": region,
            "device_id": device_id,
            "remark": remark,
            "team_group": team_group,
        }))

    def remove_account(self, account_id: str) -> bool:
        """删除账号并持久化"""
        if not self._mgr:
            return False
        return bool(self._mgr.remove_account(account_id))

    def update_account(self, account_id: str, **updates: Any) -> bool:
        """更新账号字段并持久化"""
        if not self._mgr:
            return False
        return bool(self._mgr.update_account(account_id, **updates))

    def get_accounts_detail(self) -> list[dict[str, Any]]:
        """获取全部账号详情（含 account_id/role/device_id 等，供管理面板展示）"""
        if not self._mgr:
            return []
        out = []
        for a in getattr(self._mgr, 'accounts', []) or []:
            out.append({
                "account_id": getattr(a, 'account_id', '') or getattr(a, 'name', ''),
                "name": getattr(a, 'name', ''),
                "role": getattr(a, 'role', 'sub'),
                "enabled": bool(getattr(a, 'enabled', True)),
                "region": getattr(a, 'region', 'cn'),
                "device_id": getattr(a, 'device_id', ''),
                "remark": getattr(a, 'remark', ''),
                "team_group": getattr(a, 'team_group', ''),
            })
        return out

    def get_sub_accounts(self) -> list[dict[str, Any]]:
        """获取全部小号详情（role == sub）"""
        return [a for a in self.get_accounts_detail() if a.get("role") == "sub"]

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
