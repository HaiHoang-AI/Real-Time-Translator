"""Subtitle overlay window — frameless, always-on-top, translucent.

Two-line cinema subtitle style with smooth 250ms OutCubic transition animation:
  - Top line     : previous committed subtitle (75% font size, 65% opacity)
  - Bottom line  : current committed subtitle (100% font size, 100% opacity)
  - Partial line : live in-progress speech (55% font size, dimmed)

Features:
  - Netflix/YouTube style translucent background card with rounded corners (14px)
  - Guaranteed 100% text containment inside background card (Zero alignment overflow)
  - Strict multi-line word wrapping (max ~520px line width, max 6-8 words/line)
  - Alignment control (Căn trái / Căn giữa / Căn phải)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    Property,
    QRectF,
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
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from rtt.settings import AppSettings


class OverlayBridge(QObject):
    """Thread-safe entry point: emit these from any thread."""

    partial_changed = Signal(str)
    committed_changed = Signal(str)
    status_changed = Signal(str)
    paused_changed = Signal(bool)
    pause_requested = Signal()


class OverlayIconButton(QPushButton):
    """Small, subtle borderless button for overlay controls (Play/Pause) with vector rendering."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._is_paused = False
        self._hovered = False
        self.setToolTip("Tạm dừng dịch")
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def set_paused(self, paused: bool) -> None:
        if self._is_paused != paused:
            self._is_paused = paused
            self.setToolTip("Tiếp tục dịch" if paused else "Tạm dừng dịch")
            self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Subtle hover background without any harsh border
        if self._hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 28))
            painter.drawRoundedRect(self.rect(), 5, 5)

        if self._is_paused:
            # Draw crisp geometric Play triangle (vector shape, NO emoji)
            color = QColor(16, 185, 129, 255 if self._hovered else 220)  # Emerald green
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)

            path = QPainterPath()
            path.moveTo(8.5, 6.0)
            path.lineTo(17.5, 12.0)
            path.lineTo(8.5, 18.0)
            path.closeSubpath()
            painter.drawPath(path)
        else:
            # Draw crisp geometric Pause bars (vector shape, NO emoji)
            alpha = 240 if self._hovered else 150
            color = QColor(255, 255, 255, alpha)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)

            # Left bar
            painter.drawRoundedRect(QRectF(7.0, 6.5, 3.0, 11.0), 1.0, 1.0)
            # Right bar
            painter.drawRoundedRect(QRectF(14.0, 6.5, 3.0, 11.0), 1.0, 1.0)

        painter.end()


class _DualSubtitleWidget(QWidget):
    """Dual-line cinema style subtitle widget with smooth OutCubic transition animation."""

    def __init__(
        self,
        main_pt: int = 20,
        font_family: str = "Segoe UI",
        show_original: bool = True,
        bg_opacity: float = 0.78,
        alignment: str = "center",
        card_width: int = 680,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._main_pt = main_pt
        self._font_family = font_family
        self._show_original = show_original
        self._bg_opacity = bg_opacity
        self._alignment = alignment
        self._card_width = card_width

        self._old_prev_text = ""
        self._prev_text = ""
        self._curr_text = ""
        self._partial_text = ""
        # Pipeline/status notices live in their own line so they never push
        # real subtitles out of the two-line history.
        self._status_text = ""
        # Which edge of this (tall, mostly transparent) widget the card hugs.
        self._anchor = "bottom"

        self._anim_progress = 1.0  # 0.0 -> 1.0

        self.pause_btn = OverlayIconButton(self)
        self.pause_btn.hide()

        self._anim = QPropertyAnimation(self, b"animProgress", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.OutBack)

        self._recalc_height()

    def set_card_width(self, width: int) -> None:
        self._card_width = max(350, width)
        self.update()

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

    def set_bg_opacity(self, opacity: float) -> None:
        self._bg_opacity = max(0.0, min(1.0, opacity))
        self.update()

    def set_alignment(self, align: str) -> None:
        if align in ("left", "center", "right"):
            self._alignment = align
            self.update()

    def set_anchor(self, anchor: str) -> None:
        """'bottom' | 'center' | 'top' — grow the card away from that edge."""
        if anchor in ("bottom", "center", "top") and anchor != self._anchor:
            self._anchor = anchor
            self.update()

    def set_status_text(self, text: str) -> None:
        text = (text or "").strip()
        if text != self._status_text:
            self._status_text = text
            self.update()

    def clear_subtitles(self) -> None:
        self._old_prev_text = self._prev_text = self._curr_text = self._partial_text = ""
        self.update()

    def _recalc_height(self) -> None:
        font_curr = QFont(self._font_family, self._main_pt, QFont.DemiBold)
        line_h = QFontMetrics(font_curr).height()
        total_h = line_h * 8 + 60
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
        if not text:
            # Empty commit = clear request (pause / test subtitle timeout).
            if self._curr_text or self._prev_text:
                self.clear_subtitles()
            return
        if text == self._curr_text:
            return

        if self._curr_text and self._is_continuation(self._curr_text, text):
            self._curr_text = text
            self.update()
            return

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
        if not (self._prev_text or self._curr_text or self._partial_text or self._status_text):
            if self.pause_btn.isVisible():
                self.pause_btn.hide()
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
        m_part = QFontMetrics(font_part)

        pad_x = 24
        pad_y = 14

        target_card_w = min(self._card_width, self.width() - 48)
        max_wrap_width = max(260, target_card_w - (pad_x * 2) - 28)

        prev_lines = self._wrap(m_prev, self._prev_text, max_wrap_width)[:3] if self._prev_text else []
        curr_lines = self._wrap(m_curr, self._curr_text, max_wrap_width)[:3] if self._curr_text else []
        part_lines = self._wrap(m_part, self._partial_text, max_wrap_width)[:1] if (self._show_original and self._partial_text) else []

        interp_lines = []
        font_interp = font_curr
        m_interp = m_curr
        if p < 1.0 and self._prev_text:
            size_interp = int(curr_pt - (curr_pt - prev_pt) * p)
            font_interp = QFont(self._font_family, size_interp, QFont.DemiBold)
            m_interp = QFontMetrics(font_interp)
            interp_lines = self._wrap(m_interp, self._prev_text, max_wrap_width)[:3]

        status_lines = (
            self._wrap(m_part, self._status_text, max_wrap_width)[:2] if self._status_text else []
        )

        h_prev = int(m_prev.height() * 1.35)
        h_curr = int(m_curr.height() * 1.35)
        h_part = int(m_part.height() * 1.35)

        # ── Vertical layout, relative to the top of the text block ──
        # Each block: first baseline = cursor + ascent; block height uses the
        # real glyph height for its last line (no trailing leading).
        def block_h(n: int, h: int, m: QFontMetrics) -> int:
            return (n - 1) * h + m.height() if n else 0

        cursor = 0
        y_top = cursor + m_prev.ascent()
        if prev_lines:
            cursor += block_h(len(prev_lines), h_prev, m_prev) + 10
        y_curr = cursor + m_curr.ascent()
        if curr_lines:
            cursor += block_h(len(curr_lines), h_curr, m_curr) + 8
        y_part = cursor + m_part.ascent()
        if part_lines:
            cursor += block_h(len(part_lines), h_part, m_part) + 6
        y_status = cursor + m_part.ascent()
        if status_lines:
            cursor += block_h(len(status_lines), h_part, m_part) + 6
        content_h = max(0, cursor - 6)

        # Measure max width across ALL rendered lines using their EXACT font metrics
        max_line_w = 0
        for l in prev_lines:
            max_line_w = max(max_line_w, m_prev.horizontalAdvance(l))
        for l in curr_lines:
            max_line_w = max(max_line_w, m_curr.horizontalAdvance(l))
        for l in interp_lines:
            max_line_w = max(max_line_w, m_interp.horizontalAdvance(l))
        for l in part_lines + status_lines:
            max_line_w = max(max_line_w, m_part.horizontalAdvance(l))

        if max_line_w == 0:
            self.pause_btn.hide()
            painter.end()
            return

        card_w = max(target_card_w, min(self.width() - 48, max_line_w + (pad_x * 2) + 28))
        card_h = content_h + (pad_y * 2)

        # Hug the configured screen edge: a bottom subtitle used to float
        # ~half a window above the bottom because the card was top-anchored.
        if self._anchor == "top":
            min_y = 2.0
        elif self._anchor == "center":
            min_y = max(2.0, (self.height() - card_h) / 2.0)
        else:
            min_y = max(2.0, float(self.height() - card_h - 2))
        off = int(min_y + pad_y)
        y_top += off
        y_curr += off
        y_part += off
        y_status += off

        if self._alignment == "left":
            card_x = 24.0
        elif self._alignment == "right":
            card_x = float(self.width() - card_w - 24.0)
        else:  # center
            card_x = (self.width() - card_w) / 2.0

        card_rect = QRectF(card_x, min_y, card_w, card_h)

        # Position small subtle pause/resume button at top-right corner of subtitle card
        btn_w = self.pause_btn.width()
        btn_x = int(card_x + card_w - btn_w - 10)
        btn_y = int(min_y + 8)
        if self.pause_btn.pos() != QPoint(btn_x, btn_y):
            self.pause_btn.move(btn_x, btn_y)
        if not self.pause_btn.isVisible():
            self.pause_btn.show()
        self.pause_btn.raise_()

        # ── Step 1: Draw Background Card (Rounded Claymorphic) ──
        if self._bg_opacity > 0.01:
            bg_alpha = int(255 * self._bg_opacity)
            painter.setPen(QPen(QColor(255, 255, 255, 30), 1.2))
            painter.setBrush(QColor(18, 20, 26, bg_alpha))
            painter.drawRoundedRect(card_rect, 16, 16)

        # Precise line alignment helper inside card_rect
        def get_x(line_w: float) -> float:
            if self._alignment == "left":
                return card_x + pad_x
            elif self._alignment == "right":
                return card_x + card_w - pad_x - line_w - 16
            else:  # center
                return card_x + (card_w - line_w) / 2.0

        # ── Step 2: Draw Old Previous Line (fading out) ──
        if self._old_prev_text and p < 1.0:
            alpha_old = int(255 * 0.65 * (1.0 - p))
            if alpha_old > 0:
                y_old = y_top - int(12 * p)
                old_lines = self._wrap(m_prev, self._old_prev_text, max_wrap_width)[:3]
                self._draw_lines(
                    painter, font_prev, old_lines, y_old,
                    QColor(255, 255, 255, alpha_old),
                    QColor(0, 0, 0, int(220 * (1.0 - p))),
                    get_x,
                )

        # ── Step 3: Draw Previous Line (gliding & shrinking) ──
        if self._prev_text:
            if p < 1.0:
                y_interp = int(y_curr - (y_curr - y_top) * p)
                alpha_interp = int(255 * (1.0 - 0.35 * p))
                outline_alpha = int(220 * (1.0 - 0.2 * p))

                self._draw_lines(
                    painter, font_interp, interp_lines, y_interp,
                    QColor(255, 255, 255, alpha_interp),
                    QColor(0, 0, 0, outline_alpha),
                    get_x,
                )
            else:
                self._draw_lines(
                    painter, font_prev, prev_lines, y_top,
                    QColor(255, 255, 255, 165),  # 65% opacity
                    QColor(0, 0, 0, 180),
                    get_x,
                )

        # ── Step 4: Draw Current Line (gliding & fading in) ──
        if curr_lines:
            if p < 1.0:
                y_curr_interp = int(y_curr + 14 * (1.0 - p))
                alpha_curr = int(255 * p)
                outline_curr = int(220 * p)
                self._draw_lines(
                    painter, font_curr, curr_lines, y_curr_interp,
                    QColor(255, 255, 255, alpha_curr),
                    QColor(0, 0, 0, outline_curr),
                    get_x,
                )
            else:
                self._draw_lines(
                    painter, font_curr, curr_lines, y_curr,
                    QColor(255, 255, 255, 255),  # 100% opacity
                    QColor(0, 0, 0, 230),
                    get_x,
                )

        # ── Step 5: Draw Partial Live Speech Line ──
        if part_lines:
            self._draw_lines(
                painter, font_part, part_lines, y_part,
                QColor(208, 208, 208, 190),
                QColor(0, 0, 0, 160),
                get_x,
            )

        # ── Step 6: Status notice (model loading, fallbacks, lock state) ──
        if status_lines:
            self._draw_lines(
                painter, font_part, status_lines, y_status,
                QColor(52, 211, 153, 235),  # emerald, matches app accent
                QColor(0, 0, 0, 150),
                get_x,
            )

        painter.end()

    def _draw_lines(
        self,
        painter: QPainter,
        font: QFont,
        lines: list[str],
        start_y: int,
        color: QColor,
        outline_color: QColor,
        get_x_fn,
    ) -> None:
        painter.setFont(font)
        metrics = QFontMetrics(font)
        line_h = int(metrics.height() * 1.35)

        # Round joins: miter spikes poked into neighbouring glyphs.
        outline = QPen(outline_color, 4)
        outline.setJoinStyle(Qt.RoundJoin)
        outline.setCapStyle(Qt.RoundCap)

        cur_y = start_y
        for line in lines:
            line_w = metrics.horizontalAdvance(line)
            x = get_x_fn(line_w)

            path = QPainterPath()
            # Winding fill: with the default odd-even rule, overlapping glyph
            # contours (Vietnamese diacritics, some joins) rendered as holes.
            path.setFillRule(Qt.WindingFill)
            path.addText(x, cur_y, font, line)
            # strokePath() never fills with the current brush (drawPath used
            # to paint the glyphs in the card colour first).
            painter.strokePath(path, outline)
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
    def __init__(
        self,
        bridge: OverlayBridge,
        settings: Optional[AppSettings] = None,
        session: Optional[object] = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._session = session
        self._bridge = bridge
        self._is_paused = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # no taskbar entry
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._transparent_for_mouse = False
        self._dragged = False

        from PySide6.QtCore import QTimer

        # Auto-hide for transient notices (lock/unlock hints).
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self.subtitle_widget.set_status_text(""))

        use_custom = settings.data.ui.use_custom_fonts if settings else False
        try:
            from rtt.theme import font_ui
            ui_font = font_ui(use_custom)
        except Exception:
            ui_font = "Segoe UI"

        main_pt = settings.data.display.font_size if settings else 20
        show_orig = settings.data.display.show_original if settings else True
        bg_opac = settings.data.display.bg_opacity if settings else 0.78
        align = getattr(settings.data.display, 'alignment', 'center') if settings else 'center'
        card_w_val = getattr(settings.data.display, 'overlay_width', 680) if settings else 680

        self.subtitle_widget = _DualSubtitleWidget(
            main_pt=main_pt,
            font_family=ui_font,
            show_original=show_orig,
            bg_opacity=bg_opac,
            alignment=align,
            card_width=card_w_val,
            parent=self,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.subtitle_widget)

        self._apply_position(settings)

        bridge.partial_changed.connect(self.subtitle_widget.set_partial_text)
        bridge.committed_changed.connect(self.subtitle_widget.set_committed_text)
        bridge.status_changed.connect(self._show_status)
        bridge.paused_changed.connect(self._on_pause_changed)

        if hasattr(self.subtitle_widget, "pause_btn"):
            self.subtitle_widget.pause_btn.clicked.connect(self._toggle_pause)

        if self._session is not None:
            if hasattr(self._session, "paused_changed"):
                self._session.paused_changed.connect(self._on_pause_changed)
            if hasattr(self._session, "is_paused"):
                self._on_pause_changed(self._session.is_paused)

        self._drag_origin: QPoint | None = None

        if settings is not None:
            settings.changed.connect(self._on_settings_changed)

    def _toggle_pause(self) -> None:
        if self._session and hasattr(self._session, "toggle_pause"):
            self._session.toggle_pause()
        elif self._bridge and hasattr(self._bridge, "pause_requested"):
            self._bridge.pause_requested.emit()
        else:
            self._is_paused = not self._is_paused
            self._on_pause_changed(self._is_paused)

    def _on_pause_changed(self, is_paused: bool) -> None:
        self._is_paused = is_paused
        if hasattr(self.subtitle_widget, "pause_btn"):
            self.subtitle_widget.pause_btn.set_paused(is_paused)

    def _apply_position(self, settings: Optional[AppSettings] = None) -> None:
        """Position the overlay on the correct screen at the correct location."""
        screen = QGuiApplication.primaryScreen().availableGeometry()
        target_w = self.subtitle_widget._card_width + 80 if hasattr(self, "subtitle_widget") else 760
        width = max(target_w, int(screen.width() * 0.75))
        height = self.subtitle_widget.height() + 20
        self.resize(width, height)

        pos = settings.data.display.position if settings else "bottom"
        self.subtitle_widget.set_anchor(pos if pos in ("top", "center") else "bottom")

        # A position the user dragged to wins over the preset — it used to be
        # thrown away on every settings change (e.g. moving the font slider).
        custom = list(getattr(settings.data.display, "custom_pos", []) or []) if settings else []
        if len(custom) == 2:
            from PySide6.QtCore import QRect

            target = QRect(int(custom[0]), int(custom[1]), width, height)
            # Only if it is still (mostly) on a connected screen.
            for scr in QGuiApplication.screens():
                if scr.availableGeometry().intersects(target.adjusted(width // 3, 0, -width // 3, 0)):
                    self.move(target.topLeft())
                    return

        if pos == "top":
            y = screen.y() + 32
        elif pos == "center":
            y = screen.y() + (screen.height() - height) // 2
        else:  # bottom
            y = screen.y() + screen.height() - height - 32

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
        self.subtitle_widget.set_bg_opacity(s.data.display.bg_opacity)
        self.subtitle_widget.set_alignment(getattr(s.data.display, 'alignment', 'center'))
        self.subtitle_widget.set_card_width(getattr(s.data.display, 'overlay_width', 680))
        self._apply_position(s)

    def _click_through(self, enabled: bool) -> None:
        """Lock (clicks go to the app underneath) or unlock (drag / pause button).

        WA_TransparentForMouseEvents only makes *Qt* ignore input; other apps
        still could not be clicked through. WindowTransparentForInput sets the
        native WS_EX_TRANSPARENT style. Changing flags needs a re-show.
        """
        self._transparent_for_mouse = enabled
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowTransparentForInput, enabled)
        if visible:
            self.show()

    def toggle_move_mode(self) -> None:
        """Ctrl+Alt+S: lock the overlay (click-through) / unlock it to drag."""
        self._click_through(not self._transparent_for_mouse)
        if self._transparent_for_mouse:
            self._flash_status("Đã khoá phụ đề: chuột xuyên qua (Ctrl+Alt+S để mở khoá)")
        else:
            self._flash_status("Đã mở khoá phụ đề: kéo để di chuyển (Ctrl+Alt+S để khoá)")

    def _flash_status(self, text: str, ms: int = 2600) -> None:
        self.subtitle_widget.set_status_text(text)
        self._status_timer.start(ms)

    def _show_status(self, text: str) -> None:
        # Pipeline notices go to the dedicated status line — they used to be
        # injected as committed subtitles and pushed real lines away.
        self._status_timer.stop()
        self.subtitle_widget.set_status_text(text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragged = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            self._dragged = True

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_origin = None
        if self._dragged and self._settings is not None:
            self._dragged = False
            top_left = self.frameGeometry().topLeft()
            self._settings.update(display={"custom_pos": [top_left.x(), top_left.y()]})


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
