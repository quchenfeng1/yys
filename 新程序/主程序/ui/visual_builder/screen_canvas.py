"""
17-可视化构建模块：截图画布（P1，ScreenCanvas）。

显示示教截图，接收用户点击（相对坐标 0~1）与框选区域，叠加已记录特征/点击点。
"""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

import numpy as np


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# 框选颜色：红=识别区域 / 蓝=整体标识 / 青=默认
COLOR_RED = QColor(255, 80, 80)
COLOR_BLUE = QColor(80, 140, 255)
COLOR_CYAN = QColor(60, 200, 255)
COLOR_YELLOW = QColor(255, 210, 60)


class ScreenCanvas(QWidget):
    """截图显示 + 点击/框选捕获（相对坐标 0~1）+ 可编辑选框（选中/拖动/拉伸/删除/改名）"""

    point_clicked = pyqtSignal(float, float)          # 相对坐标 (x, y)
    region_selected = pyqtSignal(float, float, float, float)  # (x, y, w, h) 相对
    box_deleted = pyqtSignal(str)          # 删除选框 (box_id)
    box_rename_requested = pyqtSignal(str)  # 请求改名 (box_id)
    box_context_requested = pyqtSignal(str)  # 右键命中选框 (box_id)
    state_mutating = pyqtSignal()            # 状态即将被修改（撤回快照时机）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qimg: QImage | None = None
        self._overlay_points: list[tuple] = []   # (x, y, label)
        self._boxes: list[dict] = []   # 可编辑选框 [{id,kind,name,region,color,ref}]
        self._box_id_seq = 0
        self._selected_box: str | None = None
        self._edit_action = ""          # "" / "move" / "resize"
        self._edit_handle = ""          # resize 手柄 (nw/n/ne/e/se/s/sw/w)
        self._edit_anchor: QPointF | None = None   # 编辑起始点（显示坐标）
        self._edit_orig: list | None = None        # 编辑起始 region [x,y,w,h]
        self._drag_start: QPointF | None = None
        self._drag_rect: tuple | None = None
        self._region_mode = False
        # 遮罩画笔（识图/场景示教用）：多个遮罩按 key 管理（每个蓝框/元素一个）
        self._img_w = 0
        self._img_h = 0
        self._masks: dict[str, np.ndarray] = {}
        self._active_mask = "_"
        self._brush_mode = False
        self._erase_mode = False
        self._pan_mode = False   # ✋ 拖动模式（左键拖动平移，2026-08-15）
        self._brush_size = 15  # 画笔半径（原始图像像素）
        self._brush_cursor: QPointF | None = None  # 笔尖指示圆位置（显示坐标）
        # 视图缩放（2026-08-15）：滚轮缩放 / 中键拖动平移 / 双击复位
        self._zoom = 1.0      # 相对 fit 的倍数（1~8）
        self._pan_x = 0.0     # 平移偏移（显示像素）
        self._pan_y = 0.0
        self._panning = False
        self._pan_anchor: QPointF | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(240, 320)
        self.setStyleSheet("background:#282a30;")

    # ── 图像 ──────────────────────────────────────────────
    def set_image(self, img: np.ndarray | None) -> None:
        """设置显示图像（BGR ndarray）"""
        self._overlay_points.clear()
        self._boxes.clear()
        self._selected_box = None
        self._edit_action = ""
        self._drag_start = None
        self._drag_rect = None
        if img is None:
            self._qimg = None
            self._masks = {}
            self._active_mask = "_"
            self._img_w = self._img_h = 0
        else:
            # BGR→RGB 并保证连续；numpy 2.0 的 .data 是 memoryview，
            # QImage 不接受，必须用 tobytes() 传连续字节流
            rgb = np.ascontiguousarray(img if img.ndim == 2 else img[:, :, ::-1])
            h, w = rgb.shape[:2]
            self._img_w, self._img_h = w, h
            # 遮罩画笔 mask 与原始图像同尺寸
            self._masks = {"_": np.zeros((h, w), dtype=np.uint8)}
            self._active_mask = "_"
            if rgb.ndim == 2:
                self._qimg = QImage(rgb.tobytes(), w, h, w,
                                    QImage.Format_Grayscale8).copy()
            else:
                self._qimg = QImage(rgb.tobytes(), w, h, 3 * w,
                                    QImage.Format_RGB888).copy()
        self.reset_view()
        self.update()

    def has_image(self) -> bool:
        return self._qimg is not None

    # ── 遮罩画笔（示教：涂出要识别的图标形状）──────────
    def set_brush_mode(self, enabled: bool) -> None:
        self._brush_mode = enabled
        if enabled:
            self._erase_mode = False   # 画笔/橡皮互斥
            self._pan_mode = False
            self.unsetCursor()
        if not enabled:
            self._drag_start = None
            self._drag_rect = None
            self._brush_cursor = None
            self.update()

    def set_erase_mode(self, enabled: bool) -> None:
        """橡皮擦模式：擦除当前活动遮罩上已涂的像素（2026-08-15）"""
        self._erase_mode = enabled
        if enabled:
            self._brush_mode = False
            self._pan_mode = False
            self.unsetCursor()
        if not enabled:
            self._drag_start = None
            self._drag_rect = None
            self._brush_cursor = None
            self.update()

    def set_pan_mode(self, enabled: bool) -> None:
        """✋ 拖动模式：左键拖动平移画面（2026-08-15）"""
        self._pan_mode = enabled
        if enabled:
            self._brush_mode = False
            self._erase_mode = False
            self.setCursor(Qt.OpenHandCursor)
        else:
            self._panning = False
            self._pan_anchor = None
            self.unsetCursor()

    # ── 视图缩放/平移（2026-08-15）─────────────────────
    def zoom(self) -> float:
        return self._zoom

    def reset_view(self) -> None:
        """复位：适配整图 + 居中（清平移）"""
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()

    def _zoom_at(self, pos: QPointF, factor: float) -> None:
        """以 pos（控件坐标）为锚点缩放 factor 倍（保持鼠标下图像点不动）"""
        if self._qimg is None:
            return
        new_zoom = max(1.0, min(8.0, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-9:
            return
        r = self._image_rect()
        if r.width() <= 0 or r.height() <= 0:
            return
        fx = (pos.x() - r.x()) / r.width()
        fy = (pos.y() - r.y()) / r.height()
        self._zoom = new_zoom
        r2 = self._image_rect()   # pan 未变时的新矩形
        want_x = pos.x() - fx * r2.width()
        want_y = pos.y() - fy * r2.height()
        self._pan_x += want_x - r2.x()
        self._pan_y += want_y - r2.y()
        self.update()

    def wheelEvent(self, event) -> None:
        if self._qimg is None:
            event.ignore()
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self._zoom_at(QPointF(event.pos()), factor)
        event.accept()

    def _pan_by(self, pos: QPointF) -> None:
        """中键拖动平移"""
        if self._pan_anchor is None:
            return
        self._pan_x += pos.x() - self._pan_anchor.x()
        self._pan_y += pos.y() - self._pan_anchor.y()
        self._pan_anchor = pos
        self.update()

    def set_brush_size(self, radius: int) -> None:
        """画笔半径（原始图像像素）"""
        self._brush_size = max(1, int(radius))
        self.update()

    def _brush_radius_px(self) -> float | None:
        """画笔/橡皮模式下笔尖圆的显示半径（像素）；否则 None。

        笔尖大小 = 原始图像像素 × 当前显示缩放（放大画面时笔尖同步变大）。
        """
        if self._qimg is None or self._img_w <= 0:
            return None
        if not (self._brush_mode or self._erase_mode):
            return None
        r = self._image_rect()
        if r.width() <= 0 or r.height() <= 0:
            return None
        return self._brush_size * r.width() / self._img_w

    # ── 遮罩管理（多遮罩：每个蓝框/元素一个）───────────────
    def set_active_mask(self, key: str) -> None:
        """设置当前涂色目标遮罩（蓝框/元素 key）"""
        self._active_mask = key or "_"

    def active_mask_key(self) -> str:
        return self._active_mask or "_"

    def get_mask(self, key: str | None = None) -> np.ndarray | None:
        """返回遮罩（255=已涂 / 0=未涂），无截图返回 None。
        key=None → 当前活动遮罩；key='*' → 所有遮罩合并。"""
        if key == "*":
            if not self._masks:
                return None
            merged = None
            for m in self._masks.values():
                merged = m.copy() if merged is None else np.maximum(merged, m)
            return merged
        k = key if key is not None else self.active_mask_key()
        return self._masks.get(k)

    def get_all_masks(self) -> dict[str, np.ndarray]:
        """所有遮罩 {key: mask}"""
        return dict(self._masks)

    def set_all_masks(self, masks: dict) -> None:
        """整体恢复遮罩状态（撤回用）：{key: mask} 副本写入"""
        self._masks = {k: np.array(v, copy=True) for k, v in masks.items()}
        self.update()

    def clear_mask(self, key: str | None = None) -> None:
        """清空遮罩：key=None → 全部清空；指定 key → 清该遮罩"""
        if key is None:
            for m in self._masks.values():
                m[:] = 0
        else:
            m = self._masks.get(key)
            if m is not None:
                m[:] = 0
        self.update()

    def clear_all_masks(self) -> None:
        """移除全部遮罩（重置为空）"""
        self._masks = {}
        self.update()

    def _to_img_pos(self, pos: QPointF) -> tuple[int, int] | None:
        """鼠标显示坐标 → 原始图像像素坐标"""
        r = self._image_rect()
        if r.isNull() or r.width() <= 0 or r.height() <= 0:
            return None
        x = int((pos.x() - r.x()) / r.width() * self._img_w)
        y = int((pos.y() - r.y()) / r.height() * self._img_h)
        x = max(0, min(x, self._img_w - 1))
        y = max(0, min(y, self._img_h - 1))
        return (x, y)

    # ── 覆盖层 ────────────────────────────────────────────
    def clear_overlays(self) -> None:
        self._overlay_points.clear()
        self._boxes.clear()
        self._selected_box = None
        self._edit_action = ""
        self.update()

    def add_point(self, x: float, y: float, label: str = "") -> None:
        self._overlay_points.append((_clamp(x), _clamp(y), label))
        self.update()

    def add_rect(self, x: float, y: float, w: float, h: float,
                 label: str = "", color: QColor | None = None,
                 ref: dict | None = None) -> str:
        """叠加一个可编辑框（color 默认青；红=识别区域 / 蓝=整体标识），返回 box_id。

        ref：外部数据对象（如 region/marker dict），move/resize 时同步其 region。
        """
        self._box_id_seq += 1
        box_id = f"box{self._box_id_seq}"
        self._boxes.append({
            "id": box_id,
            "kind": "rect",
            "name": label,
            "region": [_clamp(x), _clamp(y), _clamp(w), _clamp(h)],
            "color": color or COLOR_CYAN,
            "ref": ref,
        })
        self._selected_box = box_id
        self.update()
        return box_id

    def add_region(self, x: float, y: float, w: float, h: float,
                   label: str = "", ref: dict | None = None) -> str:
        """红框：识别区域（搜索范围）"""
        return self.add_rect(x, y, w, h, label, COLOR_RED, ref)

    def add_marker(self, x: float, y: float, w: float, h: float,
                   label: str = "", ref: dict | None = None) -> str:
        """蓝框：整体标识（框内遮罩为一个整体）"""
        return self.add_rect(x, y, w, h, label, COLOR_BLUE, ref)

    def add_yellow(self, x: float, y: float, w: float, h: float,
                   label: str = "", ref: dict | None = None) -> str:
        """黄框：OCR 文字位置（需画在蓝框内，相对蓝框匹配点定位）"""
        return self.add_rect(x, y, w, h, label, COLOR_YELLOW, ref)

    # ── 选框编辑 API ─────────────────────────────────────
    def boxes(self) -> list[dict]:
        return list(self._boxes)

    def box_of(self, box_id: str) -> dict | None:
        for b in self._boxes:
            if b["id"] == box_id:
                return b
        return None

    def rename_box(self, box_id: str, new_name: str) -> None:
        for b in self._boxes:
            if b["id"] == box_id:
                b["name"] = new_name
                if b.get("ref") is not None:
                    b["ref"]["name"] = new_name
                self.update()
                return

    def delete_box(self, box_id: str) -> None:
        self._boxes = [b for b in self._boxes if b["id"] != box_id]
        if self._selected_box == box_id:
            self._selected_box = None
            self._edit_action = ""
        self.update()

    def set_region_mode(self, enabled: bool) -> None:
        """开启框选模式（region_selected 生效）"""
        self._region_mode = enabled
        if not enabled:
            self._drag_start = None
            self._drag_rect = None
            self.update()

    # ── 坐标换算 ──────────────────────────────────────────
    def _image_rect(self) -> QRectF:
        if self._qimg is None:
            return QRectF()
        iw, ih = self._qimg.width(), self._qimg.height()
        w, h = self.width(), self.height()
        if iw <= 0 or ih <= 0 or w <= 0 or h <= 0:
            return QRectF()
        scale = min(w / iw, h / ih) * self._zoom
        dw, dh = iw * scale, ih * scale
        cx, cy = w / 2 + self._pan_x, h / 2 + self._pan_y
        return QRectF(cx - dw / 2, cy - dh / 2, dw, dh)

    def _to_rel(self, pos: QPointF) -> tuple[float, float]:
        r = self._image_rect()
        if r.isNull() or r.width() <= 0 or r.height() <= 0:
            return (0.0, 0.0)
        return (_clamp((pos.x() - r.x()) / r.width()),
                _clamp((pos.y() - r.y()) / r.height()))

    # ── 选框几何辅助 ─────────────────────────────────────
    def _box_display_rect(self, box: dict) -> QRectF | None:
        r = self._image_rect()
        if r.isNull():
            return None
        x, y, w, h = box["region"]
        return QRectF(r.x() + x * r.width(), r.y() + y * r.height(),
                      w * r.width(), h * r.height())

    def _handle_positions(self, box: dict) -> dict[str, QPointF]:
        """8 个拉伸手柄的显示坐标（相对框的四角/四边中点）"""
        br = self._box_display_rect(box)
        if br is None:
            return {}
        x0, y0, x1, y1 = br.left(), br.top(), br.right(), br.bottom()
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        return {
            "nw": QPointF(x0, y0), "n": QPointF(cx, y0), "ne": QPointF(x1, y0),
            "e": QPointF(x1, cy), "se": QPointF(x1, y1), "s": QPointF(cx, y1),
            "sw": QPointF(x0, y1), "w": QPointF(x0, cy),
        }

    def _hit_handle(self, pos: QPointF) -> tuple[str, str] | None:
        """命中选中框的手柄 → (box_id, handle)；未命中 → None"""
        if not self._selected_box:
            return None
        box = self.box_of(self._selected_box)
        if box is None:
            return None
        for name, hp in self._handle_positions(box).items():
            if (abs(pos.x() - hp.x()) <= 6 and abs(pos.y() - hp.y()) <= 6):
                return (box["id"], name)
        return None

    def _hit_box(self, pos: QPointF) -> str | None:
        """命中某框内部 → box_id；从上到下（后添加的优先）"""
        r = self._image_rect()
        if r.isNull():
            return None
        x = (pos.x() - r.x()) / r.width()
        y = (pos.y() - r.y()) / r.height()
        for b in reversed(self._boxes):
            bx, by, bw, bh = b["region"]
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return b["id"]
        return None

    # ── 鼠标事件 ──────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        if self._qimg is None:
            return
        pos = QPointF(event.pos())
        # 0) 中键 或 ✋拖动模式+左键 → 平移画面
        if event.button() == Qt.MiddleButton or \
                (self._pan_mode and event.button() == Qt.LeftButton):
            self._panning = True
            self._pan_anchor = pos
            self.setCursor(Qt.ClosedHandCursor)
            return
        # 1) 画笔/橡皮优先
        if (self._brush_mode or self._erase_mode) \
                and event.button() == Qt.LeftButton:
            self.state_mutating.emit()   # 撤回快照（涂色/擦除前）
            self._paint_at(pos)
            return
        # 2) 框选模式：拖出新框（新建优先，点在已有框上也新建）
        if self._region_mode and event.button() == Qt.LeftButton:
            self._drag_start = pos
            self._drag_rect = None
            return
        # 3) 命中选中框的手柄 → 拉伸
        if event.button() == Qt.LeftButton:
            hit = self._hit_handle(pos)
            if hit is not None:
                bid, handle = hit
                self._selected_box = bid
                self._edit_action = "resize"
                self._edit_handle = handle
                self._edit_anchor = pos
                box = self.box_of(bid)
                self._edit_orig = list(box["region"]) if box else None
                self.state_mutating.emit()   # 撤回快照（拉伸前）
                return
        # 3.5) 右键命中框 → 上下文菜单（保存为图标/OCR素材/点击点等）
        if event.button() == Qt.RightButton:
            bid = self._hit_box(pos)
            if bid is not None:
                self._selected_box = bid
                self.update()
                self.box_context_requested.emit(bid)
                return
        # 4) 命中框内部 → 选中 + 拖动
        if event.button() == Qt.LeftButton:
            bid = self._hit_box(pos)
            if bid is not None:
                self._selected_box = bid
                self._edit_action = "move"
                self._edit_anchor = pos
                box = self.box_of(bid)
                self._edit_orig = list(box["region"]) if box else None
                self.state_mutating.emit()   # 撤回快照（拖动前）
                self.update()
                return
        # 5) 空白处 → 点击点（取消选中）
        if event.button() == Qt.LeftButton:
            self._selected_box = None
            self._edit_action = ""
            self.update()
            x, y = self._to_rel(pos)
            self.point_clicked.emit(x, y)

    def mouseMoveEvent(self, event) -> None:
        pos = QPointF(event.pos())
        # 画笔/橡皮模式下跟踪鼠标 → 显示笔尖指示圆（PS 风格）
        if self._brush_mode or self._erase_mode:
            self._brush_cursor = pos
            self.update()
        if self._panning:
            self._pan_by(pos)
            return
        if (self._brush_mode or self._erase_mode) \
                and event.buttons() & Qt.LeftButton:
            self._paint_at(pos)
            return
        if self._edit_action in ("move", "resize") and event.buttons() & Qt.LeftButton:
            self._apply_edit(pos)
            return
        if self._region_mode and self._drag_start is not None:
            r = self._image_rect()
            p1 = self._drag_start
            p2 = pos
            x = _clamp((min(p1.x(), p2.x()) - r.x()) / r.width())
            y = _clamp((min(p1.y(), p2.y()) - r.y()) / r.height())
            w = _clamp(abs(p2.x() - p1.x()) / r.width())
            h = _clamp(abs(p2.y() - p1.y()) / r.height())
            self._drag_rect = (x, y, w, h)
            self.update()

    def _apply_edit(self, pos: QPointF) -> None:
        """按手柄/拖动更新选中框 region（相对坐标），并同步 ref"""
        box = self.box_of(self._selected_box) if self._selected_box else None
        if box is None or self._edit_orig is None or self._edit_anchor is None:
            return
        r = self._image_rect()
        if r.isNull() or r.width() <= 0 or r.height() <= 0:
            return
        ox, oy, ow, oh = self._edit_orig
        dx = (pos.x() - self._edit_anchor.x()) / r.width()
        dy = (pos.y() - self._edit_anchor.y()) / r.height()
        nx, ny, nw, nh = ox, oy, ow, oh
        if self._edit_action == "move":
            nx = _clamp(ox + dx)
            ny = _clamp(oy + dy)
        else:
            hd = self._edit_handle
            if "w" in hd:
                nx = _clamp(ox + dx)
                nw = max(0.005, ow - dx)
            if "e" in hd:
                nw = max(0.005, ow + dx)
            if "n" in hd:
                ny = _clamp(oy + dy)
                nh = max(0.005, oh - dy)
            if "s" in hd:
                nh = max(0.005, oh + dy)
            # 防止越界
            nx = _clamp(nx)
            ny = _clamp(ny)
            nw = min(nw, 1.0 - nx)
            nh = min(nh, 1.0 - ny)
        box["region"] = [nx, ny, nw, nh]
        if box.get("ref") is not None:
            box["ref"]["region"] = [nx, ny, nw, nh]
        self.update()

    def _paint_at(self, pos: QPointF) -> None:
        """在遮罩上涂/擦一个圆——当前活动遮罩；橡皮擦模式写 0"""
        if self._img_w <= 0 or self._img_h <= 0:
            return
        p = self._to_img_pos(pos)
        if p is None:
            return
        key = self.active_mask_key()
        mask = self._masks.setdefault(key,
                                      np.zeros((self._img_h, self._img_w),
                                               dtype=np.uint8))
        import cv2
        val = 0 if self._erase_mode else 255
        cv2.circle(mask, (p[0], p[1]), self._brush_size, val, -1)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._panning and event.button() in (Qt.MiddleButton,
                                                Qt.LeftButton):
            self._panning = False
            self._pan_anchor = None
            if self._pan_mode:
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.unsetCursor()
            return
        if self._edit_action in ("move", "resize"):
            self._edit_action = ""
            self._edit_handle = ""
            self._edit_anchor = None
            self._edit_orig = None
            return
        if self._region_mode and self._drag_start is not None:
            if self._drag_rect is not None and event.button() == Qt.LeftButton:
                x, y, w, h = self._drag_rect
                if w > 0.02 and h > 0.02:
                    self.region_selected.emit(x, y, w, h)
            self._drag_start = None
            self._drag_rect = None
            self.update()

    def leaveEvent(self, event) -> None:
        """鼠标离开画布 → 隐藏笔尖指示圆"""
        if self._brush_cursor is not None:
            self._brush_cursor = None
            self.update()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """双击选框 → 请求改名；双击空白 → 复位视图（缩放/平移）"""
        if event.button() == Qt.LeftButton:
            bid = self._hit_box(QPointF(event.pos()))
            if bid is not None:
                self._selected_box = bid
                self.box_rename_requested.emit(bid)
                self.update()
                return
            self.reset_view()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        """Delete/Backspace 删除选中选框"""
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self._selected_box:
                self.box_deleted.emit(self._selected_box)
                self.delete_box(self._selected_box)
                return
        super().keyPressEvent(event)

    # ── 绘制 ──────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(40, 42, 48))
        if self._qimg is None:
            p.setPen(QColor(140, 145, 155))
            p.drawText(self.rect(), Qt.AlignCenter, "（无截图 — 示教运行后显示）")
            return
        r = self._image_rect()
        p.drawImage(r, self._qimg)

        # 遮罩画笔叠加（灰色半透明，涂过的区域=要识别的图标；合并所有蓝框遮罩）
        merged_mask = self.get_mask("*")
        if merged_mask is not None and merged_mask.any():
            mh, mw = merged_mask.shape[:2]
            if mw > 0 and mh > 0:
                mask_rgba = np.zeros((mh, mw, 4), dtype=np.uint8)
                mask_rgba[:, :, 0] = 140
                mask_rgba[:, :, 1] = 140
                mask_rgba[:, :, 2] = 140
                mask_rgba[:, :, 3] = (merged_mask * 0.55).astype(np.uint8)
                qmask = QImage(mask_rgba.tobytes(), mw, mh, 4 * mw,
                               QImage.Format_RGBA8888).copy()
                p.drawImage(r, qmask)

        # 覆盖：可编辑选框（红=识别区域 / 蓝=整体标识 / 青=默认）
        for b in self._boxes:
            bx, by, bw, bh = b["region"]
            color = b["color"]
            pen_w = 3 if b["id"] == self._selected_box else 2
            p.setPen(QPen(color, pen_w))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(r.x() + bx * r.width(), r.y() + by * r.height(),
                              bw * r.width(), bh * r.height()))
            if b["name"]:
                p.setPen(color)
                p.drawText(QPointF(r.x() + bx * r.width(),
                                   r.y() + by * r.height() - 3), b["name"])
        # 选中框的拉伸手柄（8 个，PPT 风格）
        if self._selected_box:
            box = self.box_of(self._selected_box)
            if box is not None:
                for hp in self._handle_positions(box).values():
                    p.setBrush(QColor(255, 255, 255))
                    p.setPen(QPen(box["color"], 1))
                    p.drawRect(QRectF(hp.x() - 4, hp.y() - 4, 8, 8))

        # 覆盖：点击点
        for i, (x, y, label) in enumerate(self._overlay_points):
            px = r.x() + x * r.width()
            py = r.y() + y * r.height()
            p.setBrush(QColor(255, 70, 70, 200))
            p.setPen(QPen(QColor(255, 255, 255), 1))
            p.drawEllipse(QPointF(px, py), 7, 7)
            p.setPen(QColor(255, 255, 255))
            p.drawText(QPointF(px + 8, py - 4), label or f"#{i + 1}")

        # 框选进行中
        if self._drag_rect is not None:
            x, y, w, h = self._drag_rect
            p.setPen(QPen(QColor(255, 200, 60), 2, Qt.DashLine))
            p.setBrush(QColor(255, 200, 60, 40))
            p.drawRect(QRectF(r.x() + x * r.width(), r.y() + y * r.height(),
                              w * r.width(), h * r.height()))

        # 画笔/橡皮笔尖指示圆（PS 风格，2026-08-15）：
        # 外圈黑边 + 内圈主体色（画笔白 / 橡皮黄），深浅背景都可见
        if (self._brush_mode or self._erase_mode) and \
                self._brush_cursor is not None:
            rad = self._brush_radius_px()
            if rad is not None and rad > 0:
                cursor_pos = self._brush_cursor
                inner = QColor(255, 200, 60) if self._erase_mode \
                    else QColor(255, 255, 255)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(0, 0, 0, 220), 2))
                p.drawEllipse(cursor_pos, rad, rad)
                p.setPen(QPen(inner, 1))
                p.drawEllipse(cursor_pos, rad - 1.5, rad - 1.5)
