"""验证：图标计数节点（2026-08-15）。

覆盖：
1. 屏幕 3 个图标 → count=3，数目写入输出变量，data.matches=3
2. 无匹配 → count=0
3. 红框搜索区域限制 → 只计区域内实例
4. 随机点击素材（region_click）→ 不支持计数（error）
5. dispatch 注册表路径跑通；变量可供分支引用
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import cv2
import numpy as np

from visual.nodes import GraphContext, _exec_icon_count, dispatch


class _Rec:
    def _get_screenshot(self):
        return self._screen


def _make_ctx(tmp: Path, screen, task=None) -> GraphContext:
    ctx = GraphContext(task=task or {}, assets_dir=str(tmp),
                       screen_size=(300, 200))
    rec = _Rec()
    rec._screen = screen
    ctx.recognizer = rec
    ctx._screenshot = screen
    return ctx


def _write_entry(tmp: Path, name: str, entry: dict, mask=None) -> str:
    d = tmp / "visual" / "t1" / "icons"
    d.mkdir(parents=True, exist_ok=True)
    if mask is not None:
        cv2.imencode(".png", mask)[1].tofile(str(d / f"{name}.png"))
    (d / f"{name}.json").write_text(json.dumps(entry, ensure_ascii=False),
                                    encoding="utf-8")
    return f"visual/t1/icons/{name}.json"


def _screen_with_blocks() -> np.ndarray:
    """300x200 灰底 + 3 个 60x60 蓝块（互不重叠，间隔 > 模板尺寸）"""
    screen = np.full((200, 300, 3), 127, np.uint8)
    for x, y in ((10, 10), (120, 10), (10, 120)):
        screen[y:y + 60, x:x + 60] = (255, 0, 0)
    return screen


def _mask():
    m = np.zeros((60, 60, 4), np.uint8)
    m[..., 0] = 255
    m[..., 3] = 255
    return m


def test_count_three():
    tmp = Path(tempfile.mkdtemp(prefix="ic1_"))
    rel = _write_entry(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png",
        "region": None, "threshold": 0.85}, _mask())
    ctx = _make_ctx(tmp, _screen_with_blocks())
    r = _exec_icon_count({"params": {"template": rel, "output_var": "n"}}, ctx)
    assert r.status == "ok" and r.goto == "out", r
    assert r.data["count"] == 3, r.data
    assert len(r.data["matches"]) == 3, r.data
    assert int(ctx.vars["n"]) == 3, ctx.vars
    print("  ✅ 3 个图标 → count=3 + 输出变量 n=3 + matches 3 个")


def test_count_zero_and_region():
    tmp = Path(tempfile.mkdtemp(prefix="ic2_"))
    rel = _write_entry(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png",
        "region": None, "threshold": 0.85}, _mask())
    # 无匹配
    empty = np.full((200, 300, 3), 127, np.uint8)
    ctx0 = _make_ctx(tmp, empty)
    r0 = _exec_icon_count({"params": {"template": rel, "output_var": "n"}},
                          ctx0)
    assert r0.data["count"] == 0 and int(ctx0.vars["n"]) == 0
    # 红框区域限制：只搜左上四分之一（只含第一个蓝块）
    rel_r = _write_entry(tmp, "icon2", {
        "id": "icon2", "name": "icon2", "image": "icon.png",
        "region": [0.0, 0.0, 0.5, 0.5], "threshold": 0.85}, _mask())
    ctx = _make_ctx(tmp, _screen_with_blocks())
    r = _exec_icon_count({"params": {"template": rel_r, "output_var": "n"}},
                         ctx)
    assert r.data["count"] == 1, r.data
    print("  ✅ 无匹配→0；红框区域限制只计区域内（3 个只算 1 个）")


def test_region_click_rejected():
    tmp = Path(tempfile.mkdtemp(prefix="ic3_"))
    rel = _write_entry(tmp, "rand", {
        "id": "rand", "name": "rand", "image": "rand.png",
        "region": [0.1, 0.1, 0.3, 0.3], "threshold": 0.85,
        "mode": "region_click"}, None)
    ctx = _make_ctx(tmp, _screen_with_blocks())
    r = _exec_icon_count({"params": {"template": rel}}, ctx)
    assert r.status == "error" and "不支持计数" in r.message, r
    print("  ✅ 随机点击素材 → 明确报错不支持计数")


def test_dispatch_and_branch_flow():
    """dispatch 注册表路径 + 计数变量进分支判断（模拟循环结束条件）"""
    tmp = Path(tempfile.mkdtemp(prefix="ic4_"))
    rel = _write_entry(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png",
        "region": None, "threshold": 0.85}, _mask())
    ctx = _make_ctx(tmp, _screen_with_blocks())
    r = dispatch({"type": "icon_count", "name": "计数",
                  "params": {"template": rel, "output_var": "n"}}, ctx)
    assert r.status == "ok" and int(ctx.vars["n"]) == 3
    # 分支引用计数变量（branch 数据源读变量）
    br = dispatch({"type": "branch", "name": "分支",
                   "params": {"data_source": "n", "op": ">=",
                              "value": "3"}}, ctx)
    assert br.goto == "true", br
    print("  ✅ dispatch 注册表跑通；计数变量进分支判断（n>=3 → true）")


if __name__ == "__main__":
    test_count_three()
    test_count_zero_and_region()
    test_region_click_rejected()
    test_dispatch_and_branch_flow()
    print("\n🎉 verify_visual_icon_count 全部通过")
