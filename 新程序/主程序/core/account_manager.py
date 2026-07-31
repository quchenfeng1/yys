"""
15-账号管理模块

AccountManager 账号配置与生命周期管理（§5.1 单文件）。
对应设计书 §2/§3/§4/§5/§6。

职责:
- 加载 accounts.yaml 管理主号/小号配置
- 账号切换（含设备切换、状态更新、事件通知）
- 角色区分与任务范围过滤
- Cookie 持久化
- 组队协调（teaming_partners / prepare_teaming / coordinate_action）
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.config_schema import AccountsConfig
from core.event_bus import EventBus, get_global_bus
from core.events import Events
from core.exceptions import AccountError


# ═══════════════════════════════════════════════════════════════
#  §2.3 AccountInfo 数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class AccountInfo:
    """账号信息（§2.3 + §5.2）"""
    account_id: str = ""         # 账号标识（"main"/"sub1"/"sub2"）
    name: str = ""               # 显示名
    role: str = "main"           # 角色（"main" / "sub"）
    enabled: bool = True
    region: str = "cn"           # 区服
    device_id: str = ""          # 绑定的模拟器设备 ID
    server: str = ""             # 区服(同 region)
    task_scope: list[str] = field(default_factory=lambda: ["daily", "permanent", "event", "special"])
    team_group: str = ""         # 组队分组标识
    teaming_enabled: bool = True # 是否允许作为组队小号被调用


class TeamAction:
    """组队协调动作枚举（§5.2）"""
    ACCEPT_INVITE = "accept_invite"   # 接受组队邀请
    APPLY_TEAM = "apply_team"         # 申请入队
    LEAVE_TEAM = "leave_team"         # 离开队伍
    PREPARE_JOIN = "prepare_join"     # 前置准备（打开组队界面等）


class AccountManager:
    """
    账号管理器（§5.3 方法定义）。

    加载 accounts.yaml → 管理全部账号配置 → 切换账号（含设备/状态联动）
    → 查询任务范围 → 组队协调。
    """

    def __init__(
        self,
        config: Any = None,                # ConfigManager 或 AccountsConfig（兼容）
        connection: Any = None,             # §2.1 ADBClient
        state_manager: Any = None,          # §2.1 StateManager
        event_bus: EventBus | None = None,  # §2.1 EventBus
        scheduler: Any = None,              # §2.1 Scheduler
        cookie_dir: str | Path = "config/cookies",
    ):
        self._config = config                    # ConfigManager（说明书 §2.1 要求名）
        self._config_mgr = self._config          # 兼容别名
        self._connection = connection           # ADBClient（切换设备）
        self._state_manager = state_manager      # StateManager（说明书 §2.1 要求名）
        self._state_mgr = self._state_manager    # 兼容别名
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名
        self._scheduler = scheduler             # Scheduler（刷新日程）

        self._cookie_dir = Path(cookie_dir)
        self._cookie_dir.mkdir(parents=True, exist_ok=True)

        # §2.3 内部属性
        self._accounts: dict[str, AccountInfo] = {}  # id → AccountInfo
        self._current_id: str | None = None
        self._accounts_lock = threading.Lock()
        self._login_status: dict[str, str] = {}      # id → status

        # 加载配置
        self.load_accounts()

    # ═══════════════════════════════════════════════════════════
    #  §2.2 对外暴露属性
    # ═══════════════════════════════════════════════════════════

    @property
    def current_account_id(self) -> str | None:
        """当前操作的账号 ID（§2.2）"""
        return self._current_id

    @property
    def current_account_role(self) -> str | None:
        """当前账号角色（§2.2）"""
        info = self._accounts.get(self._current_id) if self._current_id else None
        return info.role if info else None

    @property
    def account_list(self) -> list[AccountInfo]:
        """所有已配置的账号列表（§2.2）"""
        with self._accounts_lock:
            return list(self._accounts.values())

    @property
    def main_account(self) -> AccountInfo | None:
        """主号信息（§2.2）"""
        for info in self._accounts.values():
            if info.role == "main":
                return info
        return None

    @property
    def sub_accounts(self) -> list[AccountInfo]:
        """小号列表（§2.2）"""
        return [info for info in self._accounts.values() if info.role == "sub"]

    # ── 兼容旧属性 ─────────────────────────────────────────

    @property
    def current(self) -> str | None:
        return self._current_id

    @property
    def accounts(self) -> list:
        """兼容旧版返回 AccountEntry 列表"""
        return [a for a in self._accounts.values()]

    @property
    def enabled_accounts(self) -> list[AccountInfo]:
        return [a for a in self._accounts.values() if a.enabled]

    # ═══════════════════════════════════════════════════════════
    #  §5.3 配置加载
    # ═══════════════════════════════════════════════════════════

    def load_accounts(self) -> None:
        """
        从 accounts.yaml 加载全部账号配置（§5.3 + §2.1）。

        由 16-应用启动引导 在初始化时调用。
        """
        raw_accounts: list[dict] = []

        # 从 ConfigManager 读取
        if self._config and hasattr(self._config, 'get_section'):
            try:
                section = self._config_mgr.get_section("accounts")
                raw_accounts = section.get("accounts", [])
            except Exception:
                raw_accounts = []
        # 兼容旧版：直接传 AccountsConfig
        elif self._config_mgr and hasattr(self._config_mgr, 'accounts'):
            raw_accounts = [
                {"name": a.name, "enabled": a.enabled, "region": getattr(a, 'region', 'cn'),
                 "role": "main" if i == 0 else "sub"}
                for i, a in enumerate(self._config_mgr.accounts)
            ]

        with self._accounts_lock:
            self._accounts.clear()
            for i, raw in enumerate(raw_accounts):
                if isinstance(raw, dict):
                    name = raw.get("name", f"account_{i}")
                    aid = raw.get("account_id", raw.get("id", name))
                    role = raw.get("role", "main" if i == 0 else "sub")
                    self._accounts[aid] = AccountInfo(
                        account_id=aid,
                        name=name,
                        role=role,
                        enabled=raw.get("enabled", True),
                        region=raw.get("region", "cn"),
                        device_id=raw.get("device_id", ""),
                        server=raw.get("server", raw.get("region", "cn")),
                        task_scope=raw.get("task_scope",
                                           ["daily", "permanent", "event", "special"] if role == "main"
                                           else ["permanent"]),
                        team_group=raw.get("team_group", ""),
                        teaming_enabled=raw.get("teaming_enabled", role == "sub"),
                    )

        # 设置当前账号
        if not self._current_id and self._accounts:
            main = self.main_account
            self._current_id = main.account_id if main else list(self._accounts.keys())[0]

    # ── 兼容旧接口 ─────────────────────────────────────────

    def load_config(self, config: Any) -> None:
        """兼容旧版 load_config"""
        self._config_mgr = config
        self.load_accounts()

    def get_account(self, name: str) -> AccountInfo | None:
        """兼容旧版 get_account"""
        return self._accounts.get(name)

    # ═══════════════════════════════════════════════════════════
    #  §5.3 账号切换
    # ═══════════════════════════════════════════════════════════

    def switch_to(self, account_id: str) -> bool:
        """
        切换到指定账号（§3.1 + §5.3）。

        含设备切换 + 状态更新 + 事件通知 + 调度刷新。
        返回 True=成功 / False=失败。
        """
        with self._accounts_lock:
            info = self._accounts.get(account_id)
            if not info:
                return False
            if not info.enabled:
                return False

            old_id = self._current_id
            old_info = self._accounts.get(old_id) if old_id else None

            # 切换设备
            if self._connection and info.device_id:
                try:
                    if hasattr(self._connection, 'switch_device'):
                        self._connection.switch_device(info.device_id)
                except Exception:
                    # 连接失败 → 回退原设备
                    if old_info and old_info.device_id and hasattr(self._connection, 'switch_device'):
                        try:
                            self._connection.switch_device(old_info.device_id)
                        except Exception:
                            pass
                    return False

            self._current_id = account_id

        # 更新状态管理
        if self._state_mgr:
            try:
                self._state_mgr.set_state("current_account", account_id)
                self._state_mgr.set_state("account_role", info.role)
            except Exception:
                pass

        # 发布事件
        self._bus.publish(Events.ACCOUNT_SWITCHED, source="account_manager",
                         account_id=account_id, role=info.role, old=old_id)

        # 通知 scheduler 刷新
        if self._scheduler and hasattr(self._scheduler, 'build_schedule'):
            try:
                self._scheduler.build_schedule()
            except Exception:
                pass

        return True

    def get_current(self) -> AccountInfo | None:
        """获取当前账号信息（§5.3）"""
        if not self._current_id:
            return None
        return self._accounts.get(self._current_id)

    def is_main(self) -> bool:
        """当前是否主号（§5.3）"""
        info = self.get_current()
        return info is not None and info.role == "main"

    def get_task_scope(self) -> list[str]:
        """
        获取当前账号可执行的任务分类（§3.2 + §5.3）。

        主号默认全部可执行，小号仅可执行 permanent 类。
        """
        info = self.get_current()
        if not info:
            return []
        return info.task_scope or (["daily", "permanent", "event", "special"]
                                   if info.role == "main" else ["permanent"])

    def get_all_accounts(self) -> list[AccountInfo]:
        """获取全部账号列表（§5.3）"""
        with self._accounts_lock:
            return list(self._accounts.values())

    def switch_next(self) -> bool:
        """
        按 accounts.yaml 顺序遍历到下一个账号（§3.3 + §5.3）。

        main → 第一个 sub → 第二个 sub → ... → 最后一个 → 返回 False
        """
        subs = self.sub_accounts
        if not subs:
            return False

        if self._current_id == (self.main_account.account_id if self.main_account else None):
            # 当前是 main → 切到第一个 sub
            return self.switch_to(subs[0].account_id)

        # 查找当前 sub 的下一个
        for i, s in enumerate(subs):
            if s.account_id == self._current_id:
                if i + 1 < len(subs):
                    return self.switch_to(subs[i + 1].account_id)
                return False  # 最后一个 sub

        return False

    # ═══════════════════════════════════════════════════════════
    #  §3.4 组队协调
    # ═══════════════════════════════════════════════════════════

    def get_teaming_partners(self, group: str) -> list[AccountInfo]:
        """
        获取指定分组中可用的组队小号列表（§3.4 + §5.3）。

        筛选条件：同 group + teaming_enabled=True + 已启用。
        """
        result = []
        for info in self._accounts.values():
            if info.role != "sub":
                continue
            if not info.enabled or not info.teaming_enabled:
                continue
            if group and info.team_group and info.team_group != group:
                continue
            result.append(info)
        return result

    def prepare_teaming(self, task_name: str) -> dict[str, bool]:
        """
        为指定任务准备组队（§3.4 + §5.3）。

        依次唤醒小号、完成前置操作。
        返回 {account_id: 是否就绪} 字典。
        """
        results: dict[str, bool] = {}
        old_id = self._current_id

        for partner in self.get_teaming_partners(""):
            try:
                ok = self.switch_to(partner.account_id)
                results[partner.account_id] = ok
                # 更新 sub_account_status
                if self._state_mgr and ok:
                    status_map = self._state_mgr.get_state("sub_account_status", {})
                    from core.run_state import SubStatus
                    status_map[partner.account_id] = SubStatus(
                        account_id=partner.account_id,
                        status="teaming",
                        task=f"准备组队: {task_name}",
                    )
                    self._state_mgr.set_state("sub_account_status", status_map)
            except Exception:
                results[partner.account_id] = False

        # 切回原账号
        if old_id:
            self.switch_to(old_id)

        # 发布事件
        self._bus.publish(Events.TEAMING_PREPARED, source="account_manager",
                         task_name=task_name, results=results)
        return results

    def coordinate_action(self, account_id: str, action: str, params: dict | None = None) -> bool:
        """
        在指定账号上执行协调操作（§3.4 + §5.3）。

        切换账号 → 更新 sub_account_status → 发布 coordinate_action 事件。
        09-运行控制中心 订阅后通过 Executor 执行实际识图/点击。
        """
        try:
            old = self._current_id
            ok = self.switch_to(account_id)
            if not ok:
                return False

            # 更新状态
            if self._state_mgr:
                status_map = self._state_mgr.get_state("sub_account_status", {})
                from core.run_state import SubStatus
                status_map[account_id] = SubStatus(
                    account_id=account_id,
                    status="teaming",
                    task=f"执行: {action}",
                )
                self._state_mgr.set_state("sub_account_status", status_map)

            # 发布事件
            self._bus.publish(Events.COORDINATE_ACTION, source="account_manager",
                             account_id=account_id, action=action, params=params or {})

            if old:
                self.switch_to(old)
            return True
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════════
    #  登录状态 + Cookie
    # ═══════════════════════════════════════════════════════════

    def set_login_status(self, name: str, status: str) -> None:
        """设置登录状态"""
        self._login_status[name] = status
        if status == "online":
            self._bus.publish(Events.ACCOUNT_LOGIN, name=name)
        elif status == "offline":
            self._bus.publish(Events.ACCOUNT_LOGOUT, name=name)
        elif status == "error":
            self._bus.publish(Events.ACCOUNT_ERROR, name=name)

    def get_login_status(self, name: str) -> str:
        return self._login_status.get(name, "unknown")

    def is_online(self, name: str | None = None) -> bool:
        target = name or self._current_id
        if not target:
            return False
        return self._login_status.get(target) == "online"

    def save_cookies(self, name: str, cookies: dict[str, str]) -> None:
        path = self._cookie_dir / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

    def load_cookies(self, name: str) -> dict[str, str]:
        path = self._cookie_dir / f"{name}.json"
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def delete_cookies(self, name: str) -> bool:
        path = self._cookie_dir / f"{name}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # ── 兼容旧接口 ─────────────────────────────────────────

    def add_account(self, entry: Any) -> bool:
        # 兼容旧版
        return False

    def remove_account(self, name: str) -> bool:
        return False

    def update_account(self, name: str, **updates: Any) -> bool:
        return False

    def get_current_account(self) -> AccountEntry | None:
        """获取当前账号"""
        if not self._current:
            return None
        return self.get_account(self._current)
