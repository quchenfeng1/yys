"""17-可视化构建模块：排除示教页（2026-08-15，独立 Tab）。

为操作识别素材标注排除特征（红点/蓝点等状态标记）。流程：

1. 选择操作识别素材（下拉）→ 📷 截图观察整屏画面（发现需要排除的状态图标）
2. 🔍 截图对比：按点击器逻辑（红框区域找蓝框特征整体）自动定位候选
   ——低阈值预筛（低阈值都不匹配→无需排除）→ 正常阈值候选升序；
   把匹配到的图标按遮罩抠出显示在画布（候选 n/m + 分数）
3. 观察抠图：不是目标图标则 ⏭ 下一处（向匹配度更高方向跳转）
4. 是目标 → 红框圈排除特征位置 + 蓝框遮罩涂特征 → 💾 保存排除素材
   （追加到图标条目 exclusions，可多次：红点一次、蓝点一次）
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from ui.visual_builder.screen_canvas import ScreenCanvas


class ExclusionTeachWidget(QWidget):
    """排除示教页（独立 Tab）"""

    def __init__(self, assets_dir: str = "", capture_callback=None,
                 icon_list_provider=None, parent=None):
        super().__init__(parent)
        self._assets_dir = Path(assets_dir) if assets_dir else Path(".")
        self._capture_callback = capture_callback
        self._icon_list_provider = icon_list_provider

        # 状态
        self._screen = None           # 整屏截图
        self._last_image = None       # 画布当前显示图（抠图或整屏）
        self._entry: dict = {}
        self._candidates: list = []   # [(x,y,w,h,score)] 升序
        self._idx = 0
        self._cur: tuple | None = None
        self._regions: list[dict] = []
        self._current_region: dict | None = None
        self._pending_frame = None    # red/blue
        self._mask_seq = 0
        self._undo_stack: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        self._status = QLabel("排除示教：选素材 → 📷 截图观察屏幕 → "
                              "🔍 截图对比定位图标候选")
        self._status.setStyleSheet("font-weight:bold;")
        root.addWidget(self._status)

        # ── 主工具栏 ──
        bar = QHBoxLayout()
        bar.addWidget(QLabel("操作识别素材:"))
        self._icon_combo = QComboBox()
        self._icon_combo.setMinimumWidth(200)
        self._icon_combo.setToolTip(
            "要标注排除特征的操作识别素材（当前任务素材库）")
        bar.addWidget(self._icon_combo)
        self._capture_btn = QPushButton("📷 截图")
        self._capture_btn.setToolTip("截取模拟器当前屏幕显示在画布（观察图标状态）")
        self._capture_btn.clicked.connect(self._on_capture)
        self._compare_btn = QPushButton("🔍 截图对比")
        self._compare_btn.setToolTip(
            "在截图中按点击器逻辑自动定位匹配图标（匹配度最低优先）并抠出显示")
        self._compare_btn.clicked.connect(self._on_compare)
        self._next_btn = QPushButton("⏭ 下一处")
        self._next_btn.setToolTip("跳到下一个候选（向匹配度更高方向，循环）")
        self._next_btn.clicked.connect(self._on_next)
        self._next_btn.setEnabled(False)
        self._save_btn = QPushButton("💾 保存排除素材")
        self._save_btn.setToolTip("把红框+蓝框遮罩标注保存为该图标的一个排除特征")
        self._save_btn.clicked.connect(self._on_save)
        self._save_btn.setEnabled(False)
        for b in (self._capture_btn, self._compare_btn, self._next_btn,
                  self._save_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        root.addLayout(bar)

        # ── 标注工具栏 ──
        tools = QHBoxLayout()
        self._red_btn = QPushButton("＋红框(排除区域)")
        self._red_btn.setCheckable(True)
        self._red_btn.toggled.connect(self._on_red_toggle)
        self._blue_btn = QPushButton("＋蓝框(特征标识)")
        self._blue_btn.setCheckable(True)
        self._blue_btn.toggled.connect(self._on_blue_toggle)
        self._brush_btn = QPushButton("🖌 画笔")
        self._brush_btn.setCheckable(True)
        self._brush_btn.toggled.connect(self._on_brush_toggle)
        self._erase_btn = QPushButton("🧹 橡皮")
        self._erase_btn.setCheckable(True)
        self._erase_btn.setToolTip("擦除画笔涂出的遮罩")
        self._erase_btn.toggled.connect(self._on_erase_toggle)
        self._pan_btn = QPushButton("✋ 拖动")
        self._pan_btn.setCheckable(True)
        self._pan_btn.setToolTip("按下后按住左键拖动平移画面")
        self._pan_btn.toggled.connect(self._on_pan_toggle)
        # 按下状态高亮（选中工具视觉反馈）
        _TOOL_CHECKED_QSS = (
            "QPushButton:checked {"
            " background-color:#1e6fd9; color:#ffffff;"
            " border:1px solid #0f5bb5; font-weight:bold; }")
        for _tb in (self._red_btn, self._blue_btn, self._brush_btn,
                    self._erase_btn, self._pan_btn):
            _tb.setStyleSheet(_TOOL_CHECKED_QSS)
        self._brush_size_spin = QSpinBox()
        self._brush_size_spin.setRange(1, 60)
        self._brush_size_spin.setValue(10)
        self._brush_size_spin.valueChanged.connect(
            lambda v: self._canvas.set_brush_size(v))
        self._undo_btn = QPushButton("↩ 撤回")
        self._undo_btn.clicked.connect(self._undo)
        for b in (self._red_btn, self._blue_btn, self._brush_btn,
                  self._erase_btn, self._pan_btn, self._brush_size_spin,
                  self._undo_btn):
            tools.addWidget(b)
        tools.addStretch(1)
        root.addLayout(tools)

        self._hint = QLabel("红框=排除特征搜索位置（相对图标）；"
                            "蓝框+遮罩=排除特征本身（红点/蓝点）；"
                            "✋ 拖动或按住中键平移画面 · 滚轮缩放 · 双击画面复位")
        self._hint.setStyleSheet("color:#8a94a6;font-size:11px;")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        self._canvas = ScreenCanvas()
        self._canvas.region_selected.connect(self._on_canvas_region)
        self._canvas.box_deleted.connect(self._on_box_deleted)
        self._canvas.state_mutating.connect(self._snapshot)
        root.addWidget(self._canvas, 1)

        self._refresh_icons()

    # ── 素材下拉 ─────────────────────────────────────────
    def refresh_icons(self) -> None:
        """外部触发刷新图标下拉（2026-08-16：切到排除示教页时调用，
        新保存的操作识别素材立即可选，无需先点截图）"""
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        cur = self._icon_combo.currentData()
        self._icon_combo.blockSignals(True)
        self._icon_combo.clear()
        items: list[str] = []
        if self._icon_list_provider is not None:
            try:
                items = list(self._icon_list_provider() or [])
            except Exception:
                items = []
        for rel in items:
            self._icon_combo.addItem(Path(rel).stem, rel)
        self._icon_combo.blockSignals(False)
        if cur and self._icon_combo.findData(cur) >= 0:
            self._icon_combo.setCurrentIndex(self._icon_combo.findData(cur))

    def current_icon_rel(self) -> str:
        return self._icon_combo.currentData() or ""

    # ── 截图 / 截图对比 / 下一处 / 保存 ──────────────────
    def _on_capture(self) -> None:
        """📷 截取模拟器当前屏幕显示（用户观察图标状态）"""
        self._refresh_icons()
        if self._capture_callback is None:
            self._status.setText("⚠ 未配置截图接口")
            return
        try:
            img = self._capture_callback()
        except Exception as e:
            img = None
            self._status.setText(f"⚠ 截图失败: {e}")
        if img is None:
            self._status.setText("⚠ 截图失败：请检查模拟器连接")
            return
        self._screen = img
        self._show_image(img)
        self._status.setText("✔ 已截图；观察画面找到需要排除的状态图标后点"
                             "【🔍 截图对比】自动定位")

    def _on_compare(self) -> None:
        """🔍 截图对比：自动定位候选并抠出第一个（匹配度最低优先）"""
        self._refresh_icons()
        rel = self.current_icon_rel()
        if not rel:
            self._hint.setText("请先选择操作识别素材")
            return
        if self._screen is None:
            self._hint.setText("请先点【📷 截图】")
            return
        self._scan(rel, self._screen)

    def _scan(self, rel: str, img) -> None:
        from visual.nodes import (GraphContext, _icon_entry,
                                  _match_all_templates, _match_template_score)
        H, W = img.shape[:2]
        ctx = GraphContext(task={}, assets_dir=str(self._assets_dir),
                           screen_size=(W, H))
        ctx._screenshot = img
        self._entry = _icon_entry(ctx, rel)
        image = self._entry.get("image") or rel
        region = self._entry.get("region") or None
        # 低阈值预筛：低阈值都匹配不到 → 正常高阈值必然不通过，无需排除
        probe = _match_template_score(ctx, image, 0.5, region=region)
        if probe is None:
            self._candidates = []
            self._cur = None
            self._show_image(img)
            self._status.setText("🔍 低阈值均未匹配：该素材正常识别时必然不通过，"
                                 "无需排除")
            self._next_btn.setEnabled(False)
            self._save_btn.setEnabled(False)
            return
        cands = _match_all_templates(ctx, image, 0.85, region=region)
        if not cands:
            self._candidates = []
            self._cur = None
            self._show_image(img)
            self._status.setText("🔍 低阈值有匹配但正常阈值无实例，无需排除")
            self._next_btn.setEnabled(False)
            self._save_btn.setEnabled(False)
            return
        cands.sort(key=lambda m: m[4])   # 匹配度最低优先（先看最可疑的）
        self._candidates = cands
        self._idx = 0
        self._next_btn.setEnabled(True)
        self._save_btn.setEnabled(True)
        self._show(0)

    def _show(self, idx: int) -> None:
        """显示第 idx 个候选的抠图（循环），清空标注供新标注"""
        if not self._candidates:
            return
        idx = idx % len(self._candidates)
        self._idx = idx
        m = self._candidates[idx]
        self._cur = tuple(m)
        x, y, w, h = int(m[0]), int(m[1]), int(m[2]), int(m[3])
        crop = self._screen[y:y + h, x:x + w].copy()
        self._show_image(crop)
        self._status.setText(
            f"🔍 候选 {idx + 1}/{len(self._candidates)}"
            f"（score={m[4]:.2f}）——这个图标需要排除就：红框圈排除特征位置 → "
            f"蓝框+遮罩涂特征 → 【💾 保存排除素材】；不是目标就【⏭ 下一处】")

    def _on_next(self) -> None:
        self._show(self._idx + 1)

    def _on_save(self) -> None:
        """把当前抠图上的红框+蓝框遮罩标注保存为该图标的一个排除素材（追加）"""
        import json
        import time
        from core.cv_io import imwrite as _cv_imwrite
        rel = self.current_icon_rel()
        if not self._cur or not rel:
            self._hint.setText("请先【📷 截图】→【🔍 截图对比】定位到候选")
            return
        if not self._regions:
            self._hint.setText("请先用红框圈出排除特征所在位置")
            return
        region = self._regions[0]
        merged = None
        for marker in region.get("markers", []):
            m = self._canvas.get_mask(marker.get("mask_key", ""))
            if m is not None and m.any():
                merged = m.copy() if merged is None else np.maximum(merged, m)
        if merged is None:
            self._hint.setText("红框内没有遮罩：先用蓝框+🖌画笔涂出排除特征（红点/蓝点）")
            return
        img = self._last_image
        if img is None:
            self._hint.setText("请先【📷 截图】→【🔍 截图对比】")
            return
        ys, xs = np.nonzero(merged)
        H, W = img.shape[:2]
        x0, x1 = max(0, int(xs.min())), min(W - 1, int(xs.max()))
        y0, y1 = max(0, int(ys.min())), min(H - 1, int(ys.max()))
        if x1 < x0 or y1 < y0:
            self._hint.setText("排除特征遮罩裁剪失败")
            return
        crop = img[y0:y1 + 1, x0:x1 + 1]
        crop_mask = merged[y0:y1 + 1, x0:x1 + 1]
        rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
        rgba[:, :, 3] = crop_mask
        # 排除 PNG 存条目 json 同目录（icons/）
        icon_dir = (self._assets_dir / rel).parent
        icon_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        png_name = f"excl_{ts}.png"
        if not _cv_imwrite(str(icon_dir / png_name), rgba):
            self._hint.setText("排除素材保存失败（图片写入错误）")
            return
        excl = {"image": png_name,
                "region": [round(float(v), 4)
                           for v in region.get("region", [])],
                "threshold": 0.85}
        icon_path = self._assets_dir / rel
        try:
            data = json.loads(icon_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data.setdefault("exclusions", []).append(excl)
        try:
            icon_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except Exception as e:
            self._hint.setText(f"排除素材写入条目失败: {e}")
            return
        # 保留当前抠图、清空标注：可继续涂下一个特征或跳下一处
        self._show_image(self._last_image)
        self._status.setText(
            f"✔ 排除素材已追加到「{Path(rel).stem}」"
            f"（共 {len(data['exclusions'])} 个）；可继续涂下一个特征或"
            f"【⏭ 下一处】")

    # ── 画面显示 ─────────────────────────────────────────
    def _show_image(self, img) -> None:
        self._last_image = img
        self._canvas.set_image(img)
        self._canvas.clear_overlays()
        self._canvas.clear_all_masks()
        self._regions = []
        self._current_region = None
        self._pending_frame = None
        self._mask_seq = 0
        self._reset_tool_buttons()

    # ── 框选 / 画笔（与画面示教同款）────────────────────
    def _reset_tool_buttons(self) -> None:
        self._pending_frame = None
        for b in (self._red_btn, self._blue_btn):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        for b in (self._brush_btn, self._erase_btn, self._pan_btn):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self._canvas.set_region_mode(False)
        self._canvas.set_brush_mode(False)
        self._canvas.set_erase_mode(False)
        self._canvas.set_pan_mode(False)

    def _begin_frame(self, kind: str) -> None:
        self._pending_frame = kind
        self._canvas.set_region_mode(True)
        self._canvas.set_brush_mode(False)
        self._canvas.set_erase_mode(False)
        self._canvas.set_pan_mode(False)
        for b in (self._brush_btn, self._erase_btn, self._pan_btn):
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)

    def _on_red_toggle(self, checked: bool) -> None:
        if checked:
            self._begin_frame("red")

    def _on_blue_toggle(self, checked: bool) -> None:
        if checked:
            if not self._current_region:
                self._blue_btn.setChecked(False)
                self._hint.setText("请先点【＋红框】框一个排除搜索区域，再框蓝框")
                return
            self._begin_frame("blue")

    def _on_brush_toggle(self, checked: bool) -> None:
        self._canvas.set_brush_mode(checked)
        if checked:
            for b in (self._red_btn, self._blue_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            for b in (self._erase_btn, self._pan_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            self._pending_frame = None

    def _on_erase_toggle(self, checked: bool) -> None:
        """🧹 橡皮：擦除当前遮罩上已涂的像素"""
        self._canvas.set_erase_mode(checked)
        if checked:
            for b in (self._red_btn, self._blue_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            for b in (self._brush_btn, self._pan_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            self._pending_frame = None

    def _on_pan_toggle(self, checked: bool) -> None:
        """✋ 拖动：按住左键拖动平移画面"""
        self._canvas.set_pan_mode(checked)
        if checked:
            for b in (self._red_btn, self._blue_btn, self._brush_btn,
                      self._erase_btn):
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            self._pending_frame = None

    def _on_canvas_region(self, x: float, y: float, w: float, h: float) -> None:
        if not self._canvas.has_image():
            return
        kind = self._pending_frame
        self._pending_frame = None
        self._reset_tool_buttons()
        if kind == "red":
            self._add_red_region(x, y, w, h)
        elif kind == "blue":
            self._add_blue_marker(x, y, w, h)

    def _add_red_region(self, x, y, w, h) -> None:
        self._snapshot()
        default = f"红{len(self._regions) + 1}区"
        region = {"name": default, "region": [x, y, w, h], "markers": []}
        region["box_id"] = self._canvas.add_region(x, y, w, h, default, ref=region)
        self._regions.append(region)
        self._current_region = region
        self._status.setText(f"✔ 红框「{default}」已添加；可继续＋蓝框")

    def _add_blue_marker(self, x, y, w, h) -> None:
        region = self._current_region
        if region is None:
            self._hint.setText("请先点【＋红框】框一个排除搜索区域，再框蓝框")
            return
        self._snapshot()
        default = f"蓝{len(region['markers']) + 1}区"
        self._mask_seq += 1
        key = f"m{self._mask_seq}"
        marker = {"name": default, "region": [x, y, w, h], "mask_key": key}
        marker["box_id"] = self._canvas.add_marker(x, y, w, h, default, ref=marker)
        region["markers"].append(marker)
        self._canvas.set_active_mask(key)
        self._status.setText(f"✔ 蓝框「{default}」已加入；开【🖌 画笔】涂排除特征")

    # ── 撤回 ─────────────────────────────────────────────
    def _snapshot(self) -> None:
        import copy
        self._undo_stack.append({
            "regions": copy.deepcopy(self._regions),
            "masks": {k: np.array(v, copy=True)
                      for k, v in self._canvas.get_all_masks().items()},
            "current_idx": (self._regions.index(self._current_region)
                            if self._current_region in self._regions else -1),
            "mask_seq": self._mask_seq,
        })
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _undo(self) -> None:
        if not self._undo_stack:
            self._hint.setText("没有可撤回的操作")
            return
        s = self._undo_stack.pop()
        self._canvas.clear_overlays()
        self._canvas.set_all_masks(s["masks"])
        self._regions = s["regions"]
        self._mask_seq = s["mask_seq"]
        for r in self._regions:
            r["box_id"] = self._canvas.add_region(*r["region"],
                                                  r.get("name", ""), ref=r)
            for m in r.get("markers", []):
                m["box_id"] = self._canvas.add_marker(*m["region"],
                                                      m.get("name", ""), ref=m)
        self._current_region = (self._regions[s["current_idx"]]
                                if 0 <= s["current_idx"] < len(self._regions)
                                else None)
        self._status.setText("↩ 已撤回上一步")

    def _on_box_deleted(self, box_id: str) -> None:
        self._snapshot()
        for r in self._regions:
            if r.get("box_id") == box_id:
                self._regions.remove(r)
                self._current_region = None
                return
            for m in list(r.get("markers", [])):
                if m.get("box_id") == box_id:
                    r["markers"].remove(m)
                    return
