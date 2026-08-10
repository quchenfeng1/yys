"""验证：任务执行完/被中断后，「下次执行」在游戏任务配置 UI 中实时同步。

链路：
  mark_done（执行完/失败）→ 推进 next_run → 发布 SCHEDULE_UPDATED
    → MainWindow._ui_schedule_updated → _sync_game_next_run
    → game_task_panel.refresh_next_run_time() → 更新「下次执行」输入框

覆盖：
  ① 渲染表单后显示初始 next_run
  ② 任务执行完（mark_done 推进 next_run）→ refresh 后输入框实时更新
  ③ 失败场景（mark_done success=False → 冷却推进）→ 刷新更新
  ④ 用户手动编辑中 → 刷新跳过（不覆盖手输值）
  ⑤ 编辑值=已加载值（未修改）→ 刷新正常更新
  ⑥ MainWindow._sync_game_next_run 经 fake window 调用生效
"""
import os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

PASS = 0


def check(label, cond, detail=""):
    global PASS
    assert cond, f"FAIL: {label}  {detail}"
    PASS += 1
    print(f"PASS {label}")


def build_raw(name, rtype="daily"):
    return SimpleNamespace(
        name=name, display_name=name, category="daily", enabled=True,
        priority=10, time_start="06:00", time_end="23:59", max_daily=None,
        active_range=None, total_count=None, execution_mode="daily",
        loop_count=1, time_slots=None,
        repeat={"type": rtype, "value": 1, "loop_count": 1},
    )


class FakeBridge:
    """模拟 TaskBridge（get_task_detail / get_next_run_time 走真实 Scheduler）"""
    def __init__(self, scheduler):
        self.task = SimpleNamespace(
            get_task_detail=self._detail,
            get_next_run_time=self._nrt,
        )
        self._sched = scheduler

    def _detail(self, name):
        nrt = self._sched.get_next_run_time(name)
        return {
            "name": name, "display_name": name, "task_type": "daily",
            "uses_battle": False, "uses_team": False, "uses_soul": False,
            "uses_stamina": False, "enabled": True,
            "repeat": {"type": "daily", "value": 1, "loop_count": 1},
            "time_start": "06:00", "time_end": "23:59", "time_slots": None,
            "active_range": None, "max_daily": None, "total_count": None,
            "execution_mode": "daily", "loop_count": 1, "priority": 10,
            "next_run_time": nrt.strftime("%Y-%m-%d %H:%M") if nrt else "",
        }

    def _nrt(self, name):
        nrt = self._sched.get_next_run_time(name)
        return nrt.strftime("%Y-%m-%d %H:%M") if nrt else None


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    from core.event_bus import EventBus
    from core.scheduler import Scheduler, ScheduleStatus

    bus = EventBus()
    fake_cfg = SimpleNamespace(tasks_config=SimpleNamespace(tasks=[build_raw("daily_test")]))
    sched = Scheduler(event_bus=bus, config=fake_cfg, state_manager=None, store=None)
    sched.load_tasks_from_config()

    bridge = FakeBridge(sched)

    from ui.panels.game_task_panel import GameTaskPanel
    panel = GameTaskPanel(param_bridge=bridge)
    # 加载任务并选中（触发渲染）
    panel.load_tasks([{"name": "daily_test", "display_name": "日常测试",
                       "task_type": "daily", "uses_battle": False}])
    panel.task_list.setCurrentRow(0)

    ed = panel._form_widgets.get("next_run_time")
    check("① 渲染后显示初始 next_run", ed is not None and ed.text() != "")

    # 记录初始值（daily 窗口内 → 初始 next_run≈now）
    init_text = ed.text()

    # ═══ ② 任务执行完：mark_done 推进 next_run → 刷新同步 ═══
    sched.mark_done("daily_test", True)  # 成功 → next_run=明天 06:00
    panel.refresh_next_run_time()
    updated = ed.text()
    check("② 执行完刷新后输入框更新", updated != init_text, f"{init_text} → {updated}")
    check("② 更新为明天 06:00", "06:00" in updated and updated > init_text, updated)

    # ═══ ③ 失败场景：mark_done(False) 冷却推进 → 刷新同步 ═══
    sched.mark_done("daily_test", False)  # 失败 → 冷却（5min）
    before = ed.text()
    panel.refresh_next_run_time()
    after = ed.text()
    check("③ 失败后刷新同步", after != init_text and after == panel._loaded_next_run,
          f"{before} → {after}")

    # ═══ ④ 用户手动编辑中 → 刷新跳过 ═══
    sched.mark_done("daily_test", True)
    ed.setText("2026-09-01 10:00")  # 用户手输
    panel.refresh_next_run_time()
    check("④ 编辑中不被覆盖", ed.text() == "2026-09-01 10:00", ed.text())

    # ═══ ⑤ 编辑值 = 已加载值（未修改）→ 正常刷新 ═══
    sched.mark_done("daily_test", True)  # 再推进一次
    panel._loaded_next_run = ed.text()   # 视作系统显示值
    panel.refresh_next_run_time()
    check("⑤ 未编辑状态正常刷新", ed.text() == panel._loaded_next_run,
          f"loaded={panel._loaded_next_run} text={ed.text()}")

    # ═══ ⑥ MainWindow._sync_game_next_run 调用链 ═══
    from ui.main_window import MainWindow
    import types
    fake_win = SimpleNamespace(panels={"game_task": panel})
    fake_win._sync_game_next_run = types.MethodType(MainWindow._sync_game_next_run, fake_win)
    sched.mark_done("daily_test", True)
    fake_win._sync_game_next_run()
    check("⑥ _sync_game_next_run 生效", ed.text() == panel._loaded_next_run)

    print(f"\n🎉 下次执行实时同步验证 {PASS} 项通过")


if __name__ == "__main__":
    main()
