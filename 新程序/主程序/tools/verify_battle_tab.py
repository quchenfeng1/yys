"""UI 双 Tab 战斗配置专项验证（临时）"""
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
        "repeat": {"type": "daily", "value": 1, "loop_count": 5},
        "loop_count": 5, "floor": 10, "team_id": "阵容1", "max_fail_streak": 10,
        "stamina_required": 100, "priority": 10, "enabled": False,
        "time_start": "06:00", "time_end": "23:59",
        "soul_setup": {"group": "御魂副本", "team": "御魂十层", "position": [4, 1]},
        "lock_team": True, "change_team": True,
    }
    panel._render_form(detail)

    w = panel._form_widgets
    # ① 双 Tab 战斗配置控件存在
    for key in ("soul_group", "soul_team", "soul_pos_group", "soul_pos_team",
                "lock_team", "change_team", "team_id", "floor", "max_fail_streak"):
        assert key in w, f"缺少控件 {key}"
    # ② 读取回填正确
    assert w["soul_group"].text() == "御魂副本", w["soul_group"].text()
    assert w["soul_team"].text() == "御魂十层", w["soul_team"].text()
    assert w["soul_pos_group"].value() == 4, w["soul_pos_group"].value()
    assert w["soul_pos_team"].value() == 1, w["soul_pos_team"].value()
    assert w["lock_team"].isChecked() is True
    assert w["change_team"].isChecked() is True
    print("① PASS 双 Tab 战斗配置控件创建并回填正确")

    # ③ _collect_config 收集战斗字段
    config = panel._collect_config()
    assert config["soul_setup"] == {"group": "御魂副本", "team": "御魂十层", "position": [4, 1]}, config["soul_setup"]
    assert config["lock_team"] is True, config
    assert config["change_team"] is True, config
    assert config["floor"] == 10, config
    assert config["stamina_required"] == 100, config
    print("② PASS _collect_config 正确收集 soul_setup/lock_team/change_team")

    # ④ 非战斗任务（daily_test）不应有战斗 tab 控件
    panel._render_form({
        "name": "daily_test", "display_name": "日常测试", "task_type": "event_task",
        "uses_battle": False, "repeat": {"type": "daily"}, "priority": 10,
        "enabled": True, "time_start": "06:00", "time_end": "23:59",
    })
    assert "soul_group" not in panel._form_widgets
    print("③ PASS 非战斗任务不创建战斗配置控件")

    print("\n🎉 UI 双 Tab 战斗配置验证 3/3 通过")


if __name__ == "__main__":
    main()
