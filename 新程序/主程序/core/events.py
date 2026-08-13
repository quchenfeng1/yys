"""
08-事件通信总线

事件名常量定义。
所有事件名使用小写+下划线风格，按模块划分命名空间。
"""
from __future__ import annotations
from typing import Final


class Events:
    """事件名前缀常量（无实例化）"""

    # ── 设备事件 device ─────────────────────────────────────
    DEVICE_CONNECTED: Final[str] = "device.connected"
    DEVICE_DISCONNECTED: Final[str] = "device.disconnected"
    DEVICE_ERROR: Final[str] = "device.error"
    DEVICE_HEARTBEAT: Final[str] = "device.heartbeat"
    DEVICE_SCREENSHOT: Final[str] = "device.screenshot"
    DEVICE_ORIENTATION_CHANGED: Final[str] = "device.orientation_changed"

    # ── 图像事件 image ─────────────────────────────────────
    IMAGE_MATCH_FOUND: Final[str] = "image.match_found"
    IMAGE_MATCH_NOT_FOUND: Final[str] = "image.match_not_found"
    IMAGE_TEMPLATE_LOADED: Final[str] = "image.template_loaded"
    IMAGE_TEMPLATE_MISSING: Final[str] = "image.template_missing"
    IMAGE_OCR_COMPLETED: Final[str] = "image.ocr_completed"

    # ── 任务事件 task ───────────────────────────────────────
    TASK_STARTED: Final[str] = "task.started"
    TASK_COMPLETED: Final[str] = "task.completed"
    TASK_FAILED: Final[str] = "task.failed"
    TASK_SKIPPED: Final[str] = "task_skipped"  # 与调度段统一，避免重复定义
    TASK_PROGRESS: Final[str] = "task.progress"
    TASK_TIMEOUT: Final[str] = "task.timeout"
    TASK_INTERRUPTED: Final[str] = "task.interrupted"
    TASK_QUEUED: Final[str] = "task.queued"
    TASK_REMOVED: Final[str] = "task.removed"
    TASK_REORDERED: Final[str] = "task.reordered"

    # ── 执行器事件 executor ────────────────────────────────
    EXECUTOR_STEP_STARTED: Final[str] = "executor.step_started"
    EXECUTOR_STEP_COMPLETED: Final[str] = "executor.step_completed"
    EXECUTOR_STEP_FAILED: Final[str] = "executor.step_failed"
    EXECUTOR_STEP_RETRY: Final[str] = "executor.step_retry"
    EXECUTOR_BATCH_STARTED: Final[str] = "executor.batch_started"
    EXECUTOR_BATCH_COMPLETED: Final[str] = "executor.batch_completed"

    # ── 调度事件 scheduler ─────────────────────────────────
    SCHEDULER_TICK: Final[str] = "scheduler.tick"
    SCHEDULER_TASK_DUE: Final[str] = "scheduler.task_due"
    SCHEDULER_IDLE: Final[str] = "scheduler.idle"
    SCHEDULER_OVERRUN: Final[str] = "scheduler.overrun"

    # ── 配置事件 config ─────────────────────────────────────
    CONFIG_RELOADED: Final[str] = "config.reloaded"
    CONFIG_CHANGED: Final[str] = "config.changed"
    CONFIG_ERROR: Final[str] = "config.error"
    CONFIG_HOT_RELOAD: Final[str] = "config.hot_reload"

    # ── 状态事件 state ─────────────────────────────────────
    STATE_CHANGED: Final[str] = "state.changed"
    STATE_KEY_UPDATED: Final[str] = "state.key_updated"
    STATE_RESET: Final[str] = "state.reset"
    STATE_SNAPSHOT: Final[str] = "state.snapshot"

    # ── 运行事件 run ───────────────────────────────────────
    RUN_STARTED: Final[str] = "run.started"
    RUN_STOPPED: Final[str] = "run.stopped"
    RUN_PAUSED: Final[str] = "run.paused"
    RUN_RESUMED: Final[str] = "run.resumed"
    RUN_ERROR: Final[str] = "run.error"
    RUN_SHUTDOWN: Final[str] = "run.shutdown"

    # ── 账号事件 account ───────────────────────────────────
    ACCOUNT_SWITCHED: Final[str] = "account.switched"
    ACCOUNT_LOGIN: Final[str] = "account.login"
    ACCOUNT_LOGOUT: Final[str] = "account.logout"
    ACCOUNT_ERROR: Final[str] = "account.error"
    ACCOUNT_COOKIE_REFRESHED: Final[str] = "account.cookie_refreshed"

    # ── 请求事件 request ────────────────────────────────────
    START_REQUESTED: Final[str] = "start_requested"
    STOP_REQUESTED: Final[str] = "stop_requested"
    PAUSE_REQUESTED: Final[str] = "pause_requested"
    RESUME_REQUESTED: Final[str] = "resume_requested"

    # ── 日志/通知事件 log ───────────────────────────────────
    LOG_ALERT: Final[str] = "log.alert"
    LOG_ERROR_OCCURRED: Final[str] = "log.error_occurred"
    LOG_RECORD: Final[str] = "log_record"
    NOTIFY_ALERT: Final[str] = "notify_alert"

    # ── 防封事件 anti_detect ───────────────────────────────
    ANTI_DETECT_TRIGGERED: Final[str] = "anti_detect.triggered"
    ANTI_DETECT_BLOCKED: Final[str] = "anti_detect.blocked"
    ANTI_DETECT_HUMAN_CHECK: Final[str] = "anti_detect.human_check"
    ANTI_DETECT_RATE_LIMITED: Final[str] = "anti_detect.rate_limited"

    # ── 连接事件 connection ─────────────────────────────────
    CONNECTION_LOST: Final[str] = "connection_lost"
    CONNECTION_RESTORED: Final[str] = "connection_restored"
    CONNECTION_ERROR: Final[str] = "connection_error"
    CONNECTION_QUALITY_WARNING: Final[str] = "connection_quality_warning"

    # ── 调度事件 schedule ───────────────────────────────────
    SCHEDULE_UPDATED: Final[str] = "schedule_updated"
    TASK_DUE: Final[str] = "task_due"

    # ── 触发监控 trigger ────────────────────────────────────
    TRIGGER_DETECTED: Final[str] = "trigger_detected"  # TriggerWatcher 识别命中触发模板，05 订阅后置任务为到期

    # ── 运行限制 run_limit ──────────────────────────────────
    RUN_LIMIT_REACHED: Final[str] = "run_limit_reached"

    # ── 场景事件 scene ──────────────────────────────────────
    SCENE_UNKNOWN: Final[str] = "scene_unknown"
    SCENE_UPDATED: Final[str] = "scene_updated"  # 场景感知命中（detect_scene/probe_scene），07 维护 current_scene、11 显示当前场景
    SCENE_SIGNAL: Final[str] = "scene_signal"    # 识图素材信号触发：scene/ 素材（配置了 signal）被识别命中时发布（signal=信号名）

    # ── 应用事件 app ────────────────────────────────────────
    APP_STARTED: Final[str] = "app_started"
    APP_STOPPING: Final[str] = "app_stopping"
    PREFLIGHT_COMPLETE: Final[str] = "preflight_complete"

    # ── 任务列表事件 tasks_list ─────────────────────────────
    TASKS_LIST_CHANGED: Final[str] = "tasks_list_changed"

    # ── 素材事件 assets ─────────────────────────────────────
    ASSETS_MISSING: Final[str] = "assets_missing"

    # ── 快照事件 snapshot ───────────────────────────────────
    SNAPSHOT_CREATED: Final[str] = "snapshot_created"

    # ── 任务生命周期（§6.2 兼容别名）────────────────────────
    TASK_DONE: Final[str] = "task_done"                     # 设计书 §6.2 要求
    STEP_DONE: Final[str] = "step_done"                     # 设计书 §6.2 要求

    # ── OCR 事件 ───────────────────────────────────────────
    OCR_RESULT: Final[str] = "ocr_result"                   # 设计书 §6.2 要求

    # ── 组队事件（§6.2）───────────────────────────────────
    TEAMING_PREPARED: Final[str] = "teaming_prepared"       # 设计书 §6.2 要求
    COORDINATE_ACTION: Final[str] = "coordinate_action"      # 设计书 §6.2 要求

    # ── 错误事件（§6.2）────────────────────────────────────
    ERROR_OCCURRED: Final[str] = "error_occurred"           # 设计书 §6.2 要求

    # ── 启动事件 bootstrap ─────────────────────────────────
    BOOTSTRAP_STARTED: Final[str] = "bootstrap.started"
    BOOTSTRAP_STEP: Final[str] = "bootstrap.step"
    BOOTSTRAP_COMPLETED: Final[str] = "bootstrap.completed"
    BOOTSTRAP_ERROR: Final[str] = "bootstrap.error"

    # ── 可视化构建事件 visual（17-可视化构建模块）────────────
    VISUAL_TASK_CHANGED: Final[str] = "visual.task_changed"       # 可视化任务保存/删除 → UI 刷新
    VISUAL_UNKNOWN: Final[str] = "visual.unknown"                 # 示教运行遇未知画面（截图路径+信息）
    VISUAL_TEACH_BLOCKED: Final[str] = "visual.teach_blocked"     # 示教阻断开始
    VISUAL_TEACH_RESUMED: Final[str] = "visual.teach_resumed"     # 示教恢复
    VISUAL_ACTION_RECEIVED: Final[str] = "visual.action_received" # 用户指示（场景/点击点/规则）
    VISUAL_TEACH_PROGRESS: Final[str] = "visual.teach_progress"   # 示教运行日志

    @classmethod
    def all(cls) -> list[str]:
        """返回所有事件名列表"""
        return [
            v for k, v in vars(cls).items()
            if not k.startswith("_") and isinstance(v, str)
        ]

