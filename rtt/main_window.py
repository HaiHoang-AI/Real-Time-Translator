"""Unified Main Application Window — Real-Time Translator.

Combines HUD, Transcript History, and Settings into a single 820x620px window
with a top horizontal navigation bar (Top Navigation Bar).
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from rtt.history import TranscriptSession
from rtt.hud import HudPanel, PulsingDot
from rtt.overlay import OverlayBridge
from rtt.settings import AppSettings
from rtt.settings_ui import SettingsPanel
from rtt.theme import (
    DARK,
    ThemeColors,
    apply_theme,
    font_mono as _font_mono_str,
    font_ui as _font_ui_str,
    get_theme,
)
from rtt.transcript_ui import TranscriptPanel


def font_ui(pt_size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return QFont(_font_ui_str(), pt_size, weight)


def font_mono(pt_size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return QFont(_font_mono_str(), pt_size, weight)


from rtt.motion import ElasticButton, SlidingStackedWidget


class TopTabButton(ElasticButton):
    """Top bar navigation tab button with spring physics scaling and claymorphic styling."""

    def __init__(self, text: str, theme: ThemeColors, parent=None):
        super().__init__(text, parent)
        self.theme = theme
        self.setFont(font_ui(10, QFont.Weight.DemiBold))
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setFixedHeight(34)
        self.update_style(False)
        self.toggled.connect(self.update_style)

    def update_style(self, checked: bool = False) -> None:
        if checked:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.theme.accent};
                    color: {self.theme.accent_text};
                    border: 1.5px solid {self.theme.border_chunky};
                    border-radius: 9px;
                    padding: 0 16px;
                    font-weight: 700;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {self.theme.dim};
                    border: 1.5px solid transparent;
                    border-radius: 9px;
                    padding: 0 16px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {'rgba(0,0,0,0.05)' if self.theme.name == 'light' else 'rgba(255,255,255,0.06)'};
                    color: {self.theme.text};
                }}
            """)


class HeaderBar(QFrame):
    """Top titlebar area that triggers window move when clicked or dragged."""

    def __init__(self, main_win: QWidget, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.drag_pos: Optional[QPoint] = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            child = self.childAt(event.pos())
            if isinstance(child, (QPushButton, TopTabButton)):
                super().mousePressEvent(event)
                return

            if self.main_win.windowHandle():
                self.main_win.windowHandle().startSystemMove()
                event.accept()
                return

            self.drag_pos = event.globalPosition().toPoint() - self.main_win.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.LeftButton and self.drag_pos is not None:
            self.main_win.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.drag_pos = None
        super().mouseReleaseEvent(event)


class MainWindow(QWidget):
    """Single unified control window containing HUD, Transcript, and Settings tabs."""

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
        self.theme = get_theme(settings.data.ui.theme if settings else "dark")
        self.drag_pos: Optional[QPoint] = None

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(680, 500)
        self.setMouseTracking(True)
        self._resize_edge = "none"

        from pathlib import Path
        from PySide6.QtGui import QImage, QPixmap
        icon_path = Path(__file__).parent.parent / "rtt_icon.ico"
        if icon_path.exists():
            src_img = QImage(str(icon_path))
            if not src_img.isNull():
                ico = QIcon()
                for s in (16, 24, 32, 48, 64, 128, 256):
                    scaled = src_img.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    ico.addPixmap(QPixmap.fromImage(scaled))
                self.setWindowIcon(ico)
            else:
                self.setWindowIcon(QIcon(str(icon_path)))

        self._setup_ui()
        if self.settings:
            self.settings.changed.connect(self._on_settings_changed)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)

        self.container = QFrame(self)
        self.container.setObjectName("CentralContainer")
        self.container.setStyleSheet(f"""
            QFrame#CentralContainer {{
                background-color: {self.theme.surface};
                border-radius: 18px;
                border: 2px solid {self.theme.border_chunky};
            }}
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        main_layout.addWidget(self.container)

        # ── 1. Top Header Bar with Navigation Tabs & Pill Badge ─────
        self.header = HeaderBar(self, self.container)
        self.header.setFixedHeight(54)
        self.header.setStyleSheet(f"border-bottom: 1.5px solid {self.theme.border_strong}; background: transparent;")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 0, 12, 0)
        header_layout.setSpacing(12)

        # App Brand
        brand_box = QFrame()
        brand_box.setStyleSheet("background: transparent; border: none;")
        brand_layout = QHBoxLayout(brand_box)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(8)

        app_title = QLabel("Real-Time Translator")
        app_title.setFont(font_ui(12, QFont.Weight.Bold))
        app_title.setStyleSheet(f"color: {self.theme.text}; border: none;")
        app_title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        brand_layout.addWidget(app_title)

        header_layout.addWidget(brand_box)
        header_layout.addStretch(1)

        # Segmented Top Navigation Tabs Bar
        tab_bar_frame = QFrame()
        tab_bar_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {self.theme.raised};
                border: 1.5px solid {self.theme.border_strong};
                border-radius: 12px;
            }}
        """)
        tab_bar_layout = QHBoxLayout(tab_bar_frame)
        tab_bar_layout.setContentsMargins(4, 4, 4, 4)
        tab_bar_layout.setSpacing(4)

        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)

        tabs_info = [
            ("Lịch sử hội thoại", 0),
            ("Cài đặt", 1),
        ]

        self.tab_buttons = []
        for text, idx in tabs_info:
            btn = TopTabButton(text, self.theme)
            self.tab_group.addButton(btn, idx)
            tab_bar_layout.addWidget(btn)
            self.tab_buttons.append(btn)

        self.tab_buttons[0].setChecked(True)
        self.tab_group.idClicked.connect(self._switch_tab)
        header_layout.addWidget(tab_bar_frame)

        header_layout.addStretch(1)

        # Window Controls: Minimize, Maximize/Restore, Close (Playful Chunky Style)
        _wc_style = lambda hover_bg=self.theme.raised, hover_color=self.theme.accent: f"""
            QPushButton {{
                background-color: transparent;
                color: {self.theme.dim};
                border: 1.5px solid transparent;
                border-radius: 8px;
                font-family: 'Segoe UI', 'Segoe UI Symbol', Arial, sans-serif;
                font-size: 15px;
                font-weight: bold;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border-color: {self.theme.border_strong};
                color: {hover_color};
            }}
        """

        btn_min = QPushButton("─")
        btn_min.setFixedSize(34, 30)
        btn_min.setCursor(Qt.PointingHandCursor)
        btn_min.setStyleSheet(_wc_style())
        btn_min.clicked.connect(self.showMinimized)
        header_layout.addWidget(btn_min)

        btn_max = QPushButton("□")
        btn_max.setFixedSize(34, 30)
        btn_max.setCursor(Qt.PointingHandCursor)
        btn_max.setStyleSheet(_wc_style())
        btn_max.clicked.connect(self._toggle_maximize)
        header_layout.addWidget(btn_max)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(34, 30)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(_wc_style(hover_bg="#FEE2E2" if self.theme.name == "light" else "#451A1A", hover_color=self.theme.error))
        close_btn.clicked.connect(self.close)
        header_layout.addWidget(close_btn)

        container_layout.addWidget(self.header)

        # ── 2. Content Stack (2 Pages) ──────────────────────────────
        self.stack = SlidingStackedWidget(self.container)

        # Page 0: Transcript Panel
        self.transcript_panel = TranscriptPanel(self.session, self.settings, self.stack)
        self.stack.addWidget(self.transcript_panel)

        # Page 1: Settings Panel
        self.settings_panel = SettingsPanel(self.settings, self.stack, bridge=self.bridge)
        self.stack.addWidget(self.settings_panel)

        container_layout.addWidget(self.stack, 1)

        # Bottom-right QSizeGrip for smooth resize
        grip_layout = QHBoxLayout()
        grip_layout.setContentsMargins(0, 0, 4, 4)
        grip_layout.addStretch(1)
        grip = QSizeGrip(self)
        grip.setFixedSize(14, 14)
        grip_layout.addWidget(grip)
        container_layout.addLayout(grip_layout)

        self.header.installEventFilter(self)
        self.container.installEventFilter(self)
        self.installEventFilter(self)

        apply_theme(self, self.theme)

    def _switch_tab(self, idx: int) -> None:
        self.stack.slide_to_index(idx)

    def set_tab(self, idx: int) -> None:
        if 0 <= idx < len(self.tab_buttons):
            self.tab_buttons[idx].setChecked(True)
            self._switch_tab(idx)

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _on_settings_changed(self) -> None:
        if self.settings:
            self.theme = get_theme(self.settings.data.ui.theme)
            apply_theme(self, self.theme)

    def _get_edge_enum(self, edge_str: str) -> Qt.Edge:
        edges = Qt.Edges()
        if "left" in edge_str: edges |= Qt.LeftEdge
        if "right" in edge_str: edges |= Qt.RightEdge
        if "top" in edge_str: edges |= Qt.TopEdge
        if "bottom" in edge_str: edges |= Qt.BottomEdge
        return edges

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            global_pos = event.globalPosition().toPoint()
            local_pos = self.mapFromGlobal(global_pos)
            edge_str = self._get_edge_at(local_pos)

            if edge_str != "none":
                qt_edge = self._get_edge_enum(edge_str)
                if self.windowHandle():
                    self.windowHandle().startSystemResize(qt_edge)
                    return True

            if local_pos.y() <= 54:
                child = self.childAt(local_pos)
                if not isinstance(child, (QPushButton, TopTabButton)):
                    if self.windowHandle():
                        self.windowHandle().startSystemMove()
                        return True

        elif event.type() == QEvent.MouseMove:
            if not event.buttons():
                global_pos = event.globalPosition().toPoint()
                local_pos = self.mapFromGlobal(global_pos)
                edge_str = self._get_edge_at(local_pos)
                self._set_cursor_for_edge(edge_str)

        return super().eventFilter(watched, event)


def main() -> None:
    app = QApplication(sys.argv)
    settings = AppSettings()
    session = TranscriptSession("en", "vi")
    session.add_entry("We call that gap the ear-voice span.", "Khoảng cách đó gọi là ear-voice span.")

    win = MainWindow(settings=settings, session=session)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
