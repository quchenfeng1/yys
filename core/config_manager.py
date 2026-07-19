"""
配置管理模块

职责：统一加载与管理 YAML/JSON 配置，支持热重载。
- global.yaml: 全局配置（模拟器端口、分辨率、运行策略）
- tasks.yaml: 任务编排配置
- config/coords/*.json: 各场景坐标配置
"""

import os
import json
from pathlib import Path
from typing import Any

import yaml

from core.logger import get_logger
from core.exceptions import ConfigError

logger = get_logger("core.config")

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
COORDS_DIR = CONFIG_DIR / "coords"


class ConfigManager:
    """配置管理器，统一加载和管理所有配置文件"""

    _instance = None

    def __new__(cls):
        """单例模式，全局共享一份配置"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._global_config = {}
        self._tasks_config = {}
        self._coords_cache = {}
        self.load()

    def load(self):
        """加载所有配置文件"""
        # 全局配置
        global_path = CONFIG_DIR / "global.yaml"
        if global_path.exists():
            with open(global_path, "r", encoding="utf-8") as f:
                self._global_config = yaml.safe_load(f) or {}
            logger.info(f"已加载全局配置: {global_path}")
        else:
            logger.warning(f"全局配置文件不存在: {global_path}")
            self._global_config = {}

        # 任务配置
        tasks_path = CONFIG_DIR / "tasks.yaml"
        if tasks_path.exists():
            with open(tasks_path, "r", encoding="utf-8") as f:
                self._tasks_config = yaml.safe_load(f) or {}
            logger.info(f"已加载任务配置: {tasks_path}")
        else:
            self._tasks_config = {}

        # 清空坐标缓存
        self._coords_cache = {}

    def reload(self):
        """重新加载所有配置（热重载）"""
        logger.info("重新加载配置...")
        self.load()

    # ===== 全局配置 =====

    def get(self, key_path: str, default: Any = None) -> Any:
        """通过点分路径获取全局配置值

        Args:
            key_path: 配置路径，如 "adb.port"、"screen.width"
            default: 默认值

        Returns:
            配置值，不存在则返回 default
        """
        keys = key_path.split(".")
        value = self._global_config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path: str, value: Any):
        """设置全局配置值（仅内存，不自动写盘）"""
        keys = key_path.split(".")
        config = self._global_config
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        config[keys[-1]] = value

    def save_global(self):
        """将全局配置写回 global.yaml"""
        global_path = CONFIG_DIR / "global.yaml"
        with open(global_path, "w", encoding="utf-8") as f:
            yaml.dump(self._global_config, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"全局配置已保存: {global_path}")

    # ===== 坐标配置 =====

    def get_coords(self, scene: str) -> dict:
        """读取场景坐标配置 config/coords/{scene}.json

        Args:
            scene: 场景名，如 "login"、"courtyard"、"yuhun"

        Returns:
            配置字典，文件不存在则返回空字典
        """
        if scene in self._coords_cache:
            return self._coords_cache[scene]

        coords_path = COORDS_DIR / f"{scene}.json"
        if coords_path.exists():
            with open(coords_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self._coords_cache[scene] = config
            logger.debug(f"已加载坐标配置: {scene}")
            return config
        else:
            logger.warning(f"坐标配置文件不存在: {coords_path}")
            return {}

    # ===== 任务配置 =====

    def get_tasks_config(self) -> dict:
        """获取任务编排配置"""
        return self._tasks_config

    def get_task_config(self, task_name: str) -> dict:
        """获取指定任务的配置（从 tasks.yaml 中查找）

        Args:
            task_name: 任务名

        Returns:
            任务配置字典，包含 name/enabled/priority/repeat 等
        """
        for category in ["daily", "permanent", "special", "event"]:
            tasks = self._tasks_config.get(category, [])
            for task in tasks:
                if task.get("name") == task_name:
                    return task
        return {}

    @property
    def global_config(self) -> dict:
        """获取完整全局配置"""
        return self._global_config
