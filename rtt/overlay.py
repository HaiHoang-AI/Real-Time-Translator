"""Subtitle overlay window — frameless, always-on-top, translucent.

Two text zones, cinema-subtitle style at the bottom of the screen:

  - main line  : latest *committed* translation (big, white, outlined)
  - partial line: live in-progress original/translation (smaller, dimmed)

The window ignores mouse clicks by default (click-through) so it never
steals focus from games/videos. Ctrl+Alt+S toggles "move mode" where it
can be dragged. All updates must go through OverlayBridge signals so any
worker thread can safely post text.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget


class OverlayBridge(QObject):
    """Thread-safe entry point: emit these from any thread."""

    partial_changed = Signal(str)
    committed_changed = Signal(str)
    status_changed = Signal(str)


class _OutlinedLabel(QWidget):
    """Text with a dark outline so it stays readable on any background."""

    def __init__(
        self, point_size: int, color: str, weight=QFont.DemiBold, max_lines: int = 2
    ) -> None:
        super().__init__()
        self._text = ""
        self._font = QFont("Segoe UI", point_size, weight)
        self._color = QColor(color)
        self._max_lines = max_lines
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # Reserve room for max_lines of text so wrapped lines never paint
        # outside the widget (they would be clipped -> "missing words").
        from PySide6.QtGui import QFontMetrics

        line_h = QFontMetrics(self._font).height()
        self.setFixedHeight(line_h * max_lines + 10)

    def set_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.update()

    def paintEvent(self, _event) -> None:
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self._font)

        metrics = painter.fontMetrics()
        # Word-wrap; if it still overflows, keep the tail (newest words win).
        lines = self._wrap(metrics, self._text, self.width() - 24)[-self._max_lines:]

        y = self.height() - 8 - metrics.descent()
        for line in reversed(lines):
            x = (self.width() - metrics.horizontalAdvance(line)) / 2
            path = QPainterPath()
            path.addText(x, y, self._font, line)
            painter.setPen(QPen(QColor(0, 0, 0, 220), 4))
            painter.drawPath(path)
            painter.fillPath(path, self._color)
            y -= metrics.height()
        painter.end()

    @staticmethod
    def _wrap(metrics, text: str, width: int) -> list[str]:
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
    def __init__(self, bridge: OverlayBridge) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # no taskbar entry
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._click_through(True)

        self.main_line = _OutlinedLabel(20, "#ffffff", max_lines=3)
        self.partial_line = _OutlinedLabel(13, "#d0d0d0", weight=QFont.Normal, max_lines=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)
        layout.addWidget(self.partial_line)
        layout.addWidget(self.main_line)

        screen = QGuiApplication.primaryScreen().availableGeometry()
        width = int(screen.width() * 0.72)
        height = self.main_line.height() + self.partial_line.height() + 20
        self.resize(width, height)
        self.move(
            screen.x() + (screen.width() - width) // 2,
            screen.y() + screen.height() - height - 48,
        )

        bridge.partial_changed.connect(self.partial_line.set_text)
        bridge.committed_changed.connect(self.main_line.set_text)
        bridge.status_changed.connect(self._show_status)
        self._drag_origin: QPoint | None = None

    # ------------------------------------------------------------ behaviors

    def _click_through(self, enabled: bool) -> None:
        self._transparent_for_mouse = enabled
        self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)

    def toggle_move_mode(self) -> None:
        """Ctrl+Alt+S: let the user drag the overlay, then lock it again."""
        self._click_through(not self._transparent_for_mouse)
        self.setWindowOpacity(0.85 if not self._transparent_for_mouse else 1.0)

    def _show_status(self, text: str) -> None:
        self.main_line.set_text(text)

    # Dragging (only reachable in move mode).
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is not None:
            self.move(event.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_origin = None


# --------------------------------------------------------------------- demo

def main() -> None:
    """Visual smoke test: fake subtitles cycling through the overlay."""
    import itertools
    import sys

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    bridge = OverlayBridge()
    overlay = SubtitleOverlay(bridge)
    overlay.show()

    demo = itertools.cycle([
        ("Bạn dễ cáu kỉnh hơn, lo lắng và căng thẳng hơn, và một phần của não bộ "
         "liên quan đến việc xử lý cảm xúc, vỏ não trước trán, thường giữ hạch hạnh "
         "nhân của bạn trong tầm kiểm soát, nhưng nó vẫn không hoạt động hết công suất.",
         "Your prefrontal cortex usually keeps your amygdala in check, but it still "
         "isn't firing on all cylinders."),
        ("Các mô hình AI giờ đây có thể dịch giọng nói theo thời gian thực.", "translate speech in real time"),
        ("Cảm ơn các bạn đã theo dõi video.", "thank you for watching"),
    ])

    def tick() -> None:
        committed, partial = next(demo)
        bridge.committed_changed.emit(committed)
        bridge.partial_changed.emit("… " + partial)

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(2500)
    tick()
    QTimer.singleShot(12_000, app.quit)  # auto-close the smoke test
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
