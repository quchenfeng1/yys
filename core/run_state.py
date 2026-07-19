"""
运行状态枚举（09-运行控制模块 子模块）
"""

from enum import Enum


class RunState(Enum):
    """程序运行生命周期状态。"""
    STOPPED = "stopped"      # 未运行
    RUNNING = "running"      # 运行中
    PAUSED = "paused"        # 已暂停
    STOPPING = "stopping"    # 优雅停止中（等当前步骤完成）
    ERROR = "error"          # 异常状态
