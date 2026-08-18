"""验证：截图器 + 帧缓存 + 点击器融合（2026-08-15 第十二/十三节落地）。

覆盖：
1. 截图器写帧缓存（frame 轮转）
2. 操作节点执行后自动清帧
3. 识图节点读帧 fallback（旧任务无截图器兼容）
4. 点击器「图标+区域」：区域内识别图标并点击（真实模板匹配）
5. 区域变量引用：变量更新后区域随之变化（循环场景）
6. 图标+区域识别不到 → not_found

（识图器 matcher / 帧对比 frame_diff 已于 2026-08-15 删除：点击器已覆盖
「识别+点击」链路；帧对比无实际使用场景）
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from visual import VisualTaskStore, visual_schema as vs
from visual.graph_runner import run_graph
from visual.nodes import GraphContext
from visual import nodes as vn


# ── 假执行器 / 识别器 ─────────────────────────────────────
class _FakeExecutor:
    def __init__(self):
        self.clicks: list = []
        self.swipes: list = []

    def click_position(self, x, y):
        self.clicks.append((x, y))

    def swipe(self, x1, y1, x2, y2, duration=0.5):
        self.swipes.append((x1, y1, x2, y2))


class _FakeRecognizer:
    def __init__(self, screen):
        self._screen = screen

    def _get_screenshot(self):
        return self._screen


def _make_screen(mark=True):
    """生成 200x300 屏幕；mark=True 时在 (50,50) 画红块"""
    screen = np.full((200, 300, 3), 127, dtype=np.uint8)
    if mark:
        cv2.rectangle(screen, (50, 50), (90, 90), (0, 0, 255), -1)
    return screen


def _make_ctx(tmp: Path, task: dict, screen) -> GraphContext:
    ctx = GraphContext(task=task, assets_dir=tmp, screen_size=(300, 200))
    ctx.executor = _FakeExecutor()
    ctx.recognizer = _FakeRecognizer(screen)
    return ctx


# ── 测试 ─────────────────────────────────────────────────
def test_screenshot_frame_cache():
    """截图器写帧缓存：frame 轮转 prev；测试运行发布帧预览（节点内嵌图片）"""
    tmp = Path(tempfile.mkdtemp(prefix="fr_shot_"))
    store = VisualTaskStore(tmp)
    task = store.create("fr_shot", "截图", "daily")
    shot = vs.new_node("screenshot", name="截图")
    ctx = _make_ctx(tmp, task, _make_screen())

    res = vn.dispatch(shot, ctx)
    assert res.status == "ok", res.message
    assert ctx.frame is not None
    print("  ✅ 截图器写帧缓存")

    # 帧预览发布：publish_image 收到可解码 PNG（截图器节点内嵌显示）
    got = {}
    ctx.publish_image = lambda nid, data: got.update(nid=nid, data=data)
    ctx._shot_time = 0
    vn.dispatch(shot, ctx)
    assert got.get("nid") == shot["id"]
    img = cv2.imdecode(np.frombuffer(got["data"], np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.shape[:2] == (200, 300)
    print("  ✅ 截图器发布帧预览 PNG（供节点内嵌图片显示）")


def test_action_clears_frame():
    """操作节点执行后自动清帧"""
    tmp = Path(tempfile.mkdtemp(prefix="fr_clear_"))
    screen = _make_screen()
    cv2.imwrite(str(tmp / "red.png"), screen[50:90, 50:90].copy())
    store = VisualTaskStore(tmp)
    task = store.create("fr_clear", "清帧", "daily")
    ctx = _make_ctx(tmp, task, screen)
    ctx.frame = screen  # 预置帧（含红块，保证点击成功）

    clicker = vs.new_node("clicker", name="点击")
    clicker["params"] = {"template": "red.png"}
    vn.dispatch(clicker, ctx)
    assert ctx.frame is None, "操作节点执行后应清帧"
    assert ctx.executor.clicks, "应真实点击"
    print("  ✅ 操作节点自动清帧")


def test_sense_fallback_without_screenshotter():
    """无截图器时识图节点 fallback 底层截图（旧任务兼容）"""
    tmp = Path(tempfile.mkdtemp(prefix="fr_fb_"))
    screen = _make_screen()
    cv2.imwrite(str(tmp / "red.png"), screen[50:90, 50:90].copy())
    store = VisualTaskStore(tmp)
    task = store.create("fr_fb", "fallback", "daily")
    ctx = _make_ctx(tmp, task, screen)
    assert ctx.frame is None

    clicker = vs.new_node("clicker", name="点击")
    clicker["params"] = {"template": "red.png"}
    res = vn.dispatch(clicker, ctx)
    assert res.goto == "out", res.message
    assert len(ctx.executor.clicks) == 1, "fallback 截图后应点击命中"
    print("  ✅ 无帧 fallback 自行截图（旧任务不变）")


def test_clicker_icon_region():
    """点击器：识别遮罩图标后，在遮罩覆盖区域内随机点击（模拟人手）"""
    tmp = Path(tempfile.mkdtemp(prefix="fr_click_"))
    screen = _make_screen()
    # 图标 = 红块遮罩（alpha 覆盖整个 40x40 红块 = 点击范围）
    crop = screen[50:90, 50:90].copy()
    rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = 255
    cv2.imwrite(str(tmp / "red.png"), rgba)
    store = VisualTaskStore(tmp)
    task = store.create("fr_click", "图标点击", "daily")
    ctx = _make_ctx(tmp, task, screen)

    clicker = vs.new_node("clicker", name="打怪")
    clicker["params"] = {"template": "red.png"}
    res = vn.dispatch(clicker, ctx)
    print(f"icon_click: goto={res.goto} point={res.data.get('point')}")
    assert res.goto == "out", res.message
    assert len(ctx.executor.clicks) == 1
    px, py = ctx.executor.clicks[0]
    # 点击必在遮罩覆盖区（红块 50..90 绝对像素）
    assert 50 <= px <= 89 and 50 <= py <= 89, \
        f"应在遮罩区域内随机点击: ({px},{py})"
    assert ctx.frame is None, "点击器执行后应清帧"
    # 多次点击验证随机性（不是固定一点）
    pts = set()
    for _ in range(20):
        ctx.executor.clicks.clear()
        ctx.frame = screen
        vn.dispatch(clicker, ctx)
        pts.add(ctx.executor.clicks[0])
    print(f"  20 次点击分布点数: {len(pts)}")
    assert len(pts) >= 3, f"应随机分布而非固定点: {pts}"
    print("  ✅ 遮罩随机点击（点击范围=遮罩区域）")


def test_clicker_icon_region_miss():
    """图标识别不到 → not_found"""
    tmp = Path(tempfile.mkdtemp(prefix="fr_miss_"))
    screen = _make_screen(mark=False)  # 屏幕上没有红块
    cv2.imwrite(str(tmp / "red.png"),
                _make_screen()[50:90, 50:90].copy())
    store = VisualTaskStore(tmp)
    task = store.create("fr_miss", "未命中", "daily")
    ctx = _make_ctx(tmp, task, screen)

    clicker = vs.new_node("clicker", name="打怪")
    clicker["params"] = {"template": "red.png"}
    res = vn.dispatch(clicker, ctx)
    assert res.goto == "not_found", f"识别不到应 not_found: {res.goto}"
    assert not ctx.executor.clicks
    print("  ✅ 图标未命中→not_found")


def test_clicker_icon_entry():
    """图标素材条目（与场景素材同规格的 json 条目）：点击器按条目调用"""
    import json
    tmp = Path(tempfile.mkdtemp(prefix="fr_entry_"))
    screen = _make_screen()  # 红块 (50,50)-(89,89)
    icons = tmp / "visual" / "t1" / "icons"
    icons.mkdir(parents=True)
    # 条目 json（主文件）+ PNG（图片数据，ASCII 文件名）
    crop = screen[50:90, 50:90].copy()
    rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = 255
    cv2.imwrite(str(icons / "icon_a.png"), rgba)
    entry = {"id": "攻击图标", "name": "攻击图标", "image": "icon_a.png",
             "region": [0.0, 0.0, 0.5, 0.5], "threshold": 0.85,
             "created_at": 0}
    (icons / "攻击图标.json").write_text(
        json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    rel = "visual/t1/icons/攻击图标.json"
    store = VisualTaskStore(tmp)
    task = store.create("fr_entry", "条目点击", "daily")
    ctx = _make_ctx(tmp, task, screen)

    clicker = vs.new_node("clicker", name="打怪")
    clicker["params"] = {"template": rel}
    res = vn.dispatch(clicker, ctx)
    print(f"entry_click: goto={res.goto} point={res.data.get('point')}")
    assert res.goto == "out", res.message
    px, py = ctx.executor.clicks[0]
    assert 50 <= px <= 89 and 50 <= py <= 89, f"点击应落在遮罩内: ({px},{py})"

    # 条目红框不含红块 → not_found
    ctx.executor.clicks.clear()
    entry["region"] = [0.4, 0.4, 0.6, 0.6]
    (icons / "攻击图标.json").write_text(
        json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    res2 = vn.dispatch(clicker, ctx)
    assert res2.goto == "not_found", f"条目红框外应 not_found: {res2.goto}"
    assert not ctx.executor.clicks
    print("  ✅ 图标素材条目：点击器按条目调用（红框生效）")


def test_region_variable_ref():
    """图标元数据红框（搜索区域）：区域内命中 / 区域外 not_found"""
    import json
    tmp = Path(tempfile.mkdtemp(prefix="fr_var_"))
    screen = _make_screen()  # 红块在 (50,50)
    cv2.imwrite(str(tmp / "red.png"), screen[50:90, 50:90].copy())
    store = VisualTaskStore(tmp)
    task = store.create("fr_var", "图标区域", "daily")
    ctx = _make_ctx(tmp, task, screen)

    clicker = vs.new_node("clicker", name="打怪")
    clicker["params"] = {"template": "red.png"}

    # 元数据红框包含红块 → 命中
    (tmp / "red.json").write_text(
        json.dumps({"region": [0.0, 0.0, 0.5, 0.5]}), encoding="utf-8")
    res = vn.dispatch(clicker, ctx)
    assert res.goto == "out", f"红框区域内应命中: {res.message}"

    # 元数据红框不含红块 → not_found（模拟循环不同区域）
    ctx.executor.clicks.clear()
    (tmp / "red.json").write_text(
        json.dumps({"region": [0.4, 0.4, 0.6, 0.6]}), encoding="utf-8")
    res2 = vn.dispatch(clicker, ctx)
    assert res2.goto == "not_found", "红框区域外应 not_found"
    assert not ctx.executor.clicks
    print("  ✅ 图标红框搜索区域生效（示教保存的元数据）")


if __name__ == "__main__":
    test_screenshot_frame_cache()
    test_action_clears_frame()
    test_sense_fallback_without_screenshotter()
    test_clicker_icon_region()
    test_clicker_icon_region_miss()
    test_clicker_icon_entry()
    test_region_variable_ref()
    print("\n🎉 verify_visual_frame_nodes 全部通过")
