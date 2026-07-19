"""
状态键名规范（07-状态管理模块）

集中定义所有跨模块共享的运行时状态键名，避免硬编码字符串。
"""


class StateKeys:
    """状态键名常量。按类别分组。"""

    # ==================== 运行状态 ====================
    RUN_STATUS = "run_status"              # "running" / "paused" / "stopped" / "stopping" / "error"
    RUN_START_TIME = "run_start_time"      # 本次运行开始时刻（datetime）
    TODAY_RUN_DURATION = "today_run_duration"  # 今日累计运行秒数

    # ==================== 账号状态 ====================
    CURRENT_ACCOUNT = "current_account"    # "main" / "sub1" / "sub2"
    ACCOUNT_ROLE = "account_role"           # "main" / "sub"

    # ==================== 连接状态 ====================
    CONNECTION_STATUS = "connection_status"    # "connected" / "disconnected" / "reconnecting"
    ACTIVE_DEVICE_ID = "active_device_id"       # "127.0.0.1:16384"

    # ==================== 场景状态 ====================
    CURRENT_SCENE = "current_scene"        # "courtyard" / "battle" / "explore" / "loading" / ...

    # ==================== 任务执行状态 ====================
    CURRENT_TASK = "current_task"          # 当前执行的任务名
    CURRENT_STEP = "current_step"          # 当前执行的步骤名
    TASK_PROGRESS = "task_progress"        # 进度字符串 "15/30"
    SCHEDULE_QUEUE = "schedule_queue"      # 当前日程队列（任务名列表）

    # ==================== 安全状态 ====================
    TODAY_OPERATION_COUNT = "today_operation_count"  # 今日操作次数
    RUN_LIMIT_REACHED = "run_limit_reached"          # 是否已达运行上限
    SAFETY_PROFILE = "safety_profile"                # 当前安全档位 "normal" / "safe" / "fast" / "debug"
