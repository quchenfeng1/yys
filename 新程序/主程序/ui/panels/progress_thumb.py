"""UI 子面板：任务进度缩略图（2026-08-16）。

把可视化任务进度组渲染成 o-o-o 缩略图（主行横排、分支下挂）：
- o 状态：执行中=蓝 / 完成=绿 / 失败=红 / 未执行=灰
- 组间边：执行游标位于两点之间（未框住节点在执行）→ 蓝色箭头，其余灰线
- 数据源：VISUAL_PROGRESS 事件快照（ProgressTracker.snapshot）
"""
from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, QTimer, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QWidget

_STATE_COLORS = {
    "gray": (125, 130, 138),
    "blue": (70, 140, 255),
    "green": (60, 200, 110),
    "red": (235, 80, 80),
}
_EDGE_ACTIVE = QColor("#3f8cff")
_EDGE_NORMAL = QColor("#5a6068")
_CELL_W = 64
_ROW_H = 62
_RADIUS = 15


class SpinningDot(QWidget):
    """蓝色转圈小图标（2026-08-16）：任务运行中旋转，空闲静止灰色。"""

    def __init__(self, radius: int = 12, parent=None):
        super().__init__(parent)
        self._radius = radius
        self._angle = 0
        self.setFixedSize(radius * 2 + 6, radius * 2 + 6)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def set_spinning(self, on: bool) -> None:
        if on and not self._timer.isActive():
            self._timer.start()
        elif not on and self._timer.isActive():
            self._timer.stop()
            self._angle = 0
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = self.rect().center()
        r = self._radius
        # 底环
        painter.setPen(QPen(QColor("#cfe3ff"), 2.2))
        painter.drawEllipse(c, r - 3, r - 3)
        # 旋转弧（蓝）
        pen = QPen(QColor("#1e88e5"), 2.2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(c.x() - r + 3, c.y() - r + 3, 2 * (r - 3), 2 * (r - 3),
                        -self._angle * 16, 100 * 16)
        painter.end()


class ProgressThumb(QWidget):
    """任务执行进度缩略图（快照驱动，纯绘制无布局开销）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot: dict | None = None
        self.setMinimumHeight(110)

    # ── 数据 ───────────────────────────────────────────
    def update_snapshot(self, snap: dict | None) -> None:
        self._snapshot = snap
        self.update()

    def reset(self) -> None:
        self._snapshot = None
        self.update()

    def _point_pos(self, p: dict) -> tuple[float, float]:
        return (p.get("col", 0) * _CELL_W + 30,
                p.get("row", 0) * _ROW_H + 30)

    # ── 绘制 ───────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        snap = self._snapshot
        if not snap or not snap.get("points"):
            painter.setPen(QColor("#8a94a6"))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "任务运行后此处显示执行进度\n（每个 o 是一个进度点）")
            return
        points = {p["id"]: p for p in snap["points"]}
        states = snap.get("states", {})
        self._draw_edges(painter, snap, points)
        self._draw_points(painter, snap, states, points)
        painter.end()

    def _draw_edges(self, painter, snap, points) -> None:
        for e in snap.get("edges", []):
            a = points.get(e.get("from"))
            b = points.get(e.get("to"))
            if a is None or b is None:
                continue
            p1 = self._point_pos(a)
            p2 = self._point_pos(b)
            active = bool(e.get("active"))
            color = _EDGE_ACTIVE if active else _EDGE_NORMAL
            painter.setPen(QPen(color, 2.2 if active else 1.5))
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            dist = max(1e-6, math.hypot(dx, dy))
            ux, uy = dx / dist, dy / dist
            s1 = (p1[0] + ux * (_RADIUS + 3), p1[1] + uy * (_RADIUS + 3))
            s2 = (p2[0] - ux * (_RADIUS + 3), p2[1] - uy * (_RADIUS + 3))
            painter.drawLine(QPointF(*s1), QPointF(*s2))
            if active:
                # 箭头：指向执行方向（由上一组指向下一组）
                mid = ((s1[0] + s2[0]) / 2, (s1[1] + s2[1]) / 2)
                ang = math.atan2(s2[1] - s1[1], s2[0] - s1[0])
                poly = QPolygonF()
                for off in (-2.0944, 0.0, 2.0944):   # ±120°
                    a_ = ang + off
                    poly.append(QPointF(mid[0] + 9 * math.cos(a_),
                                        mid[1] + 9 * math.sin(a_)))
                painter.setPen(Qt.NoPen)
                painter.setBrush(_EDGE_ACTIVE)
                painter.drawPolygon(poly)

    def _draw_points(self, painter, snap, states, points) -> None:
        for p in snap["points"]:
            state = states.get(p["id"], "gray")
            color = QColor(*_STATE_COLORS.get(state, _STATE_COLORS["gray"]))
            x, y = self._point_pos(p)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, y), _RADIUS, _RADIUS)
            # 名字在 o 下方
            name = str(p.get("name", ""))
            if len(name) > 4:
                name = name[:4] + "…"
            painter.setPen(QColor("#c9d1d9"))
            painter.drawText(QRectF(x - 40, y + _RADIUS + 3, 80, 18),
                             Qt.AlignHCenter | Qt.AlignTop, name)
