"""
任务队列进度验证：RunBridge.get_current_progress 与 TaskQueuePanel.set_progress。

覆盖：
① 无 controller → 0
② 无当前任务 → 0
③ 无 state_mgr → 0
④ 有进度 5/10 → 50
⑤ 0/10 → 0
⑥ 完成 10/10 → 100
⑦ 超 100 钳制 → 100
⑧ 非法 entry（非 dict）→ 0
⑨ TaskQueuePanel.set_progress 设置进度条数值
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

# ⑨ set_progress 设置进度条
app = QApplication.instance() or QApplication([])
panel = TaskQueuePanel()
panel.set_progress(50)
bar = panel.findChild(QProgressBar)
check("进度条存在", bar is not None)
check("进度条值=50", bar is not None and bar.value() == 50)
panel.set_progress(100)
check("进度条值=100", bar is not None and bar.value() == 100)
panel.set_progress(-5)
check("进度条负数钳制(内部)", bar is not None and bar.value() >= 0)

print(f"\n🎉 任务队列进度验证 {PASS} 项通过")
