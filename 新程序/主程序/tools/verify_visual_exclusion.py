"""验证：排除素材（2026-08-15）。

覆盖：
1. 条目解析：exclusions.image 文件名 → assets 根相对路径
2. 排除命中：region 相对图标框换算；命中/未命中
3. 点击器：多候选逐个排除检查，点第一个未排除实例；全排除 → not_found
4. 场景判定：marker 带 exclusions，命中排除特征 → 场景不通过
5. 排除示教：低阈值预筛无匹配提示；候选升序；抠图显示；保存追加条目 exclusions
6. 旧任务兼容：无 exclusions 字段行为不变
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
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
from visual.nodes import (GraphContext, _exec_clicker, _icon_entry,
                          _exclusions_hit, _judge_scene_v2_score)
from ui.visual_builder.exclusion_teach import ExclusionTeachWidget


class _Ex:
    def __init__(self, screen):
        self.clicks = []
        self._screen = screen

    def click_position(self, x, y):
        self.clicks.append((int(x), int(y)))


def _make_ctx(tmp, screen):
    ctx = GraphContext(task={}, assets_dir=str(tmp), screen_size=(300, 200))
    ctx.executor = _Ex(screen)
    ctx._screenshot = screen
    return ctx


def _icon_mask():
    m = np.zeros((60, 60, 4), np.uint8)
    m[..., 0] = 255
    m[..., 3] = 255
    return m


def _red_dot_mask():
    m = np.zeros((10, 10, 4), np.uint8)
    m[..., 2] = 255   # 红点：R 通道
    m[..., 3] = 255
    return m


def _write(tmp: Path, name: str, entry: dict, mask=None) -> str:
    d = tmp / "visual" / "t1" / "icons"
    d.mkdir(parents=True, exist_ok=True)
    if mask is not None:
        cv2.imencode(".png", mask)[1].tofile(str(d / f"{name}.png"))
    (d / f"{name}.json").write_text(json.dumps(entry, ensure_ascii=False),
                                    encoding="utf-8")
    return f"visual/t1/icons/{name}.json"


def _screen_three_blocks(with_dot=False):
    """300x200 灰底 + 3 个蓝块；with_dot 时第一个蓝块**右侧邻域**加红点
    （排除特征画在图标邻域，不影响主图标匹配分数，保证候选同分按位置序）"""
    s = np.full((200, 300, 3), 127, np.uint8)
    for x, y in ((10, 10), (120, 10), (10, 120)):
        s[y:y + 60, x:x + 60] = (255, 0, 0)
    if with_dot:
        s[10:20, 70:80] = (0, 0, 255)   # 图标1 (10,10) 右侧 (70,10)
    return s


# ── 1/2. 条目解析 + 排除命中 ─────────────────────────────
def test_entry_parse_and_hit():
    tmp = Path(tempfile.mkdtemp(prefix="ex1_"))
    _write(tmp, "dot", {"id": "dot", "name": "dot", "image": "dot.png"},
           _red_dot_mask())
    rel = _write(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png",
        "region": None, "threshold": 0.85,
        "exclusions": [{"image": "dot.png",
                        "region": [1.0, 0.0, 0.1667, 0.1667],
                        "threshold": 0.85}]}, _icon_mask())
    ctx = _make_ctx(tmp, _screen_three_blocks(with_dot=True))
    entry = _icon_entry(ctx, rel)
    assert len(entry["exclusions"]) == 1, entry
    assert entry["exclusions"][0]["image"].endswith("icons/dot.png"), \
        entry["exclusions"]
    # 主图标匹配框 (10,10,60,60) 右侧邻域找红点：区域=(10+60,10+0,10,10)
    hit = _exclusions_hit(ctx, entry["exclusions"], 10, 10, 60, 60)
    assert hit is True
    # 第二个图标位置 (120,10) 没有红点
    hit2 = _exclusions_hit(ctx, entry["exclusions"], 120, 10, 60, 60)
    assert hit2 is False
    print("  ✅ 条目 exclusions 解析 + region 相对图标框换算命中/未命中")


# ── 3. 点击器排除筛选 ────────────────────────────────────
def test_clicker_exclusion():
    tmp = Path(tempfile.mkdtemp(prefix="ex2_"))
    _write(tmp, "dot", {"id": "dot", "name": "dot", "image": "dot.png"},
           _red_dot_mask())
    rel = _write(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png",
        "region": None, "threshold": 0.85,
        "exclusions": [{"image": "dot.png",
                        "region": [1.0, 0.0, 0.1667, 0.1667],
                        "threshold": 0.85}]}, _icon_mask())
    # 第一个图标右侧邻域带红点 → 被排除，应点第二个 (120,10)
    ctx = _make_ctx(tmp, _screen_three_blocks(with_dot=True))
    r = _exec_clicker({"params": {"template": rel}}, ctx)
    assert r.goto == "out" and r.status == "ok", r
    assert r.data.get("excluded") == 1, r.data
    px, py = r.data["point"]
    assert 120 <= px <= 179 and 10 <= py <= 69, (px, py)
    assert ctx.executor.clicks[0] == (px, py)
    # 三个图标右侧邻域全带红点 → 全部排除 → not_found
    screen = _screen_three_blocks(with_dot=True)
    screen[10:20, 180:190] = (0, 0, 255)   # 图标2 (120,10) 右侧 (180,10)
    screen[120:130, 70:80] = (0, 0, 255)   # 图标3 (10,120) 右侧 (70,120)
    ctx2 = _make_ctx(tmp, screen)
    r2 = _exec_clicker({"params": {"template": rel}}, ctx2)
    assert r2.goto == "not_found" and r2.data.get("excluded") == 3, r2
    assert not ctx2.executor.clicks
    print("  ✅ 点击器：跳过带红点实例点第二个；全排除 → not_found 不点击")


# ── 4. 场景判定排除 ──────────────────────────────────────
def test_scene_marker_exclusion():
    tmp = Path(tempfile.mkdtemp(prefix="ex3_"))
    _write(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png"}, _icon_mask())
    _write(tmp, "dot", {"id": "dot", "name": "dot",
                        "image": "dot.png"}, _red_dot_mask())
    scene = {"id": "s1", "name": "s1", "signal": "s1", "accuracy": 0,
             "regions": [{
                 "name": "r1", "region": None,
                 "markers": [{
                     "name": "m1", "threshold": 0.85,
                     "templates": [{"template": "visual/t1/icons/icon.png",
                                    "dx": 0, "dy": 0}],
                     "exclusions": [{"image": "visual/t1/icons/dot.png",
                                     "region": [1.0, 0.0,
                                                0.1667, 0.1667],
                                     "threshold": 0.85}],
                 }]}]}
    ctx_hit = _make_ctx(tmp, _screen_three_blocks(with_dot=True))
    h, s = _judge_scene_v2_score(scene, ctx_hit)
    assert h is False, (h, s)
    ctx_ok = _make_ctx(tmp, _screen_three_blocks(with_dot=False))
    h2, _ = _judge_scene_v2_score(scene, ctx_ok)
    assert h2 is True
    print("  ✅ 场景判定：标识带排除特征 → 场景不通过；无排除特征 → 通过")


# ── 5. 排除示教 UI 链路 ──────────────────────────────────
def test_exclusion_teach_flow():
    tmp = Path(tempfile.mkdtemp(prefix="ex4_"))
    rel = _write(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png"}, _icon_mask())
    w = ExclusionTeachWidget(assets_dir=str(tmp),
                             icon_list_provider=lambda: [rel])
    # 免弹窗/免截图：直接进入扫描
    screen = _screen_three_blocks(with_dot=True)
    w._screen = screen
    w._scan(rel, screen)
    assert w._candidates, "候选为空"
    assert w._candidates[0][4] <= w._candidates[-1][4], "候选应升序"
    # 抠图显示 = 第一个候选（最低分；同分时为 y,x 顺序 (10,10)）
    m0 = w._candidates[0]
    assert w._last_image.shape[:2] == (int(m0[3]), int(m0[2])), \
        (w._last_image.shape, m0)
    assert w._next_btn.isEnabled()
    # 标注：红框圈排除特征（相对抠图）+ 蓝框遮罩 → 保存
    w._add_red_region(0.3, 0.3, 0.25, 0.25)
    w._add_blue_marker(0.32, 0.32, 0.18, 0.18)
    key = w._regions[0]["markers"][0]["mask_key"]
    w._canvas.set_active_mask(key)
    H, W = w._last_image.shape[:2]
    w._canvas._masks[key] = np.zeros((H, W), np.uint8)
    w._canvas._masks[key][max(0, H // 2 - 4):H // 2 + 4,
                           max(0, W // 2 - 4):W // 2 + 4] = 255
    w._on_save()
    data = json.loads((tmp / rel).read_text(encoding="utf-8"))
    assert len(data.get("exclusions", [])) == 1, data
    excl = data["exclusions"][0]
    assert excl["region"] == [0.3, 0.3, 0.25, 0.25], excl
    assert (tmp / rel).parent.joinpath(excl["image"]).exists()
    # 再保存一次 → 追加（多次追加机制）
    w._add_red_region(0.5, 0.5, 0.2, 0.2)
    w._add_blue_marker(0.52, 0.52, 0.15, 0.15)
    key2 = w._regions[0]["markers"][0]["mask_key"]
    w._canvas.set_active_mask(key2)
    w._canvas._masks[key2] = np.zeros((H, W), np.uint8)
    w._canvas._masks[key2][H // 2:H // 2 + 6, W // 2:W // 2 + 6] = 255
    w._on_save()
    data2 = json.loads((tmp / rel).read_text(encoding="utf-8"))
    assert len(data2.get("exclusions", [])) == 2, data2
    print("  ✅ 排除示教：低阈值预筛/候选升序/抠图显示/保存追加（多次）")


def test_low_threshold_no_match():
    tmp = Path(tempfile.mkdtemp(prefix="ex5_"))
    rel = _write(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png"}, _icon_mask())
    w = ExclusionTeachWidget(assets_dir=str(tmp),
                             icon_list_provider=lambda: [rel])
    w._screen = np.full((200, 300, 3), 127, np.uint8)  # 无图标
    w._scan(rel, w._screen)
    assert not w._candidates
    assert "无需排除" in w._status.text(), w._status.text()
    assert not w._save_btn.isEnabled()
    print("  ✅ 低阈值无匹配 → 提示无需排除，不启用保存按钮")


# ── 6. 旧任务兼容 ────────────────────────────────────────
def test_old_task_compat():
    tmp = Path(tempfile.mkdtemp(prefix="ex6_"))
    rel = _write(tmp, "icon", {
        "id": "icon", "name": "icon", "image": "icon.png"}, _icon_mask())
    ctx = _make_ctx(tmp, _screen_three_blocks())
    entry = _icon_entry(ctx, rel)
    assert entry["exclusions"] == [], entry
    r = _exec_clicker({"params": {"template": rel}}, ctx)
    assert r.goto == "out" and r.status == "ok", r
    print("  ✅ 旧任务兼容：无 exclusions 字段行为不变")


# ── 7. 切页自动刷新图标下拉（2026-08-16 修复）─────────────
def test_tab_switch_refresh_icons():
    from ui.visual_builder.visual_builder_panel import VisualBuilderPanel
    panel = VisualBuilderPanel(visual_bridge=None)
    ex = panel._exclusion_teach
    idx = panel._right_tabs.indexOf(ex)
    assert idx >= 0
    # 模拟：进入排除示教前，画面示教保存了新素材
    items = {"v": ["a.png"]}
    ex._icon_list_provider = lambda: items["v"]
    # 离开再进入排除示教页 → 下拉自动刷新，无需点截图
    panel._right_tabs.setCurrentIndex(0)
    assert ex._icon_combo.count() == 0   # 尚未刷新（provider 变更后未进入页面）
    panel._right_tabs.setCurrentIndex(idx)
    assert ex._icon_combo.count() == 1, ex._icon_combo.count()
    # 再保存一个新素材 → 再次切页 → 下拉更新
    items["v"] = ["a.png", "b.png"]
    panel._right_tabs.setCurrentIndex(0)
    panel._right_tabs.setCurrentIndex(idx)
    assert ex._icon_combo.count() == 2, ex._icon_combo.count()
    panel.hide()
    panel.deleteLater()
    app.processEvents()
    print("  ✅ 切到排除示教页自动刷新图标下拉（无需先截图）")


if __name__ == "__main__":
    test_entry_parse_and_hit()
    test_clicker_exclusion()
    test_scene_marker_exclusion()
    test_exclusion_teach_flow()
    test_low_threshold_no_match()
    test_old_task_compat()
    test_tab_switch_refresh_icons()
    print("\n🎉 verify_visual_exclusion 全部通过")
