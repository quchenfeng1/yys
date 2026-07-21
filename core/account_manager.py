"""
15-账号管理模块（Account Management Module）

职责：
  加载 accounts.yaml，管理主号和小号的配置信息、切换、任务范围过滤

依赖注入：
  _config      ConfigManager    读取 accounts.yaml 配置
  _connection  ConnectionManager 账号切换时调 switch_device()
  _state       StateManager     更新当前账号状态
  _event_bus   EventBus         发布 account_switched 事件
  _scheduler   Scheduler        切换后刷新日程表范围
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AccountInfo:
    """账号信息数据结构"""
    id: str                              # 账号标识 "main"/"sub1"/"sub2"
    role: str                            # 角色 "main"/"sub"
    device_id: str                       # 绑定的模拟器设备 ID
    server: str = ""                     # 区服
    task_scope: list[str] = field(default_factory=lambda: ["daily", "permanent"])
    team_group: str = ""                 # 组队分组标识，同组可互相组队
    teaming_enabled: bool = False        # 是否允许作为组队小号被调用


class AccountManager:
    """账号管理主入口"""

    def __init__(self, config, connection, state_manager, event_bus, scheduler):
        self._config = config
        self._connection = connection
        self._state = state_manager
        self._event_bus = event_bus
        self._scheduler = scheduler
        self._accounts: dict[str, AccountInfo] = {}
        self._current_id: Optional[str] = None

    # ── 公开方法 ──────────────────────────────────────────────

    def load_accounts(self) -> None:
        """从 accounts.yaml 加载全部账号配置"""
        raw = self._config.get("accounts", {})
        for acc_id, info in raw.items():
            self._accounts[acc_id] = AccountInfo(
                id=acc_id,
                role=info.get("role", "sub"),
                device_id=info.get("device_id", ""),
                server=info.get("server", ""),
                task_scope=info.get("task_scope", ["permanent"]),
                team_group=info.get("team_group", ""),
                teaming_enabled=info.get("teaming_enabled", False),
            )
        # 默认选中第一个 main 账号
        if "main" in self._accounts:
            self._current_id = "main"
        logger.info(f"已加载 {len(self._accounts)} 个账号")

    def switch_to(self, account_id: str) -> bool:
        """切换到指定账号（含设备切换）"""
        if account_id not in self._accounts:
            logger.warning(f"账号 {account_id} 不存在")
            return False

        info = self._accounts[account_id]
        old_id = self._current_id

        # 切换模拟器连接
        if not self._connection.switch_device(info.device_id):
            logger.error(f"切换到账号 {account_id} 的设备 {info.device_id} 失败")
            return False

        self._current_id = account_id
        # 更新状态管理
        self._state.set_state("current_account", account_id)
        self._state.set_state("account_role", info.role)
        # 发布事件
        self._event_bus.publish("account_switched",
                                 account_id=account_id,
                                 role=info.role,
                                 old_account=old_id)
        logger.info(f"已切换到账号 {account_id} ({info.role})")
        return True

    def get_current(self) -> Optional[AccountInfo]:
        """获取当前账号信息"""
        if self._current_id:
            return self._accounts.get(self._current_id)
        return None

    def get_task_scope(self) -> list[str]:
        """获取当前账号可执行的任务分类"""
        current = self.get_current()
        return current.task_scope if current else ["permanent"]

    def get_all_accounts(self) -> list[AccountInfo]:
        """获取全部账号列表"""
        return list(self._accounts.values())

    def get_teaming_partners(self, group: str = "") -> list[AccountInfo]:
        """获取指定分组中可用的组队小号列表"""
        result = []
        for acc in self._accounts.values():
            if acc.teaming_enabled and (not group or acc.team_group == group):
                if acc.id != self._current_id:  # 排除自己
                    result.append(acc)
        return result

    def prepare_teaming(self, task_name: str) -> bool:
        """为指定任务准备组队：唤醒小号并等待就绪"""
        partners = self.get_teaming_partners()
        if not partners:
            return False
        for partner in partners:
            if not self.switch_to(partner.id):
                return False
            # 等待小号加载到庭院/组队界面
            self._event_bus.publish("teaming_prepared",
                                     account_id=partner.id,
                                     task_name=task_name)
        # 切回主号
        self.switch_to("main")
        return True

    def coordinate_action(self, account_id: str, action: str, params: dict = None) -> bool:
        """在指定账号上执行协调操作"""
        old_id = self._current_id
        if not self.switch_to(account_id):
            return False
        # 发布协调指令，由 09-运行控制中心 的对应 handler 执行具体操作
        self._event_bus.publish("coordinate_action",
                                 account_id=account_id,
                                 action=action,
                                 params=params or {})
        # 切回原账号
        if old_id:
            self.switch_to(old_id)
        return True

    def is_main(self) -> bool:
        """当前是否主号"""
        current = self.get_current()
        return current is not None and current.role == "main"

    def switch_next(self) -> bool:
        """切换到下一个账号（多开遍历用）"""
        ids = list(self._accounts.keys())
        if not ids:
            return False
        if self._current_id is None:
            return self.switch_to(ids[0])
        idx = ids.index(self._current_id)
        next_idx = (idx + 1) % len(ids)
        return self.switch_to(ids[next_idx])
