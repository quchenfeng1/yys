"""验证：多分辨率适配——示教坐标相对存储，运行时按实际 screen_size 换算。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visual import visual_schema as vs
from visual.nodes import GraphContext, _abs_point


def test_coord_roundtrip():
    # 相对↔绝对 往返
    assert vs.abs_to_rel(540, 960, 1080, 1920) == (0.5, 0.5)
    assert vs.rel_to_abs(0.5, 0.5, 1080, 1920) == (540, 960)
    print("  ✅ 相对坐标↔绝对坐标 往返正确")


def test_region():
    # 相对区域 → 绝对像素
    assert vs.region_to_abs([0.1, 0.1, 0.5, 0.5], 1000, 2000) == (100, 200, 500, 1000)
    # 绝对区域原样返回
    assert vs.region_to_abs([100, 200, 300, 400], 1000, 2000) == (100, 200, 300, 400)
    print("  ✅ 区域相对/绝对换算正确")


def test_abs_point_multires():
    """同一相对示教点在两种分辨率下都落在对应比例位置（多分辨率核心）"""
    ctx1080 = GraphContext(screen_size=(1080, 1920))
    ctx720 = GraphContext(screen_size=(720, 1280))
    pt = {"x": 0.5, "y": 0.5, "mode": "relative"}  # 屏幕中心
    assert _abs_point(ctx1080, pt) == (540, 960)
    assert _abs_point(ctx720, pt) == (360, 640)
    # absolute 点不受分辨率影响（原样返回）
    pt_abs = {"x": 100, "y": 200, "mode": "absolute"}
    assert _abs_point(ctx1080, pt_abs) == (100, 200)
    assert _abs_point(ctx720, pt_abs) == (100, 200)
    print("  ✅ 相对示教点随分辨率正确缩放")


def test_visual_task_screen_size_inference():
    """VisualTask.execute 从实际截图推断 screen_size（而非硬编码）"""
    import numpy as np
    from visual.visual_task import VisualTask

    class _FakeConn:
        def screenshot(self, use_cache=True):
            return np.zeros((1280, 720, 3), np.uint8)  # 720x1280 设备

    class _FakeExec:
        _connection = _FakeConn()

    class _Ctx:
        executor = _FakeExec()
        recognizer = None
        stop_event = None
        cycle_limit_event = None
        dry_run = False

    # 动态子类化注入定义
    cls = type("VT", (VisualTask,), {})
    cls._definition = {
        "name": "t1", "category": "daily", "display_name": "多分辨率测试",
        "graph": {},
    }
    cls._assets_dir = str(Path(__file__).resolve().parent.parent)
    vt = cls("t1")

    # monkeypatch run_graph 捕获传入的 screen_size
    import visual.visual_task as vv
    captured = {}

    def fake_run(graph, gctx):
        captured["screen_size"] = gctx.screen_size
        from visual.graph_runner import GraphRunResult
        return GraphRunResult(status="success", reason="ok")

    vv.run_graph = fake_run
    vt.execute(_Ctx())
    assert captured["screen_size"] == (720, 1280), captured
    print("  ✅ VisualTask 从实际截图推断 screen_size (720x1280)")


if __name__ == "__main__":
    test_coord_roundtrip()
    test_region()
    test_abs_point_multires()
    test_visual_task_screen_size_inference()
    print("\n🎉 多分辨率适配验证通过")
