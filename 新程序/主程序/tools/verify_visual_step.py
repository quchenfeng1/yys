"""验证：单步调试（2026-08-15）。

👣 单步测试 → 每个节点执行前暂停（红框高亮）；⏭ 下一步放行一步。
出问题时停在出错节点上，日志可见具体错误。
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from visual import visual_schema as vs
from visual.rule_store import VisualTaskStore
from visual.teach_engine import TeachEngine
from core.event_bus import get_global_bus
from core.events import Events


class _FakeExecutor:
    def click_position(self, *a):
        pass

    def swipe(self, *a, **k):
        pass


def _mk_task(store: VisualTaskStore, name: str) -> dict:
    task = store.create(name, "单步", "daily")
    graph = task["graph"]
    start = vs.find_node_by_type(graph, "start")
    sv = vs.new_node("set_var")
    sv["params"] = {"var_name": "n", "var_value": "1"}
    end = vs.new_node("end")
    graph["nodes"] = [start, sv, end]
    graph["connections"] = [
        vs.new_connection(sv["id"], "in", start["id"], "out"),
        vs.new_connection(end["id"], "in", sv["id"], "out"),
    ]
    store.save(task)
    return task


def test_step_mode_pause_and_advance():
    """单步：每节点前暂停；下一步放行；不点不推进"""
    tmp = Path(tempfile.mkdtemp(prefix="step_"))
    store = VisualTaskStore(tmp)
    _mk_task(store, "step_task")
    bus = get_global_bus()
    highlights: list = []
    bus.subscribe(Events.VISUAL_NODE_EXEC,
                  lambda **kw: highlights.append(kw.get("node_id")))
    eng = TeachEngine(event_bus=bus, store=store, assets_dir=str(tmp),
                      executor=_FakeExecutor())
    assert eng.teach_run("step_task", step_mode=True)
    assert eng.step_mode
    time.sleep(0.6)
    assert eng.is_running, "应停在第一步等待下一步"
    assert highlights, "应已高亮第一个节点"
    # 不点下一步 → 不推进
    snap = len(highlights)
    time.sleep(0.4)
    assert len(highlights) == snap, "未点下一步不应推进"
    # 逐步走完（start → set_var → end）
    eng.next_step()
    time.sleep(0.3)
    eng.next_step()
    time.sleep(0.3)
    eng.next_step()
    time.sleep(0.6)
    assert not eng.is_running, "应运行结束"
    assert not eng.step_mode
    assert highlights[-1] == "", "结束应清除高亮（node_id=''）"
    print("  ✅ 单步暂停/放行/结束清高亮")


def test_step_stop_releases_wait():
    """单步等待中停止 → 立即解除等待退出"""
    tmp = Path(tempfile.mkdtemp(prefix="step_stop_"))
    store = VisualTaskStore(tmp)
    _mk_task(store, "step_stop")
    eng = TeachEngine(store=store, assets_dir=str(tmp),
                      executor=_FakeExecutor())
    assert eng.teach_run("step_stop", step_mode=True)
    time.sleep(0.4)
    assert eng.is_running
    eng.stop()
    time.sleep(0.5)
    assert not eng.is_running, "停止应解除单步等待"
    print("  ✅ 停止解除单步等待")


if __name__ == "__main__":
    test_step_mode_pause_and_advance()
    test_step_stop_releases_wait()
    print("\n🎉 verify_visual_step 全部通过")
