"""验证：素材预览页（2026-08-15，替换失效老素材管理）。

覆盖：
1. 左侧三分之一 = 三种素材选择区（场景/操作/OCR 三 tab）
2. 场景素材：特征 tabs = 蓝框数；排除素材跟随特征 tab 联动
3. 图标素材：整体特征 tab + 条目级 exclusions 列表
4. OCR 素材：OCR特征 tab + 无排除概念提示
5. 属性区：红框位置/阈值/信号/mode/黄框参数展示
6. 📂 打开素材按钮存在
"""
import json
import tempfile
import sys
from pathlib import Path

import numpy as np
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import QApplication, QFormLayout, QLabel

app = QApplication(sys.argv)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.cv_io import imwrite as _cv_imwrite          # noqa: E402
from ui.visual_builder.material_preview import (       # noqa: E402
    MaterialPreviewWidget, ZoomImageView)


def _png(path: Path, size=(30, 40)) -> None:
    img = np.full((size[1], size[0], 3), 180, np.uint8)
    img[5:20, 5:20] = (60, 120, 200)
    _cv_imwrite(str(path), img)


def _form_texts(form: QFormLayout) -> list[tuple[str, str]]:
    out = []
    for i in range(form.rowCount()):
        lab = form.itemAt(i, QFormLayout.LabelRole).widget()
        fld = form.itemAt(i, QFormLayout.FieldRole).widget()
        if not isinstance(fld, QLabel):
            continue  # 复合控件行（触发素材开关等）
        out.append((lab.text() if lab else "",
                    fld.text() if fld else ""))
    return out


def _all_labels(w) -> str:
    texts = []
    for i in range(w._excl_form.count()):
        wid = w._excl_form.itemAt(i).widget()
        if isinstance(wid, QLabel):
            texts.append(wid.text())
        elif wid is not None:
            for c in wid.findChildren(QLabel):
                texts.append(c.text())
    return "\n".join(texts)


def _select(w, kind: str, key: str) -> None:
    lst = w._lists[kind]
    for i in range(lst.count()):
        if lst.item(i).data(Qt.UserRole) == key:
            # 已选中同一行时先取消选择，强制触发切换信号（模拟重新点击）
            if lst.currentRow() == i:
                lst.setCurrentRow(-1)
            lst.setCurrentRow(i)
            return
    raise AssertionError(f"列表无条目 {key}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="matprev_"))
    (tmp / "icons").mkdir(parents=True)
    (tmp / "ocr").mkdir(parents=True)
    (tmp / "scenes").mkdir(parents=True)

    # 图标条目（含 2 个排除素材）
    _png(tmp / "icons" / "icon_1.png")
    _png(tmp / "icons" / "excl_1.png", (16, 16))
    _png(tmp / "icons" / "excl_2.png", (12, 12))
    icon_entry = {
        "id": "返回按钮", "name": "返回按钮", "image": "icon_1.png",
        "region": [0.1, 0.2, 0.05, 0.05], "threshold": 0.85,
        "mode": "region_click", "created_at": 1700000000000,
        "exclusions": [
            {"image": "excl_1.png", "region": [0.3, 0.3, 0.2, 0.2],
             "threshold": 0.85},
            {"image": "excl_2.png", "region": [0.6, 0.6, 0.15, 0.15],
             "threshold": 0.9},
        ],
    }
    (tmp / "icons" / "返回按钮.json").write_text(
        json.dumps(icon_entry, ensure_ascii=False), encoding="utf-8")

    # OCR 条目
    _png(tmp / "ocr" / "ocr_1.png")
    (tmp / "ocr" / "确认文字.json").write_text(json.dumps({
        "id": "确认文字", "name": "确认文字", "image": "ocr_1.png",
        "region": [0.5, 0.5, 0.2, 0.2], "threshold": 0.85,
        "ocr_box": [5, 5, 40, 20]}, ensure_ascii=False), encoding="utf-8")

    # 场景（2 个蓝框；蓝框A 有 1 个排除素材）
    _png(tmp / "scenes" / "tpl_a.png")
    _png(tmp / "scenes" / "tpl_b.png")
    _png(tmp / "scenes" / "excl_a.png", (14, 14))
    scene = {
        "id": "主界面", "name": "主界面", "signal": "主界面",
        "accuracy": 80,
        "regions": [{
            "name": "红框1", "region": [0.0, 0.0, 1.0, 1.0],
            "markers": [
                {"name": "蓝框A", "region": [0.1, 0.1, 0.2, 0.2],
                 "threshold": 0.85,
                 "templates": [{"template": "scenes/tpl_a.png",
                                "dx": 0, "dy": 0}],
                 "exclusions": [{"image": "excl_a.png",
                                 "region": [0.2, 0.2, 0.1, 0.1],
                                 "threshold": 0.9}]},
                {"name": "蓝框B", "region": [0.5, 0.5, 0.2, 0.2],
                 "threshold": 0.85,
                 "templates": [{"template": "scenes/tpl_b.png"}]},
            ]}]}

    icon_list = ["icons/返回按钮.json"]
    ocr_list = ["ocr/确认文字.json"]
    w = MaterialPreviewWidget(
        assets_dir=str(tmp),
        scenes_provider=lambda: [{"id": "主界面", "name": "主界面"}],
        elements_provider=lambda: list(icon_list),
        ocr_provider=lambda: list(ocr_list),
        scene_loader=lambda sid: scene if sid == "主界面" else None,
    )

    # 1. 左侧三种素材选择区
    assert w._left_tabs.count() == 3, w._left_tabs.count()
    assert w._left_tabs.tabText(0) == "🧭 场景识别素材"
    assert w._left_tabs.tabText(1) == "🎯 操作识别素材"
    assert w._left_tabs.tabText(2) == "🔤 OCR识别素材"
    assert w._open_btn.text() == "📂 打开素材"
    print("  ✅ 左侧三分之一：三种素材选择区 + 打开素材按钮")

    # 2. 场景素材（自动选中第一个非空 tab=场景）
    assert w._cur_kind == "scene", w._cur_kind
    assert w._feature_tabs.count() == 2, w._feature_tabs.count()
    assert w._feature_tabs.tabText(0) == "蓝框A"
    assert w._feature_tabs.tabText(1) == "蓝框B"
    texts = _form_texts(w._props_form)
    props = dict(texts)
    assert props.get("类型:") == "场景识别素材", texts
    assert props.get("红框数:") == "1", texts
    assert props.get("蓝框数:") == "2", texts
    # 触发素材开关（信号行已换成可编辑开关+信号名，2026-08-16）
    assert w._trigger_check.isChecked()
    assert w._trigger_signal_edit.text() == "主界面"
    # 排除素材跟随特征 tab：蓝框A → 1 个排除素材
    w._feature_tabs.setCurrentIndex(0)
    labels0 = _all_labels(w)
    assert "excl_a.png" in labels0, labels0
    assert "蓝框「蓝框A」" in labels0, labels0
    w._feature_tabs.setCurrentIndex(1)
    labels1 = _all_labels(w)
    assert "excl_a.png" not in labels1, labels1
    assert "暂无排除素材" in labels1, labels1
    print("  ✅ 场景素材：特征 tabs=蓝框数，排除素材随特征 tab 联动")

    # 3. 图标素材
    _select(w, "element", "icons/返回按钮.json")
    assert w._cur_kind == "element"
    assert w._feature_tabs.count() == 1
    assert w._feature_tabs.tabText(0) == "整体特征"
    texts = _form_texts(w._props_form)
    props = dict(texts)
    assert props.get("类型:") == "操作识别素材", texts
    assert "x=0.100" in props.get("红框位置:", ""), texts
    assert props.get("点击方式:") == "随机点击素材", texts
    assert props.get("排除素材数:") == "2", texts
    labels = _all_labels(w)
    assert "excl_1.png" in labels and "excl_2.png" in labels, labels
    assert "2 个" in labels, labels
    assert "0.300" in labels and "0.150" in labels, labels
    print("  ✅ 图标素材：整体特征 + 红框位置/mode + 2 个排除素材列表")

    # 4. OCR 素材
    _select(w, "ocr", "ocr/确认文字.json")
    assert w._cur_kind == "ocr"
    assert w._feature_tabs.count() == 1
    assert w._feature_tabs.tabText(0) == "OCR特征"
    texts = _form_texts(w._props_form)
    props = dict(texts)
    assert props.get("类型:") == "OCR识别素材", texts
    assert "偏移(5,5) 尺寸 40×20px" in props.get("文字框(黄框):", ""), texts
    labels = _all_labels(w)
    assert "暂无排除素材概念" in labels, labels
    print("  ✅ OCR素材：OCR特征 tab + 黄框偏移参数 + 无排除概念提示")

    # 5. 场景蓝框特征页文本（红框名/蓝框位置/阈值）
    _select(w, "scene", "主界面")
    for i in range(w._feature_tabs.count()):
        page = w._feature_tabs.widget(i)
        page_text = "\n".join(c.text() for c in page.findChildren(QLabel))
        if w._feature_tabs.tabText(i) == "蓝框A":
            assert "所属红框: 红框1" in page_text, page_text
            assert "蓝框位置" in page_text, page_text
            assert "排除素材: 1 个" in page_text, page_text
    print("  ✅ 特征页文本：所属红框/蓝框位置/排除素材数")

    # 6. 素材缺失 → 空态提示「加载失败」
    w._show_material("scene", "不存在的场景")
    assert w._stack.currentIndex() == 0, w._stack.currentIndex()
    assert "加载失败" in w._empty_label.text()
    print("  ✅ 素材缺失 → 空态提示「加载失败」")

    # 6.5 触发素材开关（2026-08-16）：场景属性区可更改是否为触发素材
    saved_scenes: list = []
    w._scene_save_callback = lambda scene: saved_scenes.append(scene) or True
    w._notify = lambda title, text: None
    _select(w, "scene", "主界面")
    assert w._trigger_check.isChecked(), "signal=主界面 → 开关应勾选"
    assert w._trigger_signal_edit.text() == "主界面"
    assert w._trigger_signal_edit.isEnabled()
    # 修改信号名并保存 → 回调收到更新后的场景
    w._trigger_signal_edit.setText("庭院")
    w._on_save_trigger()
    assert saved_scenes and saved_scenes[-1].get("signal") == "庭院", \
        saved_scenes
    # 取消开关 → 保存 signal=""（非触发素材）
    _select(w, "scene", "主界面")
    w._trigger_check.setChecked(False)
    assert not w._trigger_signal_edit.isEnabled()
    w._on_save_trigger()
    assert saved_scenes[-1].get("signal") == "", saved_scenes[-1]
    print("  ✅ 触发素材开关：勾选/信号名编辑/取消（signal="")保存生效")

    # 7. alpha 合成：预览必须呈现遮罩形状（遮罩外暗底、遮罩内原图）
    rgba = np.zeros((30, 40, 4), np.uint8)
    rgba[:, :, :3] = (200, 60, 120)      # 整块蓝框区域 BGR 原色
    rgba[10:20, 10:30, 3] = 255          # 中心 20×10 才是遮罩
    _cv_imwrite(str(tmp / "icons" / "masked.png"), rgba)
    img = w._read_rgb(tmp / "icons" / "masked.png")
    assert img is not None and img.shape == (30, 40, 3)
    assert tuple(img[5, 5]) == (46, 50, 58), img[5, 5]          # 遮罩外→暗底
    assert tuple(img[15, 20]) == (200, 60, 120), img[15, 20]    # 遮罩内→原色
    print("  ✅ alpha 合成：遮罩外暗底、遮罩内原图（预览呈现遮罩形状）")

    # 8. 滚轮缩放：特征图/整体预览图均为 ZoomImageView，可缩放+复位
    _select(w, "element", "icons/返回按钮.json")
    view = w._feature_tabs.widget(0).findChild(ZoomImageView)
    assert view is not None, "特征页缺少可缩放图片视图"
    s0 = view.scale()
    view.zoom_at(QPoint(10, 10), 0.5)
    assert view.scale() < s0, (view.scale(), s0)
    size_shrunk = view._label.pixmap().size()
    view.zoom_at(QPoint(10, 10), 2.0)
    assert abs(view.scale() - s0) < 1e-9, (view.scale(), s0)
    assert view._label.pixmap().size() != size_shrunk
    view.reset_zoom()
    assert abs(view.scale() - view._fit_scale) < 1e-9
    # 顶部整体预览图同样可缩放
    o0 = w._overview_view.scale()
    w._overview_view.zoom_at(QPoint(5, 5), 0.5)
    assert w._overview_view.scale() < o0
    w._overview_view.zoom_at(QPoint(5, 5), 2.0)
    w._overview_view.reset_zoom()
    assert abs(w._overview_view.scale() - w._overview_view._fit_scale) < 1e-9
    # 排除素材缩略图也可缩放
    _select(w, "element", "icons/返回按钮.json")
    excl_views = w._excl_page.findChildren(ZoomImageView)
    assert excl_views, "排除素材缩略图缺少可缩放视图"
    e0 = excl_views[0].scale()
    excl_views[0].zoom_at(QPoint(4, 4), 2.0)
    assert excl_views[0].scale() > e0
    excl_views[0].reset_zoom()
    print("  ✅ 滚轮缩放：特征图/整体预览/排除缩略图均支持缩放与双击复位")

    # 9. 删除功能：图标/OCR 删条目文件（json+特征图+排除图）；场景走删除回调
    notes: list[tuple[str, str]] = []
    calls: list[tuple[str, str]] = []
    w._notify = lambda title, text: notes.append((title, text))
    w._confirm_delete = lambda kind, key, name: True

    def del_cb(kind, key, data):
        calls.append((kind, key))
        # 模拟扫描 provider：删除后列表不再返回该项
        if kind == "element" and key in icon_list:
            icon_list.remove(key)
        elif kind == "ocr" and key in ocr_list:
            ocr_list.remove(key)
        return True, ""

    w._delete_callback = del_cb
    # 图标：删除条目 json + 特征图 + 2 个排除素材图，列表清空
    _select(w, "element", "icons/返回按钮.json")
    w._on_delete()
    assert not (tmp / "icons" / "返回按钮.json").exists()
    assert not (tmp / "icons" / "icon_1.png").exists()
    assert not (tmp / "icons" / "excl_1.png").exists()
    assert not (tmp / "icons" / "excl_2.png").exists()
    assert w._lists["element"].count() == 0
    assert calls and calls[-1] == ("element", "icons/返回按钮.json"), calls
    assert notes and notes[-1] == ("删除完成", "素材「返回按钮」已删除"), notes
    # OCR：删除条目 json + 特征图
    _select(w, "ocr", "ocr/确认文字.json")
    w._on_delete()
    assert not (tmp / "ocr" / "确认文字.json").exists()
    assert not (tmp / "ocr" / "ocr_1.png").exists()
    assert w._lists["ocr"].count() == 0
    # 场景：成功走回调
    _select(w, "scene", "主界面")
    w._on_delete()
    assert calls[-1] == ("scene", "主界面"), calls
    # 场景：回调失败 → 删除失败提示
    w._delete_callback = lambda k, key, data: (False, "素材库删除失败")
    _select(w, "scene", "主界面")
    w._on_delete()
    assert notes[-1][0] == "删除失败", notes
    assert "素材库删除失败" in notes[-1][1], notes
    print("  ✅ 删除：图标/OCR 删条目文件；场景走回调（失败提示）")

    print("\n🎉 verify_material_viewer 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
