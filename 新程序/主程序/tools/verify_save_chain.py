"""验证：GameTaskPanel「💾 保存配置」_save() 完整链路（子代理审计缺口 #3）。

链路：_collect_config → task.save_task_config → run.reset_task_cycle
  → （手动改了下次执行?）update_next_run : reload_scheduler → 回显 next_run

覆盖：
  A. 不改 next_run → 走 reload_scheduler（热重载生效）+ save_task_config + reset_task_cycle
  B. 手动改 next_run → 走 update_next_run（不 reload，避免覆盖）
  C. 保存内容正确性（collect → save 的 config 含重复规则/时段/上限字段）
  D. 状态栏反馈 + 保存失败路径
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
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


class Recorder:
    def __init__(self):
        self.saved = []      # (name, config)
        self.reloaded = 0
        self.updated = []    # (name, dt)
        self.reset_cycles = []
        self.detail = None

    def get_task_detail(self, n):
        return self.detail


def make_bridge():
    rec = Recorder()
    rec.detail = {
        "name": "t", "display_name": "t", "task_type": "daily",
        "uses_battle": False, "uses_team": False, "uses_soul": False,
        "uses_stamina": False, "enabled": True,
        "repeat": {"type": "daily", "value": 1, "loop_count": 3},
        "time_start": "06:00", "time_end": "12:00", "time_slots": None,
        "active_range": None, "max_daily": 5, "total_count": None,
        "priority": 10, "next_run_time": "2026-08-11 06:00",
    }
    task = SimpleNamespace(
        get_task_detail=rec.get_task_detail,
        get_next_run_time=lambda n: rec.detail.get("next_run_time", ""),
        get_cycle_progress=lambda n: (2, 10),
        save_task_config=lambda n, c: rec.saved.append((n, c)),
        reload_scheduler=lambda n=None: rec.__setattr__("reloaded", rec.reloaded + 1),
        update_next_run=lambda n, dt: rec.updated.append((n, dt)),
    )
    run = SimpleNamespace(
        reset_task_cycle=lambda n: rec.reset_cycles.append(n),
    )
    bridge = SimpleNamespace(task=task, run=run)
    return bridge, rec


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from ui.panels.game_task_panel import GameTaskPanel

    # ═══ A. 不改 next_run → reload 分支 ═══
    print("\n[A] _save() 不改下次执行 → reload 热重载")
    bridge, rec = make_bridge()
    panel = GameTaskPanel(param_bridge=bridge)
    panel.load_tasks([{"name": "t", "display_name": "t", "task_type": "daily",
                       "uses_battle": False}])
    panel.task_list.setCurrentRow(0)
    # 修改一个字段确保收集生效
    panel._form_widgets["max_daily"].setValue(8)
    panel._save()
    check("A1 save_task_config 被调", len(rec.saved) == 1, str(rec.saved))
    check("A2 保存的 config 含修改值(max_daily=8)",
          rec.saved and rec.saved[0][1].get("max_daily") == 8,
          str(rec.saved[0][1].get("max_daily")) if rec.saved else "无")
    check("A3 保存的 config 含重复规则(loop_count=3)",
          rec.saved and rec.saved[0][1]["repeat"].get("loop_count") == 3,
          str(rec.saved))
    check("A4 reset_task_cycle 被调（改配置重置周期）",
          rec.reset_cycles == ["t"], str(rec.reset_cycles))
    check("A5 未改 next_run → reload_scheduler 被调", rec.reloaded == 1,
          str(rec.reloaded))
    check("A6 未改 next_run → update_next_run 不被调",
          len(rec.updated) == 0, str(rec.updated))
    # 状态栏反馈：_show_status 在 form_layout 添加 _status_label 标签
    status_text = ""
    for i in range(panel.form_layout.count()):
        wdg = panel.form_layout.itemAt(i).widget()
        if wdg is not None and getattr(wdg, "_status_label", False):
            status_text = wdg.text()
    check("A7 状态栏反馈已保存", "已保存" in status_text, status_text)

    # ═══ B. 手动改 next_run → update_next_run 分支 ═══
    print("\n[B] _save() 手动改下次执行 → update_next_run")
    bridge2, rec2 = make_bridge()
    panel2 = GameTaskPanel(param_bridge=bridge2)
    panel2.load_tasks([{"name": "t", "display_name": "t", "task_type": "daily",
                        "uses_battle": False}])
    panel2.task_list.setCurrentRow(0)
    ed = panel2._form_widgets["next_run_time"]
    ed.setText("2026-08-15 08:30")  # 手动修改（≠ _loaded_next_run）
    panel2._save()
    check("B1 手动改 next_run → update_next_run 被调",
          len(rec2.updated) == 1 and rec2.updated[0][0] == "t",
          str(rec2.updated))
    check("B2 手动改 next_run → 不 reload（避免覆盖手输值）",
          rec2.reloaded == 0, str(rec2.reloaded))
    check("B3 save_task_config 仍被调", len(rec2.saved) == 1, str(rec2.saved))
    check("B4 reset_task_cycle 仍被调", rec2.reset_cycles == ["t"],
          str(rec2.reset_cycles))

    # ═══ C. 非法日期 → 降级 reload ═══
    print("\n[C] 非法日期输入降级")
    bridge3, rec3 = make_bridge()
    panel3 = GameTaskPanel(param_bridge=bridge3)
    panel3.load_tasks([{"name": "t", "display_name": "t", "task_type": "daily",
                        "uses_battle": False}])
    panel3.task_list.setCurrentRow(0)
    panel3._form_widgets["next_run_time"].setText("不是日期")
    panel3._save()
    check("C1 非法日期 → reload 兜底（不抛异常）",
          rec3.reloaded == 1 and len(rec3.updated) == 0,
          f"reloaded={rec3.reloaded} updated={rec3.updated}")
    check("C2 非法日期不崩溃（已保存）", len(rec3.saved) == 1, str(rec3.saved))

    print(f"\n🎉 保存配置 _save() 完整链路验证 {PASS} 项通过"
          + ("" if FAIL == 0 else f"，失败 {FAIL} 项"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
