"""Unified Main Application Window — Real-Time Translator.

Combines Transcript History and Settings into a single frameless window with a
top navigation bar, soft drop shadow, edge resizing and live theme switching.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rtt.history import TranscriptSession
from rtt.motion import ElasticButton, SlidingStackedWidget
from rtt.overlay import OverlayBridge
from rtt.settings import AppSettings
from rtt.settings_ui import SettingsPanel
from rtt.theme import (
    ThemeColors,
    apply_theme,
    font_mono as _font_mono_str,
    font_ui as _font_ui_str,
    get_theme,
    set_prefer_custom_fonts,
)
from rtt.transcript_ui import TranscriptPanel

ICON_PATH = Path(__file__).parent.parent / "rtt_icon.ico"
SHADOW = 10          # px of soft shadow around the card (also the resize grip)
RADIUS = 16


def font_ui(pt_size: float = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(_font_ui_str())
    f.setPointSizeF(pt_size)
    f.setWeight(weight)
    return f


def font_mono(pt_size: float = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(_font_mono_str())
    f.setPointSizeF(pt_size)
    f.setWeight(weight)
    return f


def _load_app_icon() -> QIcon:
    if not ICON_PATH.exists():
        return QIcon()
    src_img = QImage(str(ICON_PATH))
    if src_img.isNull():
        return QIcon(str(ICON_PATH))
    ico = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        scaled = src_img.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ico.addPixmap(QPixmap.fromImage(scaled))
    return ico


class TopTabButton(ElasticButton):
    """Top bar navigation tab (segmented control item)."""

    def __init__(self, text: str, theme: ThemeColors, parent=None):
        super().__init__(text, parent)
        self.theme = theme
        self.setFont(font_ui(10, QFont.Weight.DemiBold))
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setFixedHeight(32)
        hover_bg = "rgba(0,0,0,0.05)" if theme.name == "light" else "rgba(255,255,255,0.06)"
        # One stylesheet with :checked — no per-toggle restyling needed.
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {theme.dim};
                border: none;
                border-radius: 9px;
                padding: 0 18px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                color: {theme.text};
            }}
            QPushButton:checked {{
                background-color: {theme.accent};
                color: {theme.accent_text};
                font-weight: 700;
            }}
        """)


class WindowControlButton(QPushButton):
    """Minimize / maximize / close drawn as crisp vector glyphs (no font glyphs)."""

    def __init__(self, kind: str, theme: ThemeColors, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.theme = theme
        self.maximized = False
        self.setFixedSize(36, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setToolTip({"min": "Thu nhỏ", "max": "Phóng to", "close": "Ẩn xuống khay"}[kind])
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hovered = self.underMouse()
        if hovered:
            if self.kind == "close":
                bg = QColor("#FEE2E2") if self.theme.name == "light" else QColor("#4A1D1D")
            else:
                bg = QColor(0, 0, 0, 14) if self.theme.name == "light" else QColor(255, 255, 255, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)

        fg = QColor(self.theme.error if (hovered and self.kind == "close") else
                    (self.theme.text if hovered else self.theme.dim))
        pen = QPen(fg, 1.4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        s = 5.0
        if self.kind == "min":
            p.drawLine(QPoint(int(cx - s), int(cy)), QPoint(int(cx + s), int(cy)))
        elif self.kind == "max":
            if self.maximized:  # "restore": two overlapping squares
                p.drawRoundedRect(QRectF(cx - s, cy - s + 2, 2 * s - 2, 2 * s - 2), 1.5, 1.5)
                p.drawLine(QPoint(int(cx - s + 2), int(cy - s)), QPoint(int(cx + s), int(cy - s)))
                p.drawLine(QPoint(int(cx + s), int(cy - s)), QPoint(int(cx + s), int(cy + s - 2)))
            else:
                p.drawRoundedRect(QRectF(cx - s, cy - s, 2 * s, 2 * s), 1.5, 1.5)
        else:
            p.drawLine(QPoint(int(cx - s), int(cy - s)), QPoint(int(cx + s), int(cy + s)))
            p.drawLine(QPoint(int(cx + s), int(cy - s)), QPoint(int(cx - s), int(cy + s)))
        p.end()


class HeaderBar(QFrame):
    """Top bar: drag to move, double-click to maximize/restore."""

    def __init__(self, main_win: "MainWindow", parent=None):
        super().__init__(parent)
        self.main_win = main_win

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and not isinstance(
            self.childAt(event.position().toPoint()), QPushButton
        ):
            self.main_win.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MainWindow(QWidget):
    """Single unified control window containing Transcript and Settings tabs."""

    def __init__(
        self,
        settings: AppSettings,
        session: Optional[TranscriptSession] = None,
        bridge: Optional[OverlayBridge] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.session = session
        self.bridge = bridge
        self.overlay_bridge = bridge
        if settings:
            set_prefer_custom_fonts(settings.data.ui.use_custom_fonts)
        self.theme = get_theme(settings.data.ui.theme if settings else "dark")
        self.container: Optional[QFrame] = None
        self._rebuild_pending = False

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Real-Time Translator")
        self.setMinimumSize(900, 620)
        self.resize(1180, 800)
        self.setMouseTracking(True)

        icon = _load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        self._main_layout.setSpacing(0)

        self._build_ui()
        self.installEventFilter(self)

        if self.settings:
            # Only a theme / font change needs a restyle. Re-applying the whole
            # stylesheet on *every* setting change (each slider tick!) made the
            # window stutter.
            self.settings.appearance_changed.connect(self._schedule_rebuild)

        app = QApplication.instance()
        if app is not None:
            try:  # follow the OS light/dark switch when theme = "auto"
                app.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
            except Exception:
                pass

    # ─────────────────────────────────────────────── construction ──

    def _build_ui(self, tab_index: int = 0, settings_tab: int = 0) -> None:
        t = self.theme
        self.container = QFrame(self)
        self.container.setObjectName("CentralContainer")
        self._apply_container_style()
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        self._main_layout.addWidget(self.container)

        # ── Header: brand · tabs · window controls ─────────────────
        self.header = HeaderBar(self, self.container)
        self.header.setObjectName("HeaderBar")
        self.header.setFixedHeight(54)
        self.header.setStyleSheet(
            f"QFrame#HeaderBar {{ border: none; border-bottom: 1px solid {t.border}; background: transparent; }}"
        )
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(18, 0, 10, 0)
        header_layout.setSpacing(10)

        brand_icon = QLabel()
        icon = self.windowIcon()
        if not icon.isNull():
            brand_icon.setPixmap(icon.pixmap(20, 20))
        brand_icon.setFixedSize(20, 20)
        brand_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        header_layout.addWidget(brand_icon)

        app_title = QLabel("Real-Time Translator")
        app_title.setFont(font_ui(11.5, QFont.Weight.Bold))
        app_title.setStyleSheet(f"color: {t.text};")
        app_title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        header_layout.addWidget(app_title)
        header_layout.addStretch(1)

        tab_bar_frame = QFrame()
        tab_bar_frame.setObjectName("TabBar")
        tab_bar_frame.setStyleSheet(f"""
            QFrame#TabBar {{
                background-color: {t.raised};
                border: 1px solid {t.border};
                border-radius: 12px;
            }}
        """)
        tab_bar_layout = QHBoxLayout(tab_bar_frame)
        tab_bar_layout.setContentsMargins(4, 4, 4, 4)
        tab_bar_layout.setSpacing(4)

        self.tab_group = QButtonGroup(self.container)
        self.tab_group.setExclusive(True)
        self.tab_buttons: list[TopTabButton] = []
        for idx, text in enumerate(("Lịch sử hội thoại", "Cài đặt")):
            btn = TopTabButton(text, t)
            self.tab_group.addButton(btn, idx)
            tab_bar_layout.addWidget(btn)
            self.tab_buttons.append(btn)
        self.tab_group.idClicked.connect(self._switch_tab)
        header_layout.addWidget(tab_bar_frame)
        header_layout.addStretch(1)

        self.btn_min = WindowControlButton("min", t)
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_max = WindowControlButton("max", t)
        self.btn_max.clicked.connect(self.toggle_maximize)
        self.btn_close = WindowControlButton("close", t)
        self.btn_close.clicked.connect(self.close)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            header_layout.addWidget(b)

        container_layout.addWidget(self.header)

        # ── Pages ───────────────────────────────────────────────────
        self.stack = SlidingStackedWidget(self.container)
        self.transcript_panel = TranscriptPanel(self.session, self.settings, self.stack)
        self.transcript_panel.open_settings_requested.connect(lambda: self.set_tab(1))
        self.stack.addWidget(self.transcript_panel)
        self.settings_panel = SettingsPanel(self.settings, self.stack, bridge=self.bridge)
        self.stack.addWidget(self.settings_panel)
        container_layout.addWidget(self.stack, 1)

        self.header.installEventFilter(self)
        self.container.installEventFilter(self)

        use_custom = self.settings.data.ui.use_custom_fonts if self.settings else True
        apply_theme(self, t, use_custom)

        self.tab_buttons[tab_index].setChecked(True)
        self.stack.setCurrentIndex(tab_index)
        self.settings_panel.set_tab(settings_tab)
        self._sync_max_button()

    def _apply_container_style(self) -> None:
        radius = 0 if self.isMaximized() else RADIUS
        self.container.setStyleSheet(f"""
            QFrame#CentralContainer {{
                background-color: {self.theme.surface};
                border-radius: {radius}px;
                border: 1px solid {self.theme.border};
            }}
        """)

    # ─────────────────────────────────────────────── theme rebuild ──

    def _schedule_rebuild(self) -> None:
        # Deferred: the signal usually comes from a widget inside the page we
        # are about to delete.
        if not self._rebuild_pending:
            self._rebuild_pending = True
            QTimer.singleShot(0, self._rebuild)

    def _on_system_scheme_changed(self, *_args) -> None:
        if self.settings and self.settings.data.ui.theme == "auto":
            self._schedule_rebuild()

    def _rebuild(self) -> None:
        """Recreate all pages with the new theme.

        Widgets bake their colours into per-widget stylesheets at build time,
        so re-applying the global stylesheet alone left a half-old,
        half-new mix after switching dark/light.
        """
        self._rebuild_pending = False
        if self.settings:
            set_prefer_custom_fonts(self.settings.data.ui.use_custom_fonts)
        self.theme = get_theme(self.settings.data.ui.theme if self.settings else "dark")
        tab_index = self.stack.currentIndex() if self.container else 0
        settings_tab = self.settings_panel.current_tab() if self.container else 0
        old = self.container
        self.setUpdatesEnabled(False)
        try:
            if old is not None:
                self._main_layout.removeWidget(old)
                old.hide()
                old.deleteLater()
            self._build_ui(tab_index, settings_tab)
        finally:
            self.setUpdatesEnabled(True)
        self.update()

    # ─────────────────────────────────────────────── navigation ──

    def _switch_tab(self, idx: int) -> None:
        self.stack.slide_to_index(idx)

    def set_tab(self, idx: int) -> None:
        if 0 <= idx < len(self.tab_buttons):
            self.tab_buttons[idx].setChecked(True)
            self._switch_tab(idx)

    # ─────────────────────────────────────────────── window state ──

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _sync_max_button(self) -> None:
        if hasattr(self, "btn_max"):
            self.btn_max.maximized = self.isMaximized()
            self.btn_max.setToolTip("Thu về" if self.isMaximized() else "Phóng to")
            self.btn_max.update()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.WindowStateChange:
            # No shadow margin / rounded corners while maximized.
            m = 0 if self.isMaximized() else SHADOW
            self._main_layout.setContentsMargins(m, m, m, m)
            if self.container is not None:
                self._apply_container_style()
            self._sync_max_button()
        super().changeEvent(event)

    def paintEvent(self, _event) -> None:
        if self.isMaximized():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Alpha=1 fill: invisible, but makes the shadow margin hit-testable on
        # Windows (fully transparent pixels of a layered window are
        # click-through), which is what enables edge resizing.
        p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        card = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        strength = 34 if self.theme.name == "light" else 60
        p.setBrush(Qt.NoBrush)
        for i in range(1, SHADOW + 1):
            alpha = int(strength * (1.0 - i / (SHADOW + 1)) ** 2)
            if alpha <= 0:
                continue
            p.setPen(QPen(QColor(0, 0, 0, alpha), 1.0))
            r = card.adjusted(-i + 0.5, -i + 1.5, i - 0.5, i - 0.5)
            p.drawRoundedRect(r, RADIUS + i, RADIUS + i)
        p.end()

    # ─────────────────────────────────────────────── resize / move ──

    def _get_edge_at(self, pos: QPoint) -> str:
        """Which window edge(s) a point (window coords) is on: 'top-left', 'right', 'none'…"""
        if self.isMaximized():
            return "none"
        grip = SHADOW + 4
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        vert = "top" if y < grip else ("bottom" if y > h - grip else "")
        horiz = "left" if x < grip else ("right" if x > w - grip else "")
        edge = "-".join(part for part in (vert, horiz) if part)
        return edge or "none"

    def _set_cursor_for_edge(self, edge: str) -> None:
        cursors = {
            "left": Qt.SizeHorCursor,
            "right": Qt.SizeHorCursor,
            "top": Qt.SizeVerCursor,
            "bottom": Qt.SizeVerCursor,
            "top-left": Qt.SizeFDiagCursor,
            "bottom-right": Qt.SizeFDiagCursor,
            "top-right": Qt.SizeBDiagCursor,
            "bottom-left": Qt.SizeBDiagCursor,
        }
        cursor = cursors.get(edge)
        if cursor is None:
            self.unsetCursor()
        else:
            self.setCursor(cursor)

    @staticmethod
    def _get_edge_enum(edge_str: str) -> Qt.Edge:
        edges = Qt.Edges()
        if "left" in edge_str:
            edges |= Qt.LeftEdge
        if "right" in edge_str:
            edges |= Qt.RightEdge
        if "top" in edge_str:
            edges |= Qt.TopEdge
        if "bottom" in edge_str:
            edges |= Qt.BottomEdge
        return edges

    def eventFilter(self, watched, event) -> bool:
        etype = event.type()
        if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
            edge_str = self._get_edge_at(local_pos)
            if edge_str != "none" and self.windowHandle():
                self.windowHandle().startSystemResize(self._get_edge_enum(edge_str))
                return True

            header_bottom = self.header.mapTo(self, QPoint(0, self.header.height())).y()
            if local_pos.y() <= header_bottom and watched in (self.header, self.container, self):
                child = self.childAt(local_pos)
                if not isinstance(child, QPushButton) and self.windowHandle():
                    self.windowHandle().startSystemMove()
                    return True

        elif etype == QEvent.MouseButtonDblClick and watched is self.header:
            return False  # handled by HeaderBar.mouseDoubleClickEvent

        elif etype in (QEvent.MouseMove, QEvent.HoverMove) and watched is self:
            if not QApplication.mouseButtons():
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                self._set_cursor_for_edge(self._get_edge_at(pos))

        elif etype == QEvent.Leave and watched is self:
            self.unsetCursor()

        return super().eventFilter(watched, event)


def main() -> None:
    app = QApplication(sys.argv)
    from rtt.theme import load_custom_fonts

    load_custom_fonts()
    settings = AppSettings()
    session = TranscriptSession("en", "vi")
    session.add_entry("We call that gap the ear-voice span.", "Khoảng cách đó gọi là ear-voice span.")

    win = MainWindow(settings=settings, session=session)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
