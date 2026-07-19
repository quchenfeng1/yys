"""
配置数据模型层（10-传参模块 子模块）

定义每个任务/模块需要的参数 schema。
"""

from typing import Any


class TaskParamSchema:
    """任务参数模型。"""

    @staticmethod
    def get_schema(task_name: str, category: str = "") -> dict:
        """返回任务的参数 schema。"""
        base = {
            "enabled": {"type": "bool", "label": "启用", "default": False},
            "priority": {"type": "int", "label": "优先级", "default": 10, "min": 1, "max": 99},
            "repeat": {"type": "repeat_rule", "label": "执行规则", "default": None},
            "next_run_time": {"type": "datetime", "label": "下次执行时间", "readonly": False},
        }

        if category == "permanent":  # 常驻副本 = 战斗任务类型需阵容
            base.update({
                "times": {"type": "int", "label": "挑战次数", "default": 30, "min": 1},
                "team_id": {"type": "team_select", "label": "阵容预设", "default": ""},
                "lock_team_after_select": {"type": "bool", "label": "选阵容后锁定", "default": True},
                "max_daily": {"type": "int", "label": "每日上限", "default": 100},
            })

        if category == "event":
            base.update({
                "valid_from": {"type": "date", "label": "生效日期", "default": ""},
                "valid_until": {"type": "date", "label": "失效日期", "default": ""},
            })

        return base

    @staticmethod
    def validate(value: Any, schema: dict) -> list[str]:
        """校验参数值是否符合 schema。"""
        errors = []
        stype = schema.get("type")
        if stype == "int":
            if not isinstance(value, int):
                errors.append(f"应为整数，实际为 {type(value).__name__}")
            elif "min" in schema and value < schema["min"]:
                errors.append(f"最小值为 {schema['min']}")
            elif "max" in schema and value > schema["max"]:
                errors.append(f"最大值为 {schema['max']}")
        elif stype == "bool":
            if not isinstance(value, bool):
                errors.append(f"应为布尔值")
        return errors
