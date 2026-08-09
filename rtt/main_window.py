"""Unified Main Application Window — Real-Time Translator.

Combines HUD, Transcript History, and Settings into a single 820x620px window
with a top horizontal navigation bar (Top Navigation Bar).
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt
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


class TopTabButton(QPushButton):
    """Top bar navigation tab button."""

    def __init__(self, text: str, theme: ThemeColors, parent=None):
        super().__init__(text, parent)
        self.theme = theme
        self.setFont(font_ui(10, QFont.Weight.Medium))
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
                    border: none;
                    border-radius: 8px;
                    padding: 0 16px;
                    font-weight: 600;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {self.theme.dim};
                    border: 1px solid transparent;
                    border-radius: 8px;
                    padding: 0 16px;
                }}
                QPushButton:hover {{
                    background-color: {self.theme.raised};
                    color: {self.theme.text};
                }}
            """)


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
        self.overlay_bridge = bridge
        self.theme = get_theme(settings.data.ui.theme if settings else "dark")
        self.drag_pos: Optional[QPoint] = None

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)
        self._resize_edge = "none"

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
                border-radius: 14px;
                border: 1px solid {self.theme.border};
            }}
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        main_layout.addWidget(self.container)

        # ── 1. Top Header Bar with Navigation Tabs ──────────────────
        self.header = QFrame(self.container)
        self.header.setFixedHeight(54)
        self.header.setStyleSheet(f"border-bottom: 1px solid {self.theme.border}; background: transparent;")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(12)

        # Logo badge & status dot
        self.dot = PulsingDot(self.theme.teal)
        header_layout.addWidget(self.dot)

        app_title = QLabel("Real-Time Translator")
        app_title.setFont(font_ui(11, QFont.Weight.DemiBold))
        app_title.setStyleSheet(f"color: {self.theme.text}; border: none;")
        header_layout.addWidget(app_title)

        header_layout.addStretch(1)

        # Segmented Top Navigation Tabs Bar
        tab_bar_frame = QFrame()
        tab_bar_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {self.theme.raised};
                border: 1px solid {self.theme.border};
                border-radius: 10px;
            }}
        """)
        tab_bar_layout = QHBoxLayout(tab_bar_frame)
        tab_bar_layout.setContentsMargins(4, 4, 4, 4)
        tab_bar_layout.setSpacing(4)

        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)

        tabs_info = [
            ("🎛️ Bảng điều khiển", 0),
            ("📜 Lịch sử hội thoại", 1),
            ("⚙️ Cài đặt", 2),
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

        # Window Controls: Minimize, Maximize/Restore, Close
        btn_min = QPushButton("─")
        btn_min.setFixedSize(28, 28)
        btn_min.setCursor(Qt.PointingHandCursor)
        btn_min.setStyleSheet(f"QPushButton {{ background: transparent; color: {self.theme.text}; border: none; border-radius: 14px; }} QPushButton:hover {{ background: {self.theme.border}; }}")
        btn_min.clicked.connect(self.showMinimized)
        header_layout.addWidget(btn_min)

        btn_max = QPushButton("□")
        btn_max.setFixedSize(28, 28)
        btn_max.setCursor(Qt.PointingHandCursor)
        btn_max.setStyleSheet(f"QPushButton {{ background: transparent; color: {self.theme.text}; border: none; border-radius: 14px; }} QPushButton:hover {{ background: {self.theme.border}; }}")
        btn_max.clicked.connect(self._toggle_maximize)
        header_layout.addWidget(btn_max)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {self.theme.text};
                border: none;
                border-radius: 14px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {self.theme.border};
            }}
        """)
        close_btn.clicked.connect(self.close)
        header_layout.addWidget(close_btn)

        container_layout.addWidget(self.header)

        # ── 2. Content Stack (3 Pages) ──────────────────────────────
        self.stack = QStackedWidget(self.container)

        # Page 0: HUD Panel
        self.hud_panel = HudPanel(self.settings, self.overlay_bridge, self.stack)
        self.stack.addWidget(self.hud_panel)

        # Page 1: Transcript Panel
        self.transcript_panel = TranscriptPanel(self.session, self.settings, self.stack)
        self.stack.addWidget(self.transcript_panel)

        # Page 2: Settings Panel
        self.settings_panel = SettingsPanel(self.settings, self.stack)
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

        apply_theme(self, self.theme)

    def _switch_tab(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)

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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            edge = self._get_edge_at(event.pos())
            if edge != "none":
                self._resize_edge = edge
                self._start_mouse_pos = event.globalPosition().toPoint()
                self._start_geom = QRect(self.geometry())
                event.accept()
                return
            elif event.pos().y() <= 54:
                self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.pos()
        global_pos = event.globalPosition().toPoint()

        # Update cursor when hovering over edges
        if not event.buttons():
            edge = self._get_edge_at(pos)
            self._set_cursor_for_edge(edge)
            return

        if event.buttons() == Qt.LeftButton:
            # Resizing window
            if getattr(self, "_resize_edge", "none") != "none":
                dx = global_pos.x() - self._start_mouse_pos.x()
                dy = global_pos.y() - self._start_mouse_pos.y()
                g = QRect(self._start_geom)

                min_w = self.minimumWidth()
                min_h = self.minimumHeight()

                edge = self._resize_edge

                if "left" in edge:
                    new_w = max(min_w, g.width() - dx)
                    g.setLeft(g.right() - new_w)
                if "right" in edge:
                    g.setWidth(max(min_w, g.width() + dx))
                if "top" in edge:
                    new_h = max(min_h, g.height() - dy)
                    g.setTop(g.bottom() - new_h)
                if "bottom" in edge:
                    g.setHeight(max(min_h, g.height() + dy))

                self.setGeometry(g)
                event.accept()
                return

            # Header dragging
            if self.drag_pos is not None:
                self.move(global_pos - self.drag_pos)
                event.accept()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self.drag_pos = None
        self._resize_edge = "none"
        self.setCursor(Qt.ArrowCursor)


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
