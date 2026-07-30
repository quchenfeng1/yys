"""
12-日志监控中心

底层日志引擎（基于 loguru）。
提供:
- 统一的日志配置（控制台+文件+结构化）
- 日志级别动态调整
- 上下文绑定（账号/任务/设备）
- 日志轮转和压缩
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from loguru import logger as _loguru_logger


class LoggerEngine:
    """日志引擎封装"""

    _initialized = False
    _log_dir: Path | None = None

    def __init__(self) -> None:
        self._logger = _loguru_logger

    def configure(
        self,
        log_dir: str | Path = "logs",
        level: str = "DEBUG",
        rotation: str = "10 MB",
        retention: str = "30 days",
        compression: str = "gz",
        console: bool = True,
        structured: bool = False,
    ) -> None:
        """
        配置日志引擎。

        Args:
            log_dir: 日志文件目录
            level: 日志级别 TRACE / DEBUG / INFO / SUCCESS / WARNING / ERROR / CRITICAL
            rotation: 轮转大小（如 "10 MB"）或时间（如 "1 day"）
            retention: 保留时间
            compression: 压缩格式（如 "gz", "zip"）
            console: 是否输出到控制台
            structured: 是否启用结构化 JSON 日志
        """
        if self._initialized:
            self._logger.warning("Logger already configured, reconfiguring...")
            self._logger.remove()

        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        self._log_dir = log_path

        # 格式化
        fmt_console = (
            "<green>{time:MM-DD HH:mm:ss}</green> "
            "|<level>{level:^8}</level>|"
            "{extra[scope]:^12}|"
            "<level>{message}</level>"
        )
        fmt_file = (
            "{time:YYYY-MM-DD HH:mm:ss.SSS} "
            "|{level:^8}|"
            "{extra[scope]:^12}|"
            "{name}:{line}|"
            "{message}"
        )

        # 控制台
        if console:
            self._logger.add(
                sys.stderr,
                level=level,
                format=fmt_console,
                colorize=True,
                backtrace=True,
                diagnose=True,
            )

        # 运行时日志
        self._logger.add(
            str(log_path / "runtime.log"),
            level=level,
            format=fmt_file,
            rotation=rotation,
            retention=retention,
            compression=compression,
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )

        # 错误日志（单独）
        self._logger.add(
            str(log_path / "error.log"),
            level="ERROR",
            format=fmt_file,
            rotation=rotation,
            retention=retention,
            compression=compression,
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )

        # 结构化 JSON 日志
        if structured:
            self._logger.add(
                str(log_path / "structured.jsonl"),
                level=level,
                format=lambda r: self._json_format(r),
                rotation=rotation,
                retention=retention,
                compression=compression,
                enqueue=True,
            )

        # 崩溃日志（最高级别，不轮转）
        self._logger.add(
            str(log_path / "crash.log"),
            level="CRITICAL",
            format=fmt_file,
            rotation=None,
            retention=retention,
            enqueue=True,
        )

        self._initialized = True
        self._logger.info("Logger initialized: level=%s, dir=%s", level, log_path)

    @staticmethod
    def _json_format(record: dict) -> str:
        """结构化 JSON 格式"""
        import json
        from datetime import datetime

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": record["level"].name,
            "scope": record["extra"].get("scope", "root"),
            "message": record["message"],
            "module": record["name"],
            "line": record["line"],
        }
        if record.get("exception"):
            log_entry["exception"] = str(record["exception"])
        return json.dumps(log_entry, ensure_ascii=False)

    def bind(self, **kwargs: Any) -> _loguru_logger.__class__:  # type: ignore
        """返回绑定了上下文的 logger。

        用法:
            logger.bind(scope="task", task_id="123").info("start")
        """
        return self._logger.bind(**kwargs)

    @property
    def logger(self) -> _loguru_logger.__class__:  # type: ignore
        return self._logger

    def __getattr__(self, name: str) -> Any:
        return getattr(self._logger, name)


# 全局单例
engine = LoggerEngine()
logger = engine.logger


__all__ = [
    "LoggerEngine",
    "engine",
    "logger",
]

