"""
全局异常聚合定义

模块分区:
- 基础异常: YYSException
- 配置异常: ConfigError / ConfigValidationError
- 设备异常: DeviceError / ADBError / ConnectionError / EmulatorError / ScreenshotError
- 图像异常: ImageError / TemplateNotFound / OCRError
- 任务异常: TaskError / TaskSkip / TaskTimeout / TaskInterrupted
- 执行异常: ExecutorError / StepError
- 账号异常: AccountError / AccountLocked
- 状态异常: StateError / StateTransitionError
- 调度异常: SchedulerError
- 运行异常: RunError / StopSignal
- 防封异常: AntiDetectError
"""
from __future__ import annotations


# ── 基础异常 ────────────────────────────────────────────────
class YYSException(Exception):
    """所有自定义异常的基类"""


# ── 配置异常 ────────────────────────────────────────────────
class ConfigError(YYSException):
    """配置相关错误"""


class ConfigValidationError(ConfigError):
    """配置校验失败"""


class ConfigNotFoundError(ConfigError):
    """配置文件不存在"""


# ── 设备异常 ────────────────────────────────────────────────
class DeviceError(YYSException):
    """设备相关错误"""


class ADBError(DeviceError):
    """ADB 命令执行失败"""


class ConnectionError(DeviceError):
    """设备连接失败"""


class EmulatorError(DeviceError):
    """模拟器操作错误"""


class ScreenshotError(DeviceError):
    """截屏失败"""


class HeartbeatError(DeviceError):
    """心跳检测失败"""


class DeviceNotFoundError(DeviceError):
    """未找到设备"""


# ── 图像异常 ────────────────────────────────────────────────
class ImageError(YYSException):
    """图像相关错误"""


class TemplateNotFoundError(ImageError):
    """模板图片未找到"""


class OCRTimeoutError(ImageError):
    """OCR 识别超时"""


class MatchNotFoundError(ImageError):
    """未找到匹配结果"""


# ── 任务异常 ────────────────────────────────────────────────
class TaskError(YYSException):
    """任务执行错误"""


class TaskSkip(TaskError):
    """任务跳过（非错误，用于控制流）"""


class TaskTimeout(TaskError):
    """任务执行超时"""


class TaskInterrupted(TaskError):
    """任务被中断"""


class TaskNotFoundError(TaskError):
    """任务未找到"""


class TaskValidationError(TaskError):
    """任务配置校验失败"""


# ── 执行异常 ────────────────────────────────────────────────
class ExecutorError(YYSException):
    """执行器错误"""


class StepError(ExecutorError):
    """步骤执行失败"""


class StepTimeoutError(StepError):
    """步骤执行超时"""


# ── 账号异常 ────────────────────────────────────────────────
class AccountError(YYSException):
    """账号相关错误"""


class AccountLockedError(AccountError):
    """账号被锁定"""


class AccountLoginError(AccountError):
    """登录失败"""


class AccountCookieExpiredError(AccountError):
    """Cookie 过期"""


# ── 状态异常 ────────────────────────────────────────────────
class StateError(YYSException):
    """状态管理错误"""


class StateTransitionError(StateError):
    """状态转换非法"""


class StateKeyNotFoundError(StateError):
    """状态键不存在"""


# ── 调度异常 ────────────────────────────────────────────────
class SchedulerError(YYSException):
    """调度器错误"""


# ── 运行异常 ────────────────────────────────────────────────
class RunError(YYSException):
    """运行控制错误"""


class StopSignal(RunError):
    """停止信号（用于控制流）"""


# ── 防封异常 ────────────────────────────────────────────────
class AntiDetectError(YYSException):
    """防封策略错误"""


class RateLimitError(AntiDetectError):
    """操作频率超限"""


class RunLimitExceeded(AntiDetectError):
    """运行时长/操作次数达上限"""


class HumanCheckDetectedError(AntiDetectError):
    """检测到人工验证"""


class ProfileNotFoundError(AntiDetectError):
    """行为档案不存在"""


# ── 设备补充异常 ────────────────────────────────────────────
class DeviceConfigError(DeviceError):
    """设备配置错误"""


class DeviceOfflineError(DeviceError):
    """设备离线"""


class DeviceTimeoutError(DeviceError):
    """设备操作超时"""


class DeviceReconnectingError(DeviceError):
    """设备正在重连"""


class DevicePermissionError(DeviceError):
    """设备权限不足"""


class DeviceScreenshotError(DeviceError):
    """截图失败"""


# ── 调度异常 ────────────────────────────────────────────────
class ScheduleError(YYSException):
    """调度错误"""


class ScheduleOverrunError(ScheduleError):
    """调度超时"""


class ScheduleConfigError(ScheduleError):
    """调度配置错误"""


# ── 场景异常 ────────────────────────────────────────────────
class SceneUnknownError(YYSException):
    """未知场景"""


class SceneTimeoutError(YYSException):
    """场景等待超时"""


# ── 素材异常 ────────────────────────────────────────────────
class AssetNotFoundError(ImageError):
    """素材文件未找到"""


class AssetMissingError(ImageError):
    """素材缺失（由 find_missing_assets 检测）"""


class AssetCorruptedError(ImageError):
    """素材文件损坏"""


# ── 识别异常 ────────────────────────────────────────────────
class RecognitionError(ImageError):
    """识别错误的基类"""


class RecognitionTimeoutError(RecognitionError):
    """识别超时"""


class OCRNotAvailableError(RecognitionError):
    """OCR 引擎不可用"""


# ── 桥接异常 ────────────────────────────────────────────────
class BridgeError(YYSException):
    """参数桥接错误"""


class BindingError(BridgeError):
    """UI 绑定错误"""


class UndoError(BridgeError):
    """撤销操作错误"""


# ── 引导异常 ────────────────────────────────────────────────
class BootstrapError(YYSException):
    """应用启动错误"""


class SelfCheckError(BootstrapError):
    """启动自检失败"""


class InitError(BootstrapError):
    """模块初始化失败"""


# ── 识别模式枚举（用于 Recognizer） ──────────────────────────
from enum import Enum


class MatchMode(str, Enum):
    """识别模式"""
    TEMPLATE_ONLY = "template_only"
    OCR_ONLY = "ocr_only"
    AUTO = "auto"  # 先模板，模板未匹配则 OCR
    SMART = "smart"  # 根据素材元数据自动选择

