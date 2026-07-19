"""
事件名常量定义（08-事件总线模块）

定义所有模块间通信的事件名称，避免硬编码字符串。
命名规范：past_tense 过去式（如 task_done 而非 do_task）。
"""


class Events:
    """事件名常量。按类别分组。"""

    # ==================== 运行控制事件 ====================
    START_REQUESTED = "start_requested"          # UI → RunController：用户点击启动
    STOP_REQUESTED = "stop_requested"            # UI → RunController+Scheduler+Task：用户点击停止
    PAUSE_REQUESTED = "pause_requested"          # UI → RunController：用户点击暂停
    RUN_STARTED = "run_started"                  # RunController → UI+StateManager：运行已启动
    RUN_PAUSED = "run_paused"                    # RunController → UI+StateManager：运行已暂停
    RUN_STOPPED = "run_stopped"                  # RunController → UI+StateManager：运行已停止
    RUN_LIMIT_REACHED = "run_limit_reached"       # AntiDetect → RunController+UI：达到运行上限

    # ==================== 连接事件 ====================
    CONNECTION_LOST = "connection_lost"           # ConnectionManager → RunController+UI+StateManager
    CONNECTION_RESTORED = "connection_restored"   # ConnectionManager → RunController+UI+StateManager
    CONNECTION_ERROR = "connection_error"          # ConnectionManager → UI+Monitor

    # ==================== 任务事件 ====================
    TASK_STARTED = "task_started"                 # RunController → UI+StateManager+Monitor
    TASK_DONE = "task_done"                       # RunController → UI+Scheduler+Monitor
    STEP_DONE = "step_done"                       # TaskGraph → UI+Monitor
    TASK_SKIPPED = "task_skipped"                 # Scheduler → UI+Monitor

    # ==================== 调度事件 ====================
    SCHEDULE_UPDATED = "schedule_updated"          # Scheduler → UI
    TASK_DUE = "task_due"                         # Scheduler → RunController
    DAILY_RESET = "daily_reset"                    # Scheduler → self+StateManager

    # ==================== 状态事件 ====================
    STATE_CHANGED = "state_changed"               # StateManager → UI+相关模块
    CONFIG_CHANGED = "config_changed"              # ConfigManager → 相关模块
    ACCOUNT_SWITCHED = "account_switched"          # AccountManager → Connection+StateManager

    # ==================== 日志事件 ====================
    LOG_RECORD = "log_record"                     # Monitor → UI LogPanel
