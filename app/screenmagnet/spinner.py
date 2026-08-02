"""Two arrows chasing each other in a circle, spinning while we scan for screens."""

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

import math


class ChasingArrows(QWidget):
    """Circular scan indicator: two arcs, each with an arrowhead, chasing.

    Colours come from the widget palette so it re-themes with Plasma's light/dark
    scheme instead of hardcoding anything.
    """

    def __init__(self, parent=None, diameter=44, line_width=3):
        super().__init__(parent)
        self._angle = 0
        self._line_width = line_width
        self.setFixedSize(diameter, diameter)

        self._anim = QPropertyAnimation(self, b"angle", self)
        self._anim.setStartValue(0)
        self._anim.setEndValue(360)
        self._anim.setDuration(1400)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)

    def start(self):
        self.show()
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._anim.start()

    def stop(self):
        self._anim.stop()
        self.hide()

    def _get_angle(self):
        return self._angle

    def _set_angle(self, value):
        self._angle = value
        self.update()

    angle = Property(int, _get_angle, _set_angle)

    def _arrowhead(self, painter, cx, cy, radius, deg, color):
        """Draw a triangular head tangent to the circle at `deg`."""
        rad = math.radians(deg)
        tip = QPointF(cx + radius * math.cos(rad), cy - radius * math.sin(rad))
        # tangent direction (counter-clockwise)
        tx, ty = -math.sin(rad), -math.cos(rad)
        nx, ny = math.cos(rad), -math.sin(rad)
        size = self._line_width * 2.1
        back_x, back_y = tip.x() - tx * size * 1.6, tip.y() - ty * size * 1.6

        path = QPainterPath()
        path.moveTo(tip)
        path.lineTo(back_x + nx * size, back_y + ny * size)
        path.lineTo(back_x - nx * size, back_y - ny * size)
        path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pad = self._line_width * 2
        rect = self.rect().adjusted(pad, pad, -pad, -pad)
        cx, cy = rect.center().x(), rect.center().y()
        radius = rect.width() / 2

        lead = self.palette().highlight().color()
        trail = QColor(lead)
        trail.setAlpha(110)

        span = 110  # degrees of arc per arrow
        for offset, color in ((0, lead), (180, trail)):
            pen = QPen(color)
            pen.setWidth(self._line_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            start = self._angle + offset
            # QPainter angles are 1/16th degree, counter-clockwise
            painter.drawArc(rect, int(-start * 16), int(-span * 16))
            self._arrowhead(painter, cx, cy, radius, -(start + span), color)

        painter.end()
