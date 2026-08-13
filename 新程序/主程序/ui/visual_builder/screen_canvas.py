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


class ScreenCanvas(QWidget):
    """截图显示 + 点击/框选捕获（相对坐标 0~1）"""

    point_clicked = pyqtSignal(float, float)          # 相对坐标 (x, y)
    region_selected = pyqtSignal(float, float, float, float)  # (x, y, w, h) 相对

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qimg: QImage | None = None
        self._overlay_points: list[tuple] = []   # (x, y, label)
        self._overlay_rects: list[tuple] = []    # (x, y, w, h, label)
        self._drag_start: QPointF | None = None
        self._drag_rect: tuple | None = None
        self._region_mode = False
        self.setMouseTracking(True)
        self.setMinimumSize(240, 320)
        self.setStyleSheet("background:#282a30;")

    # ── 图像 ──────────────────────────────────────────────
    def set_image(self, img: np.ndarray | None) -> None:
        """设置显示图像（BGR ndarray）"""
        self._overlay_points.clear()
        self._overlay_rects.clear()
        self._drag_start = None
        self._drag_rect = None
        if img is None:
            self._qimg = None
        else:
            rgb = img if img.ndim == 2 else img[:, :, ::-1]  # BGR→RGB
            h, w = rgb.shape[:2]
            if rgb.ndim == 2:
                self._qimg = QImage(rgb.data, w, h, w, QImage.Format_Grayscale8).copy()
            else:
                self._qimg = QImage(rgb.data, w, h, 3 * w,
                                    QImage.Format_RGB888).copy()
        self.update()

    def has_image(self) -> bool:
        return self._qimg is not None

    # ── 覆盖层 ────────────────────────────────────────────
    def clear_overlays(self) -> None:
        self._overlay_points.clear()
        self._overlay_rects.clear()
        self.update()

    def add_point(self, x: float, y: float, label: str = "") -> None:
        self._overlay_points.append((_clamp(x), _clamp(y), label))
        self.update()

    def add_rect(self, x: float, y: float, w: float, h: float,
                 label: str = "") -> None:
        self._overlay_rects.append((_clamp(x), _clamp(y), _clamp(w), _clamp(h),
                                    label))
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
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        return QRectF((w - dw) / 2, (h - dh) / 2, dw, dh)

    def _to_rel(self, pos: QPointF) -> tuple[float, float]:
        r = self._image_rect()
        if r.isNull() or r.width() <= 0 or r.height() <= 0:
            return (0.0, 0.0)
        return (_clamp((pos.x() - r.x()) / r.width()),
                _clamp((pos.y() - r.y()) / r.height()))

    # ── 鼠标事件 ──────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        if self._qimg is None:
            return
        if self._region_mode and event.button() == Qt.LeftButton:
            self._drag_start = QPointF(event.pos())
            self._drag_rect = None
        else:
            x, y = self._to_rel(QPointF(event.pos()))
            self.point_clicked.emit(x, y)

    def mouseMoveEvent(self, event) -> None:
        if self._region_mode and self._drag_start is not None:
            r = self._image_rect()
            p1 = self._drag_start
            p2 = QPointF(event.pos())
            x = _clamp((min(p1.x(), p2.x()) - r.x()) / r.width())
            y = _clamp((min(p1.y(), p2.y()) - r.y()) / r.height())
            w = _clamp(abs(p2.x() - p1.x()) / r.width())
            h = _clamp(abs(p2.y() - p1.y()) / r.height())
            self._drag_rect = (x, y, w, h)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._region_mode and self._drag_start is not None:
            if self._drag_rect is not None and event.button() == Qt.LeftButton:
                x, y, w, h = self._drag_rect
                if w > 0.02 and h > 0.02:
                    self.region_selected.emit(x, y, w, h)
            self._drag_start = None
            self._drag_rect = None
            self.update()

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

        # 覆盖：框
        for x, y, w, h, label in self._overlay_rects:
            p.setPen(QPen(QColor(60, 200, 255), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(r.x() + x * r.width(), r.y() + y * r.height(),
                              w * r.width(), h * r.height()))
            if label:
                p.setPen(QColor(60, 200, 255))
                p.drawText(QPointF(r.x() + x * r.width(),
                                   r.y() + y * r.height() - 3), label)

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
