"""
07-运行时状态管理

状态键名常量（StateKeys 类）。
所有键名使用小写+下划线风格，按模块分区。
"""
from __future__ import annotations

from typing import Final


class StateKeys:
    """状态键名常量（无实例化）—— 下划线命名风格，与兼容性确认书一致"""

    # ── 运行状态 run ─────────────────────────────────────────
    RUN_STATUS: Final[str] = "run_status"                 # idle | running | paused | stopping | error
    RUN_START_TIME: Final[str] = "run_start_time"         # 启动时间
    TODAY_RUN_DURATION: Final[str] = "today_run_duration" # 今日运行时长
    CURRENT_TASK: Final[str] = "current_task"             # 当前执行的任务 ID
    CURRENT_STEP: Final[str] = "current_step"             # 当前步骤名
    TASK_PROGRESS: Final[str] = "task_progress"           # 进度 0.0~1.0
    TASK_RUNTIME_PROGRESS: Final[str] = "task_runtime_progress"  # 运行时进度 dict
    DRY_RUN_MODE: Final[str] = "dry_run_mode"             # 干运行模式

    # ── 队列状态 queue ──────────────────────────────────────
    SCHEDULE_QUEUE: Final[str] = "schedule_queue"         # 调度队列 list[TaskInfo]
    TASK_STATUS: Final[str] = "task_status"               # 任务状态 dict[str, ScheduleStatus]
    ACTIVITY_CALENDAR: Final[str] = "activity_calendar"   # 活动日历
    BATCH_SELECTION: Final[str] = "batch_selection"       # 批量选中的任务ID列表

    # ── 设备状态 device ─────────────────────────────────────
    CONNECTION_STATUS: Final[str] = "connection_status"   # connected | disconnected | reconnecting
    ACTIVE_DEVICE_ID: Final[str] = "active_device_id"     # 当前设备 ID
    DEVICE_RESOLUTION: Final[str] = "device_resolution"   # 分辨率

    # ── 账号状态 account ────────────────────────────────────
    CURRENT_ACCOUNT: Final[str] = "current_account"      # 当前账号名
    ACCOUNT_ROLE: Final[str] = "account_role"            # master | sub
    SUB_ACCOUNT_STATUS: Final[str] = "sub_account_status" # dict[str, SubStatus]

    # ── 场景状态 scene ──────────────────────────────────────
    CURRENT_SCENE: Final[str] = "current_scene"           # 当前场景名
    LAST_KNOWN_SCENE: Final[str] = "last_known_scene"     # 最后已知场景

    # ── 扫描结果 scan ───────────────────────────────────────
    SUB_ACCOUNT_FINDINGS: Final[str] = "sub_account_findings"  # dict[str, list[Finding]]
    BEST_FINDING: Final[str] = "best_finding"             # Finding | None

    # ── 运行时段 run_window ─────────────────────────────────
    RUN_WINDOW: Final[str] = "run_window"                 # tuple[str, str]
    SCHEDULED_START: Final[str] = "scheduled_start"       # str | None
    SCHEDULED_STOP: Final[str] = "scheduled_stop"         # str | None

    # ── 安全状态 security ───────────────────────────────────
    TODAY_OPERATION_COUNT: Final[str] = "today_operation_count"  # int
    RUN_LIMIT_REACHED: Final[str] = "run_limit_reached"   # bool

    # ── 防封状态 anti_detect ────────────────────────────────
    ANTI_ACTION_COUNT: Final[str] = "anti_action_count"   # 操作计数
    ANTI_LAST_ACTION: Final[str] = "anti_last_action"     # 最后操作时间
    ANTI_RISK_LEVEL: Final[str] = "anti_risk_level"       # 风险等级

    @classmethod
    def all(cls) -> list[str]:
        """返回所有状态键名列表"""
        return [
            v for k, v in vars(cls).items()
            if not k.startswith("_") and isinstance(v, str)
        ]

    @classmethod
    def module_keys(cls, module_prefix: str) -> list[str]:
        """返回指定模块前缀的所有键名"""
        return [v for v in cls.all() if v.startswith(module_prefix)]
