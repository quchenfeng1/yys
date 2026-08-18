"""
任务队列进度验证：RunBridge.get_current_progress 与执行进度抽屉（2026-08-16）。

覆盖：
① 无 controller → 0
② 无当前任务 → 0
③ 无 state_mgr → 0
④ 有进度 5/10 → 50
⑤ 0/10 → 0
⑥ 完成 10/10 → 100
⑦ 超 100 钳制 → 100
⑧ 非法 entry（非 dict）→ 0
⑨ 执行进度抽屉：当前步骤/进度字段/转圈图标/进度图（进度条已移除）
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QProgressBar

from ui.param_bridge.run_bridge import RunBridge
from ui.panels.task_queue_panel import TaskQueuePanel


class FakeStateMgr:
    def __init__(self, data: dict):
        self._data = data

    def get_state(self, key: str, default=None):
        return self._data.get(key, default)


class FakeCtrl:
    def __init__(self, current, progress_data, state_mgr=None):
        self.current_task = current
        self._state_mgr = state_mgr or FakeStateMgr({"task_runtime_progress": progress_data})
        self.queue_snapshot = []


PASS = 0


def check(label, cond):
    global PASS
    assert cond, f"FAIL: {label}"
    PASS += 1
    print(f"PASS {label}")


# ① 无 controller
rb = RunBridge(controller=None)
check("无controller→0", rb.get_current_progress() == 0)

# ② 无当前任务
rb = RunBridge(controller=FakeCtrl(None, {}))
check("无当前任务→0", rb.get_current_progress() == 0)

# ③ 无 state_mgr
ctrl = FakeCtrl("yuhun", {})
ctrl._state_mgr = None
rb = RunBridge(controller=ctrl)
check("无state_mgr→0", rb.get_current_progress() == 0)

# ④ 5/10 → 50
rb = RunBridge(controller=FakeCtrl("yuhun", {"yuhun": {"completed": 5, "total": 10}}))
check("5/10→50", rb.get_current_progress() == 50)

# ⑤ 0/10 → 0
rb = RunBridge(controller=FakeCtrl("yuhun", {"yuhun": {"completed": 0, "total": 10}}))
check("0/10→0", rb.get_current_progress() == 0)

# ⑥ 10/10 → 100
rb = RunBridge(controller=FakeCtrl("yuhun", {"yuhun": {"completed": 10, "total": 10}}))
check("10/10→100", rb.get_current_progress() == 100)

# ⑦ 超100钳制
rb = RunBridge(controller=FakeCtrl("yuhun", {"yuhun": {"completed": 99, "total": 10}}))
check("99/10→100钳制", rb.get_current_progress() == 100)

# ⑧ 非法 entry
rb = RunBridge(controller=FakeCtrl("yuhun", {"yuhun": "bad"}))
check("非dict entry→0", rb.get_current_progress() == 0)

# ⑨ 执行进度抽屉（2026-08-16 替换总体进度条）：快照驱动当前步骤/进度字段/进度图
app = QApplication.instance() or QApplication([])
panel = TaskQueuePanel()
panel.update_panel("t_prog", [], [], [])
check("默认无任务→当前步骤为无", panel.step_label.text() == "无")
check("默认转圈图标隐藏", panel.spinner.isHidden())
panel._apply_snapshot({
    "task_id": "t_prog", "current": "战斗",
    "points": [{"id": "a", "name": "准备", "row": 0, "col": 0},
               {"id": "b", "name": "战斗", "row": 0, "col": 1}],
    "states": {"a": "green", "b": "blue"},
    "edges": [],
})
check("当前步骤=战斗", panel.step_label.text() == "战斗")
check("有步骤→转圈图标显示且旋转",
      not panel.spinner.isHidden()
      and panel.spinner._timer.isActive())
check("进度字段=1/2", "1/2" in panel.progress_summary.text())
check("进度图收到快照", panel.thumb._snapshot is not None)
# 切换任务 → 进度视图重置
panel.update_panel("other", [], [], [])
check("切任务后步骤名=无", panel.step_label.text() == "无")
check("切任务后转圈隐藏", panel.spinner.isHidden())
check("切任务后进度图清空", panel.thumb._snapshot is None)

print(f"\n🎉 任务队列进度验证 {PASS} 项通过")
