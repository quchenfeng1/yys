"""验证：示教画布滚轮缩放/中键平移/双击复位 + 橡皮擦（2026-08-15）。

覆盖：
1. 滚轮缩放：fit 为基准放大，锚点（鼠标下图像点）保持不变
2. 缩放 clamp（1×~8×）；缩小到 1× 后不再变
3. reset_view 复位；中键拖动平移
4. 橡皮：擦除画笔遮罩；画笔/橡皮互斥
5. 画面示教 + 排除示教的 🧹 橡皮按钮与互斥逻辑
"""
import tempfile
import sys
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui.visual_builder.screen_canvas import ScreenCanvas   # noqa: E402
from ui.visual_builder.teach_console import TeachConsole   # noqa: E402
from ui.visual_builder.exclusion_teach import (            # noqa: E402
    ExclusionTeachWidget)


def _img(w=300, h=200):
    return np.full((h, w, 3), 127, dtype=np.uint8)


def main() -> int:
    c = ScreenCanvas()
    c.resize(400, 300)
    c.set_image(_img())
    r0 = c._image_rect()
    assert r0.width() > 0 and r0.height() > 0
    assert abs(r0.height() - 200 * (400 / 300)) < 1.5  # fit: 按宽 400

    # 1. 放大：锚点（鼠标下图像相对坐标）保持不变
    pos = QPointF(200, 100)
    fx = (pos.x() - r0.x()) / r0.width()
    fy = (pos.y() - r0.y()) / r0.height()
    c._zoom_at(pos, 1.15)
    assert c.zoom() > 1.0
    r1 = c._image_rect()
    assert r1.width() > r0.width()
    fx1 = (pos.x() - r1.x()) / r1.width()
    fy1 = (pos.y() - r1.y()) / r1.height()
    assert abs(fx1 - fx) < 1e-6 and abs(fy1 - fy) < 1e-6, (fx, fy, fx1, fy1)
    # 放大后同一图像像素的显示位置变大 → 缩放后映射回原像素
    p_img = c._to_img_pos(pos)
    assert p_img == (int(fx * 300), int(fy * 200)), (p_img, fx, fy)
    print("  ✅ 滚轮缩放：锚点保持 + 图像坐标映射正确")

    # 2. 连续缩小回 1×；1× 时继续缩小不生效（clamp）
    for _ in range(10):
        c._zoom_at(QPointF(50, 50), 1.0 / 1.15)
    assert abs(c.zoom() - 1.0) < 1e-9, c.zoom()
    c._zoom_at(QPointF(50, 50), 1.0 / 1.15)
    assert abs(c.zoom() - 1.0) < 1e-9
    r_reset = c._image_rect()
    assert abs(r_reset.width() - r0.width()) < 1e-9
    print("  ✅ 缩放范围 clamp 1×~8×，缩小回 1×")

    # 3. 中键拖动平移 + 复位
    c.reset_view()
    c._zoom_at(QPointF(200, 150), 2.0)
    px0, py0 = c._pan_x, c._pan_y
    c._pan_anchor = QPointF(100, 100)
    c._pan_by(QPointF(140, 120))
    assert abs((c._pan_x - px0) - 40.0) < 1e-9
    assert abs((c._pan_y - py0) - 20.0) < 1e-9
    c.reset_view()
    assert abs(c.zoom() - 1.0) < 1e-9
    assert abs(c._pan_x) < 1e-9 and abs(c._pan_y) < 1e-9
    print("  ✅ 中键拖动平移 + 双击复位")

    # 4. 橡皮：先涂后擦
    c.set_image(_img())
    c.set_brush_size(8)
    c.set_brush_mode(True)
    c._paint_at(QPointF(150, 100))   # 涂色
    mask = c.get_mask()
    assert mask is not None and mask.any(), "画笔应涂出遮罩"
    c.set_erase_mode(True)
    assert c._erase_mode and not c._brush_mode, "橡皮/画笔互斥"
    # 在涂色区域反复擦几遍，确保擦干净
    for _ in range(6):
        c._paint_at(QPointF(150, 100))
    mask2 = c.get_mask()
    assert mask2 is not None and not mask2.any(), "橡皮应擦除遮罩"
    # 互斥：开画笔 → 橡皮自动关
    c.set_brush_mode(True)
    assert c._brush_mode and not c._erase_mode
    print("  ✅ 橡皮擦除遮罩 + 画笔/橡皮互斥")

    # 4.5 canvas 层三模式互斥（画笔/橡皮/拖动）
    c.set_pan_mode(True)
    assert c._pan_mode and not c._brush_mode and not c._erase_mode
    c.set_brush_mode(True)
    assert c._brush_mode and not c._pan_mode and not c._erase_mode
    c.set_erase_mode(True)
    assert c._erase_mode and not c._pan_mode and not c._brush_mode
    c.set_pan_mode(False)
    c.set_erase_mode(False)
    print("  ✅ 画笔/橡皮/拖动三模式互斥")

    # 4.6 笔尖指示圆（PS 风格）：半径 = 笔尖像素 × 显示缩放
    c.set_image(_img())   # 300×200，canvas 400×300 → fit scale=4/3
    c.set_brush_size(12)
    assert c._brush_radius_px() is None, "未进入画笔模式不应有笔尖圆"
    c.set_brush_mode(True)
    r_b = c._brush_radius_px()
    assert r_b is not None and abs(r_b - 12 * (400 / 300)) < 1e-6, r_b
    c._zoom_at(QPointF(200, 150), 2.0)   # 放大 2× → 笔尖圆同步变大
    r_b2 = c._brush_radius_px()
    assert abs(r_b2 - r_b * 2.0) < 1e-6, (r_b2, r_b)
    # 橡皮模式同样有笔尖圆；退出模式后消失
    c.set_erase_mode(True)
    assert c._brush_radius_px() is not None
    c.set_erase_mode(False)
    assert c._brush_radius_px() is None
    # 鼠标移动更新指示位置；离开清空
    c.set_brush_mode(True)
    c._brush_cursor = QPointF(120, 80)
    assert c._brush_cursor == QPointF(120, 80)
    c.set_brush_mode(False)
    assert c._brush_cursor is None
    c.reset_view()
    print("  ✅ 笔尖指示圆：随模式显示/隐藏，随缩放同步变大")

    # 5. 画面示教橡皮/拖动按钮
    tmp = Path(tempfile.mkdtemp(prefix="eraser_"))
    console = TeachConsole(assets_dir=str(tmp))
    assert console._erase_btn.text() == "🧹 橡皮"
    # 按下状态样式：checkable 工具按钮均有 :checked 高亮
    for _b in (console._red_btn, console._brush_btn, console._erase_btn,
               console._pan_btn):
        assert _b.isCheckable() and ":checked" in _b.styleSheet(), \
            (_b.text(), _b.styleSheet())
    console._on_erase_toggle(True)
    assert console._canvas._erase_mode and not console._canvas._brush_mode
    assert not console._erase_btn.isHidden()
    assert not console._brush_btn.isChecked()
    console._on_brush_toggle(True)
    assert console._canvas._brush_mode and not console._canvas._erase_mode
    assert not console._erase_btn.isChecked()
    # ✋ 拖动按钮：开启 → canvas pan 模式 + 其他工具复位
    assert console._pan_btn.text() == "✋ 拖动"
    console._on_pan_toggle(True)
    assert console._canvas._pan_mode
    assert not console._brush_btn.isChecked()
    assert not console._erase_btn.isChecked()
    assert not console._red_btn.isChecked()
    # 画笔开启 → 拖动按钮复位
    console._on_brush_toggle(True)
    assert not console._pan_btn.isChecked()
    assert not console._canvas._pan_mode
    console._reset_frame_buttons()
    assert not console._canvas._brush_mode and not console._canvas._erase_mode
    assert not console._canvas._pan_mode
    print("  ✅ 画面示教：橡皮/拖动按钮 + 按下高亮样式 + 互斥 + 复位")

    # 6. 排除示教橡皮/拖动按钮
    exw = ExclusionTeachWidget(assets_dir=str(tmp))
    assert exw._erase_btn.text() == "🧹 橡皮"
    assert exw._pan_btn.text() == "✋ 拖动"
    for _b in (exw._red_btn, exw._brush_btn, exw._erase_btn, exw._pan_btn):
        assert _b.isCheckable() and ":checked" in _b.styleSheet()
    exw._on_erase_toggle(True)
    assert exw._canvas._erase_mode and not exw._canvas._brush_mode
    assert not exw._brush_btn.isChecked()
    exw._on_pan_toggle(True)
    assert exw._canvas._pan_mode and not exw._canvas._erase_mode
    assert not exw._brush_btn.isChecked() and not exw._erase_btn.isChecked()
    exw._on_brush_toggle(True)
    assert exw._canvas._brush_mode and not exw._canvas._erase_mode
    assert not exw._erase_btn.isChecked() and not exw._pan_btn.isChecked()
    exw._reset_tool_buttons()
    assert not exw._canvas._brush_mode and not exw._canvas._erase_mode
    assert not exw._canvas._pan_mode
    print("  ✅ 排除示教：橡皮/拖动按钮 + 按下高亮样式 + 互斥 + 复位")

    print("\n🎉 verify_canvas_zoom_erase 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
