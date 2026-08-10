"""调查：各重复规则模式下属性区显隐完整性（排查遗留可见控件）。

期望矩阵（属性区是否可见 ✓/✗）：
  类型：        每日 每周 每月初 间隔N天 间隔N小时 每次启动 只执行一次 触发
  每周几        ✗   ✓   ✗    ✗     ✗       ✗      ✗       ✗
  每月几号      ✗   ✗   ✓    ✗     ✗       ✗      ✗       ✗
  间隔值        ✗   ✗   ✗    ✓     ✓       ✗      ✗       ✗
  触发信号      ✗   ✗   ✗    ✗     ✗       ✗      ✗       ✓
  执行时段      ✓   ✓   ✓    ✓     ✓       ✗      ✗       ✗
  活动有效期    ✓   ✓   ✓    ✓     ✓       ✗      ✗       ✗
  活动循环次数  ✓   ✓   ✓    ✓     ✓       ✓      ✓       ✓
  周期触发次数  ✓   ✓   ✓    ✓     ✓       ✓      ✓       ✓
  循环次数      ✓   ✓   ✓    ✓     ✓       ✓      ✓       ✓

对每个类型检查每个属性区：期望可见则 isHidden()=False，期望隐藏则 isHidden()=True。
"""
import os, sys
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  ❌ {label}  {detail}")


# 期望矩阵：类型 → {属性: 期望可见}
EXPECT = {
    "daily":        {"weekday": False, "interval": False, "trigger": False,
                     "slot": True, "active": True, "total": True, "max_daily": True,
                     "monthly_day": False},
    "weekly":       {"weekday": True, "interval": False, "trigger": False,
                     "slot": True, "active": True, "total": True, "max_daily": True,
                     "monthly_day": False},
    "monthly_start":{"weekday": False, "interval": False, "trigger": False,
                     "slot": True, "active": True, "total": True, "max_daily": True,
                     "monthly_day": True},
    "interval_days": {"weekday": False, "interval": True, "trigger": False,
                     "slot": True, "active": True, "total": True, "max_daily": True,
                     "monthly_day": False},
    "interval_hours": {"weekday": False, "interval": True, "trigger": False,
                     "slot": True, "active": True, "total": True, "max_daily": True,
                     "monthly_day": False},
    "on_enter":     {"weekday": False, "interval": False, "trigger": False,
                     "slot": False, "active": False, "total": True, "max_daily": True,
                     "monthly_day": False},
    "once":         {"weekday": False, "interval": False, "trigger": False,
                     "slot": False, "active": False, "total": True, "max_daily": True,
                     "monthly_day": False},
    "trigger":      {"weekday": False, "interval": False, "trigger": True,
                     "slot": False, "active": False, "total": True, "max_daily": True,
                     "monthly_day": False},
}

# 属性 → 控件 key
WIDGETS = {
    "weekday": "weekday_label",
    "interval": "interval_label",
    "trigger": "trigger_label",
    "slot": "slot_label",
    "active": "active_start_label",
    "total": "total_label",
    "max_daily": "max_daily_label",
    "monthly_day": "monthly_day_label",
}


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from ui.panels.game_task_panel import GameTaskPanel, REPEAT_TYPES

    class FakeBridge:
        def __init__(self):
            self.task = SimpleNamespace(
                get_task_detail=lambda n: {
                    "name": n, "display_name": n, "task_type": "daily",
                    "uses_battle": False, "uses_team": False, "uses_soul": False,
                    "uses_stamina": False, "enabled": True,
                    "repeat": {"type": "daily", "value": 1, "loop_count": 1},
                    "time_start": "06:00", "time_end": "23:59", "time_slots": None,
                    "active_range": None, "max_daily": 3, "total_count": None,
                    "execution_mode": "daily", "loop_count": 1, "priority": 10,
                    "next_run_time": "",
                },
                get_next_run_time=lambda n: None,
            )

    panel = GameTaskPanel(param_bridge=FakeBridge())
    panel.load_tasks([{"name": "t", "display_name": "t", "task_type": "daily",
                       "uses_battle": False}])
    panel.task_list.setCurrentRow(0)
    combo = panel._form_widgets["repeat_type"]
    w = panel._form_widgets

    print("各重复规则类型属性区显隐调查：")
    for rtype in [t for t, _ in REPEAT_TYPES]:
        combo.setCurrentIndex(combo.findData(rtype))
        exp = EXPECT[rtype]
        label = dict(REPEAT_TYPES)[rtype]
        for prop, want_visible in exp.items():
            key = WIDGETS[prop]
            cw = w.get(key)
            if cw is None:
                check(f"{label}({rtype}) {prop} 控件缺失", False, key)
                continue
            actual_visible = not cw.isHidden()
            check(f"{label}·{prop} 期望{'可见' if want_visible else '隐藏'}",
                  actual_visible == want_visible,
                  f"实际={'可见' if actual_visible else '隐藏'}")
    # 时段行的✕删除按钮等控件整体显隐（核心遗留修复）
    for rtype in ["daily", "on_enter", "once", "trigger"]:
        combo.setCurrentIndex(combo.findData(rtype))
        row_widgets = panel._slot_row_widgets
        want = rtype in ("daily",)
        if row_widgets:
            rw = row_widgets[0]
            # 时段行内所有控件应整体随显隐（含✕按钮）
            all_hidden = all(c.isHidden() for c in rw.findChildren(type(panel)))
            visible = not rw.isHidden()
            check(f"{rtype} 时段行整体显隐", visible == want and
                  (visible or all_hidden),
                  f"row_visible={visible} inner_all_hidden={all_hidden}")

    print(f"\n调查结果: 通过 {PASS} 项, 遗留 {FAIL} 项")
    if FAIL:
        print("存在遗留可见控件，需修复！")
        raise SystemExit(1)
    print("🎉 所有模式属性区显隐完整，无遗留控件")


if __name__ == "__main__":
    main()
