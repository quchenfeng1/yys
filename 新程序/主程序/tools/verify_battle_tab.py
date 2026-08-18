"""验证：战斗配置 UI 已取消（2026-08-16，业务参数由变量组/常量组承载）。

验证点：
  1. uses_battle=True 任务：不再渲染任何战斗配置控件
  2. _collect_config 不再收集战斗字段（soul_setup/lock_team/team_id/floor 等）
  3. 非战斗任务行为不变
  4. 可视化任务：多出「变量配置」「常量展示」两个 Tab
"""
import os, sys
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from PyQt5.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)
    from ui.panels.game_task_panel import GameTaskPanel

    panel = GameTaskPanel()
    detail = {
        "name": "combat_test", "display_name": "战斗测试", "task_type": "battle",
        "uses_battle": True, "uses_team": True, "uses_stamina": True,
        "repeat": {"type": "daily", "value": 1},
        "floor": 10, "team_id": "阵容1", "max_fail_streak": 10,
        "stamina_required": 100, "priority": 10, "enabled": False,
        "time_start": "06:00", "time_end": "23:59",
        "soul_setup": {"group": "御魂副本", "team": "御魂十层", "position": [4, 1]},
        "lock_team": True, "change_team": True,
    }
    panel._render_form(detail)

    w = panel._form_widgets
    # ① 战斗配置控件全部移除
    for key in ("soul_group", "soul_team", "soul_pos_group", "soul_pos_team",
                "lock_team", "change_team", "team_id", "floor",
                "max_fail_streak", "stamina_required", "teaming_sub_ids"):
        assert key not in w, f"战斗控件 {key} 应已移除"
    # ② 调度控件仍在（执行配置 = 时间调度 + 其他）；
    #    活动循环次数 total_count 已移除（2026-08-16：图内可调用变量取代）
    for key in ("repeat_type", "max_daily", "priority",
                "next_run_time"):
        assert key in w, f"执行配置控件 {key} 缺失"
    assert "total_count" not in w, "total_count 控件应已移除（图内变量取代）"
    print("① PASS uses_battle=True 不再渲染战斗配置控件")

    # ③ _collect_config 不再收集战斗字段
    config = panel._collect_config()
    for key in ("soul_setup", "lock_team", "change_team", "team_id", "floor",
                "stamina_required", "teaming", "loop_count"):
        assert key not in config, f"config 不应含 {key}: {config}"
    assert config.get("repeat", {}).get("type") == "daily"
    assert "loop_count" not in config.get("repeat", {}), config
    print("② PASS _collect_config 不再收集战斗/循环次数字段")

    # ④ 非战斗任务行为不变
    panel._render_form({
        "name": "daily_test", "display_name": "日常测试", "task_type": "event_task",
        "uses_battle": False, "repeat": {"type": "daily"}, "priority": 10,
        "enabled": True, "time_start": "06:00", "time_end": "23:59",
    })
    assert "soul_group" not in panel._form_widgets
    assert "repeat_type" in panel._form_widgets
    print("③ PASS 非战斗任务行为不变")

    # ⑤ 可视化任务：多出变量配置/常量展示两个 Tab
    panel._visual_bridge = type("VB", (), {
        "get_task": lambda self, n: {
            "name": n, "display_name": n,
            "graph": {"nodes": [
                {"type": "variable_group", "params": {
                    "group_name": "循环参数",
                    "variables": [{"key": "loop_count", "label": "循环次数",
                                   "type": "int", "value": 3}]}},
                {"type": "constant_group", "params": {
                    "group_name": "固定配置",
                    "variables": [{"key": "team_id", "label": "阵容",
                                   "type": "text", "value": "阵容1"}]}},
            ]},
            "param_values": {"loop_count": 5},
        }})()
    panel._render_form({
        "name": "visual_daily", "display_name": "可视化日常",
        "task_type": "visual_task", "is_visual": True,
        "repeat": {"type": "daily", "value": 1},
        "priority": 10, "enabled": True,
    })
    # 变量配置 tab 有输入控件且初值 = param_values(5)
    assert "loop_count" in panel._var_inputs, list(panel._var_inputs)
    assert panel._var_inputs["loop_count"].value() == 5
    # 常量只读展示（不进入输入集合）
    assert "team_id" not in panel._var_inputs
    assert panel._collect_var_inputs() == {"loop_count": 5}
    print("④ PASS 可视化任务：变量配置 Tab 按组名分组 + 初值 param_values + 常量只读")

    print("\n🎉 战斗配置取消 + 变量/常量 Tab 验证 4/4 通过")


if __name__ == "__main__":
    main()
