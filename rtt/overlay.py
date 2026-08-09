"""Subtitle overlay window — frameless, always-on-top, translucent.

Two-line cinema subtitle style with smooth 250ms OutCubic transition animation:
  - Top line     : previous committed subtitle (75% font size, 65% opacity)
  - Bottom line  : current committed subtitle (100% font size, 100% opacity)
  - Partial line : live in-progress speech (55% font size, dimmed)

Smooth animation: when a new sentence is committed, the current sentence
shrinks (100% -> 75%), fades (100% -> 65%), and glides up into the top line
while the new sentence slides in below.

Ctrl+Alt+S toggles "move mode" where it can be dragged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    Property,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QVBoxLayout, QWidget

if TYPE_CHECKING:
    from rtt.settings import AppSettings


class OverlayBridge(QObject):
    """Thread-safe entry point: emit these from any thread."""

    partial_changed = Signal(str)
    committed_changed = Signal(str)
    status_changed = Signal(str)


class _DualSubtitleWidget(QWidget):
    """Dual-line cinema style subtitle widget with smooth OutCubic transition animation.

    Top line: Previous committed sentence (75% font size, 65% opacity).
    Bottom line: Current committed sentence (100% font size, 100% opacity).
    Below: Partial live speech line (55% font size, dimmed).
    """

    def __init__(
        self,
        main_pt: int = 20,
        font_family: str = "Segoe UI",
        show_original: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._main_pt = main_pt
        self._font_family = font_family
        self._show_original = show_original

        self._old_prev_text = ""
        self._prev_text = ""
        self._curr_text = ""
        self._partial_text = ""

        self._anim_progress = 1.0  # 0.0 -> 1.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._anim = QPropertyAnimation(self, b"animProgress", self)
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self._recalc_height()

    @Property(float)
    def animProgress(self) -> float:
        return self._anim_progress

    @animProgress.setter
    def animProgress(self, val: float) -> None:
        self._anim_progress = val
        self.update()

    def set_font(self, family: str, main_pt: int | None = None) -> None:
        self._font_family = family
        if main_pt is not None:
            self._main_pt = main_pt
        self._recalc_height()
        self.update()

    def set_show_original(self, show: bool) -> None:
        self._show_original = show
        self._recalc_height()
        self.update()

    def _recalc_height(self) -> None:
        font_curr = QFont(self._font_family, self._main_pt, QFont.DemiBold)
        line_h = QFontMetrics(font_curr).height()
        total_h = line_h * 5 + 34
        self.setFixedHeight(total_h)

    @staticmethod
    def _is_continuation(old_text: str, new_text: str) -> bool:
        """Check if new_text is an in-progress update of old_text rather than a new distinct sentence."""
        old_clean = old_text.strip().lower()
        new_clean = new_text.strip().lower()
        if not old_clean or not new_clean:
            return False

        if new_clean.startswith(old_clean[:15]) or old_clean.startswith(new_clean[:15]):
            return True

        old_words = set(old_clean.split())
        new_words = set(new_clean.split())
        if not old_words or not new_words:
            return False

        common = old_words.intersection(new_words)
        overlap = len(common) / max(1, min(len(old_words), len(new_words)))
        return overlap >= 0.55

    def set_committed_text(self, text: str) -> None:
        text = text.strip()
        if not text or text == self._curr_text:
            return

        # If this is an in-progress update to the CURRENT sentence (not a new distinct sentence):
        if self._curr_text and self._is_continuation(self._curr_text, text):
            # Update the current sentence in place without shifting prev_text or re-triggering slide animation!
            self._curr_text = text
            self.update()
            return

        # Otherwise, this is a BRAND NEW DISTINCT SENTENCE:
        self._old_prev_text = self._prev_text
        self._prev_text = self._curr_text
        self._curr_text = text

        self._anim.stop()
        self._anim_progress = 0.0
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self.update()

    def set_partial_text(self, text: str) -> None:
        if text != self._partial_text:
            self._partial_text = text
            self.update()

    def paintEvent(self, _event) -> None:
        if not self._prev_text and not self._curr_text and not self._partial_text:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        p = self._anim_progress

        prev_pt = int(self._main_pt * 0.75)
        curr_pt = self._main_pt
        part_pt = max(10, int(self._main_pt * 0.55))

        font_prev = QFont(self._font_family, prev_pt, QFont.DemiBold)
        font_curr = QFont(self._font_family, curr_pt, QFont.DemiBold)
        font_part = QFont(self._font_family, part_pt, QFont.Normal)

        m_prev = QFontMetrics(font_prev)
        m_curr = QFontMetrics(font_curr)

        h_prev = m_prev.height()
        h_curr = m_curr.height()

        # Target Y positions
        y_top = 10 + m_prev.ascent()
        y_curr = y_top + h_prev * 2 + 10
        y_part = y_curr + h_curr * 2 + 6

        # 1. Paint Old Previous Line (fading out)
        if self._old_prev_text and p < 1.0:
            alpha_old = int(255 * 0.65 * (1.0 - p))
            if alpha_old > 0:
                y_old = y_top - int(12 * p)
                self._draw_outlined_text(
                    painter, font_prev, self._old_prev_text, y_old,
                    QColor(255, 255, 255, alpha_old),
                    QColor(0, 0, 0, int(220 * (1.0 - p))),
                    max_lines=2,
                )

        # 2. Paint Previous Line (gliding & shrinking from current pos to top pos)
        if self._prev_text:
            if p < 1.0:
                # Interpolate size: 100% -> 75%
                size_interp = int(curr_pt - (curr_pt - prev_pt) * p)
                font_interp = QFont(self._font_family, size_interp, QFont.DemiBold)
                # Interpolate Y: y_curr -> y_top
                y_interp = int(y_curr - (y_curr - y_top) * p)
                # Interpolate opacity: 1.0 -> 0.65
                alpha_interp = int(255 * (1.0 - 0.35 * p))
                outline_alpha = int(220 * (1.0 - 0.2 * p))

                self._draw_outlined_text(
                    painter, font_interp, self._prev_text, y_interp,
                    QColor(255, 255, 255, alpha_interp),
                    QColor(0, 0, 0, outline_alpha),
                    max_lines=2,
                )
            else:
                self._draw_outlined_text(
                    painter, font_prev, self._prev_text, y_top,
                    QColor(255, 255, 255, 165),  # 65% opacity
                    QColor(0, 0, 0, 180),
                    max_lines=2,
                )

        # 3. Paint Current Line (gliding & fading in at bottom)
        if self._curr_text:
            if p < 1.0:
                y_curr_interp = int(y_curr + 14 * (1.0 - p))
                alpha_curr = int(255 * p)
                outline_curr = int(220 * p)
                self._draw_outlined_text(
                    painter, font_curr, self._curr_text, y_curr_interp,
                    QColor(255, 255, 255, alpha_curr),
                    QColor(0, 0, 0, outline_curr),
                    max_lines=2,
                )
            else:
                self._draw_outlined_text(
                    painter, font_curr, self._curr_text, y_curr,
                    QColor(255, 255, 255, 255),  # 100% opacity
                    QColor(0, 0, 0, 230),
                    max_lines=2,
                )

        # 4. Paint Partial Live Speech Line
        if self._show_original and self._partial_text:
            self._draw_outlined_text(
                painter, font_part, self._partial_text, y_part,
                QColor(208, 208, 208, 190),
                QColor(0, 0, 0, 160),
                max_lines=1,
            )

        painter.end()

    def _draw_outlined_text(
        self,
        painter: QPainter,
        font: QFont,
        text: str,
        y: int,
        color: QColor,
        outline_color: QColor,
        max_lines: int = 2,
    ) -> None:
        metrics = painter.fontMetrics()
        lines = self._wrap(metrics, text, self.width() - 32)[-max_lines:]
        line_h = metrics.height()

        cur_y = y
        for line in lines:
            x = (self.width() - metrics.horizontalAdvance(line)) / 2
            path = QPainterPath()
            path.addText(x, cur_y, font, line)
            painter.setPen(QPen(outline_color, 4))
            painter.drawPath(path)
            painter.fillPath(path, color)
            cur_y += line_h

    @staticmethod
    def _wrap(metrics: QFontMetrics, text: str, width: int) -> list[str]:
        words, lines, cur = text.split(), [], ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if metrics.horizontalAdvance(trial) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines


class SubtitleOverlay(QWidget):
    def __init__(self, bridge: OverlayBridge, settings: Optional[AppSettings] = None) -> None:
        super().__init__()
        self._settings = settings
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # no taskbar entry
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._click_through(True)

        # Resolve initial font family from settings.
        use_custom = settings.data.ui.use_custom_fonts if settings else False
        try:
            from rtt.theme import font_ui
            ui_font = font_ui(use_custom)
        except Exception:
            ui_font = "Segoe UI"

        main_pt = settings.data.display.font_size if settings else 20
        show_orig = settings.data.display.show_original if settings else True

        self.subtitle_widget = _DualSubtitleWidget(
            main_pt=main_pt,
            font_family=ui_font,
            show_original=show_orig,
            parent=self,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.subtitle_widget)

        self._apply_position(settings)

        bridge.partial_changed.connect(self.subtitle_widget.set_partial_text)
        bridge.committed_changed.connect(self.subtitle_widget.set_committed_text)
        bridge.status_changed.connect(self._show_status)
        self._drag_origin: QPoint | None = None

        if settings is not None:
            settings.changed.connect(self._on_settings_changed)

    def _apply_position(self, settings: Optional[AppSettings] = None) -> None:
        """Position the overlay on the correct screen at the correct location."""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        width = int(screen.width() * 0.72)
        height = self.subtitle_widget.height() + 20
        self.resize(width, height)

        pos = settings.data.display.position if settings else "bottom"
        if pos == "top":
            y = screen.y() + 32
        elif pos == "center":
            y = screen.y() + (screen.height() - height) // 2
        else:  # bottom
            y = screen.y() + screen.height() - height - 48

        self.move(screen.x() + (screen.width() - width) // 2, y)

    def _on_settings_changed(self) -> None:
        """Re-apply display settings when they change."""
        s = self._settings
        if s is None:
            return

        try:
            from rtt.theme import font_ui
            ui_font = font_ui(s.data.ui.use_custom_fonts)
        except Exception:
            ui_font = "Segoe UI"

        main_pt = s.data.display.font_size
        self.subtitle_widget.set_font(ui_font, main_pt)
        self.subtitle_widget.set_show_original(s.data.display.show_original)
        self._apply_position(s)

    def _click_through(self, enabled: bool) -> None:
        self._transparent_for_mouse = enabled
        self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)

    def toggle_move_mode(self) -> None:
        """Ctrl+Alt+S: let the user drag the overlay, then lock it again."""
        self._click_through(not self._transparent_for_mouse)
        self.setWindowOpacity(0.85 if not self._transparent_for_mouse else 1.0)

    def _show_status(self, text: str) -> None:
        self.subtitle_widget.set_committed_text(text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None:
            self.move(event.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_origin = None


def main() -> None:
    """Visual smoke test: fake 2-line animated subtitles cycling through the overlay."""
    import itertools
    import sys

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    bridge = OverlayBridge()
    overlay = SubtitleOverlay(bridge)
    overlay.show()

    demo = itertools.cycle([
        ("Bạn dễ cáu kỉnh hơn, lo lắng và căng thẳng hơn.", "You become more irritable and anxious."),
        ("Một phần của não bộ liên quan đến việc xử lý cảm xúc là vỏ não trước trán.", "Your prefrontal cortex handles emotional processing."),
        ("Các mô hình AI giờ đây có thể dịch giọng nói theo thời gian thực.", "AI models translate speech in real time."),
        ("Cảm ơn các bạn đã theo dõi video.", "Thank you for watching the video."),
    ])

    def tick() -> None:
        committed, partial = next(demo)
        bridge.committed_changed.emit(committed)
        bridge.partial_changed.emit("… " + partial)

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(3000)
    tick()
    QTimer.singleShot(15_000, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
