"""
配置 Schema 定义与校验（06-配置模块 子模块）

定义各配置字段的类型、范围、必填等信息，启动时校验。
"""

from typing import Any


class ConfigSchema:
    """配置校验器。"""

    # 字段定义：{ key_path: { type, required, min, max, enum } }
    SCHEMA = {
        "global.adb.port": {"type": int, "required": True, "min": 1024, "max": 65535},
        "global.adb.device_id": {"type": str, "required": False},
        "global.screen.width": {"type": int, "required": False, "min": 640},
        "global.screen.height": {"type": int, "required": False, "min": 360},
        "global.recognize.threshold": {"type": float, "min": 0.1, "max": 1.0},
        "global.anti_detect.click_offset_radius": {"type": int, "min": 0, "max": 100},
        "global.anti_detect.max_daily_runtime": {"type": int, "min": 1, "max": 24},
        "global.anti_detect.max_daily_actions": {"type": int, "min": 1, "max": 100000},
        "global.run.log_level": {"type": str, "enum": ["DEBUG", "INFO", "WARNING", "ERROR"]},
    }

    @classmethod
    def validate(cls, config_getter) -> list[str]:
        """校验所有配置，返回错误信息列表。"""
        errors = []

        for key_path, schema in cls.SCHEMA.items():
            value = config_getter(key_path)
            if value is None:
                if schema.get("required"):
                    errors.append(f"[必填缺失] {key_path}")
                continue

            etype = schema["type"]
            if not isinstance(value, etype):
                errors.append(f"[类型错误] {key_path}: 期望 {etype.__name__}, 实际 {type(value).__name__}")

            if etype in (int, float):
                if "min" in schema and value < schema["min"]:
                    errors.append(f"[超下限] {key_path}: {value} < {schema['min']}")
                if "max" in schema and value > schema["max"]:
                    errors.append(f"[超上限] {key_path}: {value} > {schema['max']}")

            if "enum" in schema and value not in schema["enum"]:
                errors.append(f"[枚举错误] {key_path}: {value} 不在 {schema['enum']}")

        return errors
