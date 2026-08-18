"""
10-参数桥接模块

ParamBridge 聚合入口（§5.1）。
UI 模块通过此入口与所有核心模块通信。

模块结构：
├── schemas.py         ← 参数 schema 定义
├── ui_binding.py      ← UI 数据绑定层（控件↔配置双向同步）
├── run_bridge.py      ← 运行传参（启停信号桥接）
├── task_bridge.py     ← 任务参数传参（优先级/规则/阵容）
├── account_bridge.py  ← 账号传参
└── config_bridge.py   ← 通用配置传参
"""
from __future__ import annotations

from typing import Any

from core.event_bus import EventBus, get_global_bus
from core.events import Events
from ui.param_bridge.account_bridge import AccountBridge
from ui.param_bridge.config_bridge import ConfigBridge
from ui.param_bridge.run_bridge import RunBridge
from ui.param_bridge.system_bridge import SystemBridge
from ui.param_bridge.task_bridge import TaskBridge
from ui.param_bridge.ui_binding import UIBinding
from ui.param_bridge.schemas import (
    ParamSchema,
    TaskParamSchema,
    DeviceParamSchema,
    RunParamSchema,
)


class ParamBridge:
    """参数桥接聚合器（UI 的唯一通信入口，§5.1）"""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        config: Any = None,
        state_manager: Any = None,
        scheduler: Any = None,
        account_manager: Any = None,
        task_manager: Any = None,
        run_controller: Any = None,
        registry: Any = None,
        file_manager: Any = None,
    ):
        self._event_bus = event_bus or get_global_bus()
        self._bus = self._event_bus  # 兼容别名
        self._state_manager = state_manager  # §2.1 状态管理

        # §2.1 创建子桥接器
        self.account = AccountBridge(account_manager)
        self.config = ConfigBridge(config)
        self.run = RunBridge(event_bus=self._event_bus, controller=run_controller)
        self.system = SystemBridge(event_bus=self._event_bus)
        self.task = TaskBridge(
            registry=registry,
            scheduler=scheduler,
            task_manager=task_manager,
            config=config,
            file_manager=file_manager,
            event_bus=self._event_bus,
        )
        self.ui = UIBinding(event_bus=self._event_bus, config=config)

        # UIBinding 已在自身 init 中订阅 STATE_CHANGED，无需重复订阅

    # ── §5.3 ─────────────────────────────────────────────

    def bind_all(self) -> None:
        """注册所有 UI 控件绑定（由 MainWindow 初始化时调用，§5.3）"""
        # MainWindow 在构造 UI 后显式调用 bind()/bind_state() 逐控件注册
        pass

    @property
    def bindings(self) -> dict[str, Any]:
        """当前所有控件绑定注册表（§2.2）"""
        return dict(self.ui._bindings) if hasattr(self.ui, '_bindings') else {}

    def get_all_bridges(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "config": self.config,
            "run": self.run,
            "system": self.system,
            "task": self.task,
            "ui": self.ui,
        }


__all__ = [
    "ParamBridge",
    "AccountBridge",
    "ConfigBridge",
    "RunBridge",
    "SystemBridge",
    "TaskBridge",
    "UIBinding",
    "ParamSchema",
    "TaskParamSchema",
    "DeviceParamSchema",
    "RunParamSchema",
]
