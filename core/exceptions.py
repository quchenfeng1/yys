"""
自定义异常模块

所有脚本异常继承自 ScriptError，便于上层统一捕获和处理。
"""


class ScriptError(Exception):
    """脚本基础异常"""
    pass


class DeviceConnectError(ScriptError):
    """设备连接失败"""
    pass


class RecognizeError(ScriptError):
    """识别失败"""
    pass


class SceneNotFoundError(RecognizeError):
    """场景未找到"""
    pass


class LoginFailedError(ScriptError):
    """登录流程失败"""
    pass


class AntiBanRiskError(ScriptError):
    """触发防封风险限制"""
    pass


class ConfigError(ScriptError):
    """配置错误"""
    pass


class TeamNotFoundError(ScriptError):
    """阵容预设未找到"""
    pass


class MitamaNotMatchError(ScriptError):
    """御魂套装/属性不匹配"""
    pass


class TeamLockFailedError(ScriptError):
    """锁定阵容失败"""
    pass
