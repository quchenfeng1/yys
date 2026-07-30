"""
10-参数桥接模块

参数 Schema 定义（§5.2 ParamSchema）。
定义各模块之间传递参数的格式。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ParamSchema:
    """参数 schema 定义（§5.2）"""
    key: str                                    # 参数键名
    label: str = ""                              # UI 显示标签
    type: type = str                             # 参数类型
    default: Any = None                          # 默认值
    required: bool = False                       # 是否必填
    validator: Callable[[Any], bool] | None = None  # 校验函数
    options: list | None = None                  # 枚举值列表
    description: str = ""                        # 参数说明


@dataclass
class TaskParamSchema:
    """任务执行参数"""
    task_id: str = ""
    priority: int = 0
    max_retries: int = 3
    timeout: float = 300.0
    dry_run: bool = False
    account_name: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceParamSchema:
    """设备参数"""
    serial: str = ""
    adb_host: str = "127.0.0.1"
    adb_port: int = 5037
    screenshot_method: str = "adb"
    screenshot_quality: int = 80


@dataclass
class RunParamSchema:
    """运行参数"""
    mode: str = "auto"
    account_name: str = ""
    task_ids: list[str] = field(default_factory=list)
    max_consecutive_errors: int = 5
    error_recovery: bool = True
