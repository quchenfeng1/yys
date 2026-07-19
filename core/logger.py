"""
日志模块

职责：结构化记录运行日志，支持分级、文件轮转、控制台输出。
- 分级：DEBUG / INFO / WARNING / ERROR / CRITICAL
- 格式：[时间] [级别] [模块] 消息
- 文件：按天轮转，存放 logs/YYYY-MM-DD.log
- 控制台与文件双输出
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from loguru import logger as _logger

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


def setup_logger(level: str = "INFO"):
    """初始化日志配置

    Args:
        level: 日志级别 DEBUG/INFO/WARNING/ERROR
    """
    LOG_DIR.mkdir(exist_ok=True)

    # 移除默认处理器
    _logger.remove()

    # 日志格式
    fmt = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} | {message}"

    # 控制台输出（彩色）
    # 注意：pythonw.exe（无控制台）模式下 sys.stderr 为 None，需跳过
    if sys.stderr is not None:
        _logger.add(
            sys.stderr,
            format=fmt,
            level=level,
            colorize=True,
        )

    # 文件输出（按天轮转）
    log_file = LOG_DIR / "{time:YYYY-MM-DD}.log"
    _logger.add(
        str(log_file),
        format=fmt,
        level=level,
        rotation="00:00",       # 每天 00:00 轮转
        retention="7 days",     # 保留 7 天
        encoding="utf-8",
    )

    _logger.info(f"日志系统已初始化，级别={level}，日志目录={LOG_DIR}")


def get_logger(name: str = "onmyoji"):
    """获取指定名称的 logger

    Args:
        name: 模块名，如 "device.adb"、"core.recognizer"

    Returns:
        loguru logger 实例（已绑定 name）
    """
    return _logger.bind(name=name)


# 模块导入时自动初始化（默认 INFO 级别）
setup_logger()
