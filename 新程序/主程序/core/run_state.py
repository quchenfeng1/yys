"""
07-运行时状态管理 / 09-运行控制中心

运行状态枚举 + 运行时数据结构。
对应设计书 §2.2 RuntimeProgress / Finding / SubStatus / RunState。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class RunState(str, Enum):
    """运行状态枚举（§5.2 RunState）"""
    STOPPED = "stopped"       # 停止
    RUNNING = "running"       # 运行中
    PAUSED = "paused"         # 暂停
    ERROR = "error"           # 异常停止


@dataclass
class RuntimeProgress:
    """
    运行时进度（§2.4 RuntimeProgress + §5.2）。

    对应设计书 §2.2 task_runtime_progress 中的逐任务进度结构。
    存储于 StateManager 的 "task_runtime_progress" 键中，
    以 dict[str, RuntimeProgress] 形式使用。
    """
    task_name: str = ""             # 任务名，如 "yuhun"
    # §5.2 设计书字段
    completed_cycles: int = 0       # 已完成循环次数
    last_run_time: float = 0.0      # 最后执行时间戳
    total_success: int = 0          # 累计成功次数
    total_failures: int = 0         # 累计失败次数
    # 运行时扩展字段
    completed: int = 0              # 已完成次数（向前兼容）
    total: int = 0                  # 总目标次数
    updated: str = ""               # 最后更新时间
    loop_type: str = "count"        # 循环类型："count"（次数）或 "duration"（时长）

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return self.completed / self.total

    @property
    def summary(self) -> str:
        return f"任务={self.task_name} 完成={self.completed}/{self.total} 类型={self.loop_type}"

    def reset(self) -> None:
        self.completed = 0
        self.total = 0
        self.updated = ""
        self.loop_type = "count"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_name": self.task_name,
            "completed": self.completed,
            "total": self.total,
            "updated": self.updated,
            "loop_type": self.loop_type,
        }


@dataclass
class Finding:
    """
    小号扫描发现物（§2.4 Finding + §5.2）。

    存储于 StateManager 的 "sub_account_findings" 键中，
    以 dict[str, list[Finding]] 形式使用。
    """
    sub_account_id: str = ""        # 小号 ID
    finding_type: str = ""          # 类型："collab"（协作）/ "shop"（商店商品）
    # §5.2 设计书字段
    content: str = ""               # 内容描述文本
    value: float = 0.0              # 价值评分（0~100），用于对比
    timestamp: str = ""             # 发现时间（ISO 格式字符串）


@dataclass
class SubStatus:
    """
    小号实时状态（§2.4 SubStatus）。

    存储于 StateManager 的 "sub_account_status" 键中，
    以 dict[str, SubStatus] 形式使用。
    """
    account_id: str = ""        # 小号标识 "sub1"/"sub2"
    status: str = "idle"        # idle / scanning / teaming / battling / login / error
    task: str = ""              # 当前正在做的事
    progress: str = ""          # 进度描述，如 "2/3" / "第15轮"
    last_updated: str = ""      # 最后更新时间戳
