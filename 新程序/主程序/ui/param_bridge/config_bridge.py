"""
10-参数桥接模块

通用配置传参（§5.3 ConfigBridge）。
桥接 ConfigManager 与 UI/任务。
"""
from __future__ import annotations

from typing import Any


class ConfigBridge:
    """配置参数桥接（§5.3）"""

    def __init__(self, config_mgr: Any = None):
        self._mgr = config_mgr

    # ── §5.3 方法 ────────────────────────────────────────

    def get(self, key_path: str, default: Any = None) -> Any:
        """读取任意配置值（§5.3）"""
        if not self._mgr:
            return default
        return self._mgr.get(key_path, default)

    def set(self, key_path: str, value: Any) -> None:
        """写入配置值并持久化（§5.3）"""
        if not self._mgr:
            return
        self._mgr.set(key_path, value, source="ConfigBridge")

    def export_config(self, target_path: str, overwrite: bool = False) -> None:
        """导出配置备份（§5.3）"""
        if not self._mgr:
            return
        self._mgr.export_config(target_path)

    def import_config(self, source_path: str, mode: str = "overwrite") -> None:
        """从备份恢复配置（§5.3）"""
        if not self._mgr:
            return
        self._mgr.import_config(source_path, mode)

    # ── 兼容旧方法 ───────────────────────────────────────

    def get_global_params(self) -> dict[str, Any]:
        if not self._mgr:
            return {}
        try:
            g = self._mgr.global_config
            return {
                "adb_host": g.device.adb.host,
                "adb_port": g.device.adb.port,
                "template_threshold": g.image.template_threshold,
                "min_interval": g.anti_detect.min_interval,
                "max_interval": g.anti_detect.max_interval,
                "log_level": g.log.level,
            }
        except Exception:
            return {}

    def reload_config(self) -> None:
        if self._mgr:
            self._mgr.reload()

    def get_config_file_paths(self) -> dict[str, str]:
        if not self._mgr:
            return {}
        return {
            "global": str(self._mgr.config_dir / "global.yaml"),
            "accounts": str(self._mgr.config_dir / "accounts.yaml"),
            "tasks": str(self._mgr.config_dir / "tasks.yaml"),
        }
