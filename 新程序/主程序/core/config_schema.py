"""
06-配置管理中心

配置 Schema 定义与校验。
使用 dataclass 描述 YAML 配置文件的结构。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.exceptions import ConfigValidationError


# ── 全局配置 ────────────────────────────────────────────────


@dataclass
class ADBConfig:
    """ADB 连接配置"""
    host: str = "127.0.0.1"
    port: int = 5037
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 2.0


@dataclass
class ScreenshotConfig:
    """截屏配置"""
    method: str = "adb"  # adb | minicap | scrpy
    quality: int = 80
    resize_ratio: float = 1.0
    cache: bool = True
    cache_ttl: float = 0.5


@dataclass
class ImageRecognitionConfig:
    """图像识别配置"""
    template_threshold: float = 0.8
    ocr_enabled: bool = True
    ocr_timeout: float = 10.0
    ocr_use_gpu: bool = False
    match_method: str = "cv2.TM_CCOEFF_NORMED"


@dataclass
class AntiDetectConfig:
    """防封策略配置"""
    enabled: bool = True
    min_interval: float = 1.0
    max_interval: float = 5.0
    action_jitter: bool = True
    mouse_simulation: bool = True
    random_fail_rate: float = 0.02
    behavior_profile: bool = True
    weekly_off_day: str = ""  # 每周休息日


@dataclass
class ScheduleConfig:
    """时间调度配置"""
    enabled: bool = False
    timezone: str = "Asia/Shanghai"
    crontab: str = ""


@dataclass
class LogConfig:
    """日志配置"""
    level: str = "INFO"
    dir: str = "logs"
    rotation: str = "10 MB"
    retention: str = "30 days"
    console: bool = True
    structured: bool = False


@dataclass
class DeviceConfig:
    """设备配置（多开）"""
    adb: ADBConfig = field(default_factory=ADBConfig)
    screenshot: ScreenshotConfig = field(default_factory=ScreenshotConfig)
    emulator_path: str = ""
    emulator_name: str = ""
    mock: bool = False  # 模拟设备模式（无真实模拟器调试用）


@dataclass
class GlobalConfig:
    """global.yaml 根结构"""
    _version: int = 0
    device: DeviceConfig = field(default_factory=DeviceConfig)
    image: ImageRecognitionConfig = field(default_factory=ImageRecognitionConfig)
    anti_detect: AntiDetectConfig = field(default_factory=AntiDetectConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    log: LogConfig = field(default_factory=LogConfig)


# ── 账号配置 ────────────────────────────────────────────────


@dataclass
class AccountEntry:
    """单个账号（§2.2 账号配置）"""
    account_id: str = ""             # 账号标识（"main"/"sub1"/"sub2"）
    name: str = ""                   # 显示名
    role: str = "sub"                # 角色（"main" / "sub"）
    enabled: bool = True
    region: str = "cn"               # 区服
    device_id: str = ""              # 绑定的模拟器设备 ID
    server: str = ""                 # 区服（同 region，兼容）
    remark: str = ""
    task_scope: list[str] = field(default_factory=lambda: ["daily", "permanent", "event", "special"])
    team_group: str = ""             # 组队分组标识
    teaming_enabled: bool = True     # 是否允许作为组队小号被调用
    cookies: dict[str, str] = field(default_factory=dict)


@dataclass
class AccountsConfig:
    """accounts.yaml 根结构"""
    accounts: list[AccountEntry] = field(default_factory=list)
    current: str = ""  # 当前选中的账号名


# ── 任务配置 ────────────────────────────────────────────────


@dataclass
class TaskActivityEntry:
    """活动日历条目"""
    activity_id: str = ""
    name: str = ""
    start_date: str = ""
    end_date: str = ""
    tasks: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class TaskEntry:
    """任务条目（tasks.yaml §5.1 设计书字段）"""
    id: str = ""
    name: str = ""
    display_name: str = ""
    category: str = "common"  # common | daily | event | permanent | special
    enabled: bool = True
    priority: int = 0
    max_retries: int = 3
    timeout: float = 300.0
    interval: float = 0.0  # 执行间隔（秒），0=不重复
    tags: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    # ── 设计书调度字段（§5.1，scheduler 读取） ──────────────
    repeat: dict | None = None          # {type, value, weekday(s), window(日历兼容), loop_count, monthly_day, trigger_templates}（含 on_enter 启动类型；expire_at 兼容旧配置）
    execution_mode: str = "daily"       # 执行模式：daily=按天执行一次 / per_slot=每时间段各执行一次
    max_daily: int | None = None        # 周期触发次数：活动周期内任务被触发的次数上限（达到→失效，None=不限）
    max_fail_streak: int = 10           # 连续失败熔断阈值
    active_range: list[str] | None = None  # ["2026-07-20", "2026-08-20"]
    time_start: str | None = None       # "08:00"（单时段；与 time_slots 互斥）
    time_end: str | None = None         # "23:00"（单时段；与 time_slots 互斥）
    time_slots: list[list[str]] | None = None  # 多时段 [["10:00","12:00"],["12:00","14:00"]]，2+ 时段时优先于 time_start/time_end
    team_id: str | None = None          # 阵容 ID
    floor: int | None = None            # 副本层数
    total_count: int | None = None      # 活动循环次数：循环体循环次数上限（每轮循环成功 +1，达到→失效，None=不限）
    loop_count: int | None = None       # 每轮循环次数（单人=打几场；组队=打几轮）
    images: dict | None = None          # 任务图片映射 {逻辑名: 素材路径}（§5.2 任务图片配置）
    # ── 战斗配置（UI「战斗配置」Tab 保存，scheduler→task_config 透传）──
    soul_setup: dict | None = None      # 御魂套装 {group, team, position:[分组序号,队伍序号]}
    lock_team: bool = False             # 战前准备：是否锁定队伍（选是则无法更换）
    change_team: bool = False           # 战前准备：是否更换队伍
    stamina_required: int | None = None # 体力门槛（uses_stamina=True 时，0=不检查）
    teaming: dict | None = None         # 组队配置 {sub_ids:[...]}（主号带队，轮数复用 loop_count）


@dataclass
class TasksConfig:
    """tasks.yaml 根结构"""
    tasks: list[TaskEntry] = field(default_factory=list)
    activities: list[TaskActivityEntry] = field(default_factory=list)


# ── 活动日历坐标 ────────────────────────────────────────────


@dataclass
class CoordEntry:
    """坐标点"""
    x: int = 0
    y: int = 0
    desc: str = ""


@dataclass
class CoordsConfig:
    """coords/*.json 根结构"""
    points: dict[str, CoordEntry] = field(default_factory=dict)
    screen_size: tuple[int, int] = (1080, 1920)


# ── 校验 ────────────────────────────────────────────────────


def validate_global_config(data: dict[str, Any]) -> GlobalConfig:
    """校验并构建 GlobalConfig"""
    errors: list[str] = []

    # ADB port
    adb_port = data.get("device", {}).get("adb", {}).get("port", 5037)
    if not isinstance(adb_port, int) or adb_port < 1 or adb_port > 65535:
        errors.append(f"device.adb.port 无效: {adb_port}")

    # OCR timeout
    ocr_to = data.get("image", {}).get("ocr_timeout", 10.0)
    if not isinstance(ocr_to, (int, float)) or ocr_to <= 0:
        errors.append(f"image.ocr_timeout 必须 > 0: {ocr_to}")

    # Interval
    min_interval = data.get("anti_detect", {}).get("min_interval", 1.0)
    max_interval = data.get("anti_detect", {}).get("max_interval", 5.0)
    if min_interval > max_interval:
        errors.append(f"anti_detect.min_interval({min_interval}) > max_interval({max_interval})")

    # Log level
    valid_levels = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
    log_level = data.get("log", {}).get("level", "INFO")
    if log_level.upper() not in valid_levels:
        errors.append(f"log.level 无效: {log_level}")

    # Crontab
    crontab = data.get("schedule", {}).get("crontab", "")
    if crontab and not re.match(r"^[\d*/, -]+$", crontab):
        errors.append(f"schedule.crontab 格式无效: {crontab}")

    if errors:
        raise ConfigValidationError("; ".join(errors))

    return _dict_to_dataclass(GlobalConfig, data)


def validate_accounts_config(data: dict[str, Any]) -> AccountsConfig:
    """校验并构建 AccountsConfig"""
    errors: list[str] = []
    accounts = data.get("accounts", [])
    if not isinstance(accounts, list):
        errors.append("accounts 必须为列表")
    else:
        # 兼容：account_id 唯一优先，缺失时回退 name 唯一
        ids = [a.get("account_id") or a.get("name", "") for a in accounts if isinstance(a, dict)]
        if len(ids) != len(set(ids)):
            errors.append("账号 ID 存在重复")

    if errors:
        raise ConfigValidationError("; ".join(errors))

    return _dict_to_dataclass(AccountsConfig, data)


def validate_tasks_config(data: dict[str, Any]) -> TasksConfig:
    """校验并构建 TasksConfig"""
    errors: list[str] = []
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        errors.append("tasks 必须为列表")
    else:
        ids = [t.get("id", "") for t in tasks]
        if len(ids) != len(set(ids)):
            errors.append("任务 ID 存在重复")

    if errors:
        raise ConfigValidationError("; ".join(errors))

    return _dict_to_dataclass(TasksConfig, data)


# ── 版本迁移 ────────────────────────────────────────────────
# 迁移函数表：MIGRATIONS[v] = func(old_config, old_tasks, old_accounts) -> new_config
# 从版本 v 迁移到 v+1
MIGRATIONS: dict[int, callable] = {}


# ── 工具 ────────────────────────────────────────────────────


def _dict_to_dataclass(cls: type, data: dict[str, Any]) -> Any:
    """将 dict 递归转换为 dataclass（简易实现，仅处理嵌套 dataclass）"""
    import dataclasses
    import typing

    if not dataclasses.is_dataclass(cls):
        return data

    # from __future__ import annotations 下字段类型是字符串，
    # 需用 get_type_hints 解析为真实类型才能递归转换嵌套 dataclass
    try:
        hints = typing.get_type_hints(cls)
    except Exception:
        hints = {}
    field_types: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        field_types[f.name] = hints.get(f.name, f.type)

    kwargs: dict[str, Any] = {}

    for f_name, f_type in field_types.items():
        if f_name not in data:
            # 使用默认值
            continue
        val = data[f_name]
        # 尝试递归转换
        if dataclasses.is_dataclass(f_type) and isinstance(val, dict):
            kwargs[f_name] = _dict_to_dataclass(f_type, val)
        elif (
            hasattr(f_type, "__origin__")
            and f_type.__origin__ is list
            and f_type.__args__
            and dataclasses.is_dataclass(f_type.__args__[0])
            and isinstance(val, list)
        ):
            kwargs[f_name] = [_dict_to_dataclass(f_type.__args__[0], item) for item in val]
        else:
            kwargs[f_name] = val

    return cls(**kwargs)
