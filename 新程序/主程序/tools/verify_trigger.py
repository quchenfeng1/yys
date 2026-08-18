"""trigger 特殊条件触发退役验证（2026-08-16 改写）。

新体系 = 图内「任务信号触发器」节点（见 verify_signal_nodes.py）；
旧「特殊条件触发」（repeat.type=trigger + trigger_templates 识图触发）功能下线：

  ① UI 下拉不再提供 trigger 类型（新任务无法创建）
  ② 触发信号多选控件已移除
  ③ 旧 trigger 配置渲染/保存兼容（类型与 trigger_templates 不丢失）
  ④ 调度层旧 trigger 例外代码保留（兼容已有配置）
"""
import sys
import os
from pathlib import Path

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from core.scheduler import Scheduler, RepeatConfig, TaskConfig  # noqa: E402
from ui.panels.game_task_panel import GameTaskPanel       # noqa: E402


class FakeStore:
    def __init__(self):
        self.data = {}

    def load(self):
        pass

    def save(self, data):
        self.data = data

    def get(self, name):
        return self.data.get(name)

    def get_or_create(self, name):
        return self.data.setdefault(name, {})

    def update(self, name, **kw):
        self.data.setdefault(name, {}).update(kw)


def main():
    ok, fail = 0, 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"✅ {name}")
        else:
            fail += 1
            print(f"❌ {name}  {detail}")

    # ═══ ① 下拉移除 trigger ═══
    panel = GameTaskPanel()
    panel._render_form({"name": "t", "display_name": "t",
                        "task_type": "special", "enabled": True,
                        "repeat": {"type": "daily"}})
    cb = panel._form_widgets["repeat_type"]
    check("① 下拉无 trigger 选项",
          cb.findData("trigger") < 0 and "特殊条件触发" not in
          [cb.itemText(i) for i in range(cb.count())],
          str([cb.itemText(i) for i in range(cb.count())]))

    # ═══ ② 触发信号多选控件已移除 ═══
    check("② 触发信号控件已移除",
          "trigger_templates" not in panel._form_widgets
          and "trigger_label" not in panel._form_widgets,
          str(panel._form_widgets.keys()))

    # ═══ ③ 旧 trigger 配置兼容：回显 + 保存不丢字段 ═══
    panel._render_form({"name": "t", "display_name": "t",
                        "task_type": "special", "enabled": True,
                        "repeat": {"type": "trigger",
                                   "trigger_templates": ["trigger/red_dot"]}})
    cb2 = panel._form_widgets["repeat_type"]
    check("③ 旧配置回显 trigger（已下线）", cb2.currentData() == "trigger",
          str(cb2.currentData()))
    cfg = panel._collect_config()
    check("③ 保存保留旧 trigger_templates",
          cfg["repeat"]["type"] == "trigger"
          and cfg["repeat"]["trigger_templates"] == ["trigger/red_dot"],
          str(cfg["repeat"]))
    check("③ trigger 时间字段置空", cfg["time_start"] is None
          and cfg["time_end"] is None and cfg["time_slots"] is None,
          str((cfg["time_start"], cfg["time_end"], cfg["time_slots"])))

    # ═══ ④ 调度层旧 trigger 例外代码保留（兼容已有配置） ═══
    s = Scheduler(event_bus=None, store=FakeStore())
    s._tasks["trig_test"] = TaskConfig(
        name="trig_test", display_name="触发测试", category="special",
        priority=5,
        repeat=RepeatConfig(type="trigger", trigger_templates=["trigger/red_dot"]),
    )
    s.load_state()
    nrt = s._calc_initial_next_run(s._tasks["trig_test"])
    check("④ 旧 trigger 初始无 next_run（待触发）", nrt is None, str(nrt))
    inv = s.get_invalid_tasks()
    entry = [x for x in inv if x["name"] == "trig_test"]
    check("④ 旧 trigger 已失效区「待触发」标注",
          bool(entry) and entry[0]["status"] == "待触发", str(entry))

    print(f"\n{'=' * 46}")
    print(f"🎉 trigger 退役验证 {ok}/{ok + fail} 通过")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
