"""Physics & Motion Design System for Real-Time Translator.

Provides tactile spring physics, smooth hover lift, animated sliders,
and liquid page transitions for a state-of-the-art desktop UI experience.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
    Property,
)
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QPushButton,
    QSlider,
    QStackedWidget,
    QWidget,
)


# ---------------------------------------------------------------------------
# 1. Elastic Button (Spring Scale on Press & Release)
# ---------------------------------------------------------------------------

class ElasticButton(QPushButton):
    """Button with physical spring compression on press and elastic bounce on release."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self._scale: float = 1.0
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"scaleFactor", self)

    def get_scale_factor(self) -> float:
        return self._scale

    def set_scale_factor(self, factor: float) -> None:
        self._scale = factor
        self.update()

    scaleFactor = Property(float, get_scale_factor, set_scale_factor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._anim.stop()
            self._anim.setDuration(110)
            self._anim.setStartValue(self._scale)
            self._anim.setEndValue(0.94)
            self._anim.setEasingCurve(QEasingCurve.OutQuad)
            self._anim.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._anim.stop()
            self._anim.setDuration(260)
            self._anim.setStartValue(self._scale)
            self._anim.setEndValue(1.0)
            self._anim.setEasingCurve(QEasingCurve.OutBack)  # Spring overshoot bounce!
            self._anim.start()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        if abs(self._scale - 1.0) < 0.001:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Scale transform centered at the button's middle point
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        painter.translate(cx, cy)
        painter.scale(self._scale, self._scale)
        painter.translate(-cx, -cy)

        # Render original button appearance with scale applied
        super().paintEvent(event)
        painter.end()


# ---------------------------------------------------------------------------
# 2. Hover Lift Frame (Card Elevation & Soft Drop-Shadow)
# ---------------------------------------------------------------------------

class HoverLiftFrame(QFrame):
    """Card frame that lifts (-2px) smoothly on hover without DWM shadow glitches."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._lift_offset: float = 0.0
        self._anim_lift = QPropertyAnimation(self, b"liftOffset", self)

    def get_lift_offset(self) -> float:
        return self._lift_offset

    def set_lift_offset(self, offset: float) -> None:
        self._lift_offset = offset
        self.update()

    liftOffset = Property(float, get_lift_offset, set_lift_offset)

    def enterEvent(self, event) -> None:
        self._anim_lift.stop()
        self._anim_lift.setDuration(180)
        self._anim_lift.setStartValue(self._lift_offset)
        self._anim_lift.setEndValue(-2.0)
        self._anim_lift.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_lift.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._anim_lift.stop()
        self._anim_lift.setDuration(220)
        self._anim_lift.setStartValue(self._lift_offset)
        self._anim_lift.setEndValue(0.0)
        self._anim_lift.setEasingCurve(QEasingCurve.OutQuad)
        self._anim_lift.start()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        if abs(self._lift_offset) < 0.001:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(0, self._lift_offset)
        super().paintEvent(event)
        painter.end()


# ---------------------------------------------------------------------------
# 3. Smooth Physics Slider (Liquid Glide Interpolation)
# ---------------------------------------------------------------------------

class PhysicsSlider(QSlider):
    """Horizontal QSlider with smooth value glide and spring handle feedback."""

    def __init__(self, orientation=Qt.Horizontal, parent: Optional[QWidget] = None) -> None:
        super().__init__(orientation, parent)
        self._visual_val: float = float(self.value())
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"visualValue", self)

    def get_visual_value(self) -> float:
        return self._visual_val

    def set_visual_value(self, val: float) -> None:
        self._visual_val = val
        self.update()

    visualValue = Property(float, get_visual_value, set_visual_value)

    def setValueSmooth(self, target_val: int) -> None:
        target_val = max(self.minimum(), min(self.maximum(), target_val))
        super().setValue(target_val)

        self._anim.stop()
        self._anim.setDuration(160)
        self._anim.setStartValue(self._visual_val)
        self._anim.setEndValue(float(target_val))
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            # Smooth click-to-position glide
            val_range = self.maximum() - self.minimum()
            if val_range > 0:
                rel_pos = event.position().x() / float(self.width())
                target = int(self.minimum() + rel_pos * val_range)
                self.setValueSmooth(target)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# 4. Animated Sliding Stacked Widget (Page Transitions)
# ---------------------------------------------------------------------------

class SlidingStackedWidget(QStackedWidget):
    """QStackedWidget that animates horizontal slide transitions between pages."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._anim_duration: int = 250
        self._is_animating: bool = False

    def slide_to_index(self, index: int) -> None:
        if index == self.currentIndex() or self._is_animating:
            return

        if index < 0 or index >= self.count():
            return

        self._is_animating = True
        current_widget = self.currentWidget()
        next_widget = self.widget(index)

        w = self.width()
        h = self.height()

        # Determine slide direction: left-to-right or right-to-left
        going_right = index > self.currentIndex()
        offset_x = w if going_right else -w

        next_widget.setGeometry(0, 0, w, h)
        next_widget.move(offset_x, 0)
        next_widget.show()
        next_widget.raise_()

        # Animate current widget out & next widget in
        anim_curr = QPropertyAnimation(current_widget, b"pos", self)
        anim_curr.setDuration(self._anim_duration)
        anim_curr.setStartValue(QPoint(0, 0))
        anim_curr.setEndValue(QPoint(-offset_x, 0))
        anim_curr.setEasingCurve(QEasingCurve.OutCubic)

        anim_next = QPropertyAnimation(next_widget, b"pos", self)
        anim_next.setDuration(self._anim_duration)
        anim_next.setStartValue(QPoint(offset_x, 0))
        anim_next.setEndValue(QPoint(0, 0))
        anim_next.setEasingCurve(QEasingCurve.OutCubic)

        def _on_finish():
            self.setCurrentIndex(index)
            current_widget.move(0, 0)
            self._is_animating = False

        anim_next.finished.connect(_on_finish)
        anim_curr.start()
        anim_next.start()
