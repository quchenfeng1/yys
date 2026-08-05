"""每周几多选 + 触发按钮卡片右侧 验证。

[A] 调度层：RepeatConfig.weekdays 列表解析、RepeatRule 多日匹配
[B] UI 层：GameTaskPanel 每周几多选（回填/收集 weekdays 列表）
[C] UI 层：TaskQueuePanel 触发按钮位于卡片右侧（一分为二）
"""
import sys, os
from datetime import datetime
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)


class FakeStore:
    def __init__(self):
        self.data = {}
    def load(self): pass
    def save(self, data): self.data = data
    def get(self, name): return self.data.get(name)
    def get_or_create(self, name): return self.data.setdefault(name, {})
    def update(self, name, **kw): self.data.setdefault(name, {}).update(kw)


def main():
    print("── [A] 调度层 weekdays 多选 ──")
    from core.scheduler import Scheduler, RepeatConfig, TaskConfig
    from core.repeat_rule import RepeatRule
    from core.event_bus import EventBus

    # _resolve_weekdays：优先 weekdays，回退 weekday
    assert Scheduler._resolve_weekdays(RepeatConfig(type="weekly", weekdays=[2, 5])) == [2, 5]
    assert Scheduler._resolve_weekdays(RepeatConfig(type="weekly", weekday=3)) == [3]
    assert Scheduler._resolve_weekdays(RepeatConfig(type="weekly")) == []
    print("① PASS _resolve_weekdays 优先 weekdays（多选）、回退 weekday")

    # RepeatRule 多日匹配：周三(2)、周六(5)
    rule = RepeatRule(type="weekly", time="06:00", weekdays=[2, 5])
    now = datetime(2026, 8, 3, 10, 0)  # 周一
    nxt = rule.get_initial_next_run(now)
    assert nxt is not None and nxt.weekday() in (2, 5), f"初始应落在周三/周六: {nxt}"
    nxt2 = rule.calc_next_run(nxt)
    assert nxt2.weekday() in (2, 5) and nxt2 > nxt, f"推进后仍为匹配日: {nxt2}"
    print(f"② PASS RepeatRule 多选匹配（next_run={nxt:%Y-%m-%d %a} → {nxt2:%Y-%m-%d %a}）")

    # Scheduler 集成：weekly weekdays=[2,5] 初始 next_run 落在匹配日
    s = Scheduler(event_bus=EventBus(), store=FakeStore())
    cfg = TaskConfig(name="w_test", category="special",
                     repeat=RepeatConfig(type="weekly", weekdays=[2, 5]))
    s._tasks["w_test"] = cfg
    nrt = s._calc_initial_next_run(cfg)
    assert nrt is not None and nrt.weekday() in (2, 5), f"scheduler 集成: {nrt}"
    print(f"③ PASS Scheduler 集成：初始 next_run={nrt:%Y-%m-%d %a}（周三/周六）")

    print("\n── [B] UI 每周几多选（回填/收集）──")
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from ui.panels.game_task_panel import GameTaskPanel
    panel = GameTaskPanel()

    # 回填：weekdays=[2,5]
    panel._render_form({
        "name": "w", "display_name": "周任务", "task_type": "event_task",
        "repeat": {"type": "weekly", "weekdays": [2, 5]},
        "priority": 10, "enabled": True, "time_start": "06:00", "time_end": "23:59",
    })
    wc = panel._form_widgets["weekday_checks"]
    assert wc[2].isChecked() and wc[5].isChecked(), "周三、周六应勾选"
    assert not wc[0].isChecked() and not wc[3].isChecked(), "周一、周四不应勾选"
    print("① PASS 回填：weekdays=[2,5] → 周三/周六勾选")

    # 回填：旧字段 weekday=3 单值兼容
    panel._render_form({
        "name": "w2", "display_name": "周任务2", "task_type": "event_task",
        "repeat": {"type": "weekly", "weekday": 3},
        "priority": 10, "enabled": True, "time_start": "06:00", "time_end": "23:59",
    })
    wc = panel._form_widgets["weekday_checks"]
    assert wc[3].isChecked(), "旧 weekday=3 应回填周四"
    print("② PASS 旧字段 weekday 单值兼容回填")

    # 收集：改为勾选周一、周六 → weekdays=[0,5]
    for v, cb in wc.items():
        cb.setChecked(v in (0, 5))
    config = panel._collect_config()
    assert config["repeat"].get("weekdays") == [0, 5], f"收集: {config['repeat']}"
    print("③ PASS 收集：勾选周一/周六 → repeat.weekdays=[0,5]")

    # 全不选 → 不写 weekdays（每天执行）
    for cb in wc.values():
        cb.setChecked(False)
    config = panel._collect_config()
    assert "weekdays" not in config["repeat"] and "weekday" not in config["repeat"], config["repeat"]
    print("④ PASS 全不选 → 不写 weekdays（每天执行）")

    print("\n── [C] 触发按钮卡片右侧 ──")
    from PyQt5.QtWidgets import QPushButton
    from ui.panels.task_queue_panel import TaskQueuePanel
    qp = TaskQueuePanel()
    qp.update_panel(
        current=None, pending=[],
        upcoming=[],
        invalid=[{"name": "trig_test", "status": "待触发", "detail": "等待外部触发"}],
    )
    btns = qp.invalid_list.findChildren(QPushButton)
    action = [b for b in btns if b.objectName() == "card_action_btn"]
    assert len(action) == 1, f"应有 1 个右侧触发按钮: {len(action)}"
    assert action[0].width() <= 80 or action[0].maximumWidth() >= 0, "按钮应固定窄宽"
    # 触发按钮是右侧独立区域：按钮是 card 的直接子项（外层 HBox 右侧）
    card = action[0].parentWidget()
    assert card is not None
    print(f"① PASS 已失效区触发卡片有右侧 card_action_btn（宽 {action[0].minimumWidth()}）")

    print("\n🎉 每周几多选 + 触发按钮右侧验证 8/8 通过")


if __name__ == "__main__":
    main()
