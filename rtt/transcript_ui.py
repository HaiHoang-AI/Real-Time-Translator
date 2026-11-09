"""Transcript Panel & Window UI — Real-time conversation history logger & session manager.

Features:
- Left Sidebar with Claude-style minimal design (Pinned, Chats, bullet indicators).
- Cross-session search across all past sessions and transcripts.
- Multi-session selection for Gemini AI Summarization.
- In-session pause/resume controls (Tạm dừng / Tiếp tục).
- Export to .srt, .txt, .md.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rtt.history import SessionManager, TranscriptEntry, TranscriptSession
from rtt.motion import ElasticButton, HoverLiftFrame
from rtt.settings import AppSettings
from rtt.summarizer import SummarizeWorker
from rtt.theme import (
    DARK,
    ThemeColors,
    apply_theme,
    font_mono as _font_mono_str,
    font_ui as _font_ui_str,
    get_theme,
)


def font_ui(pt_size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return QFont(_font_ui_str(), pt_size, weight)


def font_mono(pt_size: int = 10, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return QFont(_font_mono_str(), pt_size, weight)


# ───────────────────────────────────── Item Widget ───────────────────

class TranscriptEntryWidget(HoverLiftFrame):
    """Single speech card row in the transcript list."""

    def __init__(self, entry: TranscriptEntry, theme: ThemeColors = DARK, is_latest: bool = False, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.theme = theme
        self.is_latest = is_latest
        self.src_lbl: Optional[QLabel] = None
        self.tgt_lbl: Optional[QLabel] = None
        self._build()
        self._restyle()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 16, 11)
        layout.setSpacing(12)

        # Time badge pill
        st = getattr(self.entry, 'start_time_s', 0.0)
        time_str = getattr(self.entry, 'time_str', '') or f"{(int(st)//60):02d}:{(int(st)%60):02d}"
        self.time_lbl = QLabel(time_str)
        self.time_lbl.setObjectName("TimePill")
        # The global QSS font-size overrides setFont(), so the pill font is set
        # in its stylesheet (see _restyle) and measured with the same font.
        pill_font = QFont(_font_mono_str())
        pill_font.setPixelSize(11)
        pill_font.setWeight(QFont.Weight.Medium)
        self.time_lbl.setFont(pill_font)
        # Same width for every card so the text column lines up.
        sample = "88:88:88" if len(time_str) > 5 else "88:88"
        self.time_lbl.setFixedWidth(QFontMetrics(pill_font).horizontalAdvance(sample) + 18)
        self.time_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.time_lbl, 0, Qt.AlignTop)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(3)

        if self.entry.source_text:
            self.src_lbl = QLabel(self.entry.source_text)
            self.src_lbl.setObjectName("SrcText")
            self.src_lbl.setFont(font_ui(9, QFont.Weight.Medium))
            self.src_lbl.setWordWrap(True)
            self.src_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            content_layout.addWidget(self.src_lbl)

        if self.entry.target_text:
            self.tgt_lbl = QLabel(self.entry.target_text)
            self.tgt_lbl.setObjectName("TgtText")
            self.tgt_lbl.setWordWrap(True)
            self.tgt_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            content_layout.addWidget(self.tgt_lbl)

        layout.addLayout(content_layout, 1)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    def set_latest(self, latest: bool) -> None:
        """Restyle in place (the old code re-ran setup_ui() on a widget that
        already had a layout, leaking orphan widgets on every new sentence)."""
        if latest != self.is_latest:
            self.is_latest = latest
            self._restyle()

    def _restyle(self) -> None:
        t = self.theme
        is_dark = t.name == "dark"
        bg_col = "#1E222D" if is_dark else "#FFFFFF"
        idle_border = "rgba(255,255,255,0.06)" if is_dark else "rgba(0,0,0,0.07)"
        hover_border = "rgba(255,255,255,0.16)" if is_dark else "rgba(0,0,0,0.16)"
        border_col = t.accent if self.is_latest else idle_border
        time_bg = t.pill_bg if self.is_latest else t.raised
        time_color = t.accent if self.is_latest else t.dim
        self.setStyleSheet(f"""
            TranscriptEntryWidget {{
                background-color: {bg_col};
                border: 1px solid {border_col};
                border-radius: 12px;
            }}
            TranscriptEntryWidget:hover {{
                border-color: {t.accent if self.is_latest else hover_border};
            }}
            QLabel#TimePill {{
                background-color: {time_bg};
                color: {time_color};
                border: 1px solid {t.border};
                border-radius: 8px;
                padding: 2px 0px;
                font-family: '{_font_mono_str()}', 'Consolas', monospace;
                font-size: 11px;
                font-weight: 500;
            }}
            QLabel#SrcText {{ color: {t.teal}; background: transparent; }}
            QLabel#TgtText {{ color: {t.text}; background: transparent; }}
        """)
        if self.tgt_lbl is not None:
            weight = QFont.Weight.Bold if self.is_latest else QFont.Weight.DemiBold
            self.tgt_lbl.setFont(font_ui(10.5, weight))

    def _show_menu(self, pos) -> None:
        menu = QMenu(self)
        if self.entry.target_text:
            menu.addAction("Sao chép bản dịch").triggered.connect(
                lambda: QApplication.clipboard().setText(self.entry.target_text)
            )
        if self.entry.source_text:
            menu.addAction("Sao chép câu gốc").triggered.connect(
                lambda: QApplication.clipboard().setText(self.entry.source_text)
            )
        if self.entry.source_text and self.entry.target_text:
            menu.addAction("Sao chép cả hai").triggered.connect(
                lambda: QApplication.clipboard().setText(
                    f"{self.entry.source_text}\n{self.entry.target_text}"
                )
            )
        if not menu.isEmpty():
            menu.exec(self.mapToGlobal(pos))


class FormatButton(ElasticButton):
    def __init__(self, text, theme):
        super().__init__(text)
        self.theme = theme
        self.setFont(font_ui(9, QFont.Weight.Medium))
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setFixedHeight(28)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.raised};
                color: {theme.dim};
                border: 1px solid {theme.border};
                border-radius: 7px;
                padding: 0 10px;
            }}
            QPushButton:hover {{ color: {theme.text}; }}
            QPushButton:checked {{
                background-color: {theme.accent};
                color: {theme.accent_text};
                border: 1px solid {theme.accent};
            }}
        """)


class ToggleCheckBox(QWidget):
    """Small labelled switch (the old QCheckBox indicator was a knob-less pill)."""

    toggled = Signal(bool)

    def __init__(self, text, theme):
        super().__init__()
        from rtt.settings_ui import ToggleSwitch

        self.theme = theme
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        self.switch = ToggleSwitch(theme)
        self.switch.setFixedSize(34, 19)
        self.switch.toggled.connect(self.toggled.emit)
        lbl = QLabel(text)
        lbl.setFont(font_ui(8.5))
        lbl.setStyleSheet(f"color: {theme.text}; background: transparent;")
        lay.addWidget(self.switch)
        lay.addWidget(lbl)
        lay.addStretch(1)

    def isChecked(self) -> bool:
        return self.switch.isChecked()

    def setChecked(self, checked: bool) -> None:
        self.switch.setChecked(checked)


class ElidedLabel(QLabel):
    """Single-line label that ends with '…' instead of being cut mid-glyph."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        avail = max(10, self.contentsRect().width())
        super().setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, avail))


# ────────────────────────────── Modern Sidebar Components ────────────

class SidebarIconButton(QPushButton):
    """Small sleek top header icon button for sidebar."""
    def __init__(self, text: str, theme: ThemeColors, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.icon_text = text
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        is_dark = (getattr(self.theme, 'name', '') == 'dark')
        hovered = self.underMouse()

        # Hover background
        if hovered:
            bg_color = QColor(255, 255, 255, 20) if is_dark else QColor(0, 0, 0, 16)
            painter.setBrush(bg_color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(self.rect()), 6, 6)

        # Vector icons: the ≡ / ⌕ glyphs depended on Segoe UI Symbol and
        # rendered as nothing when that font was missing.
        color = QColor(self.theme.accent) if hovered else QColor(self.theme.text if is_dark else "#334155")
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self.icon_text == "≡":  # menu / sidebar toggle
            for dy in (-4.5, 0.0, 4.5):
                painter.drawLine(QPointF(cx - 6, cy + dy), QPointF(cx + 6, cy + dy))
        elif self.icon_text == "⌕":  # search
            painter.drawEllipse(QPointF(cx - 1.5, cy - 1.5), 4.6, 4.6)
            painter.drawLine(QPointF(cx + 2.0, cy + 2.0), QPointF(cx + 6.0, cy + 6.0))
        else:
            painter.drawText(self.rect(), Qt.AlignCenter, self.icon_text)
        painter.end()


class SidebarActionItemWidget(QPushButton):
    """Row item button for action menu items like + New, Projects, Artifacts, Customize."""
    def __init__(self, icon_str: str, text_str: str, theme: ThemeColors, is_selected: bool = False, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.is_selected = is_selected
        self.is_new_btn = (icon_str == "+" or text_str.lower() in ("new", "tạo mới", "phiên mới"))
        self.setText(f"{icon_str}  {text_str}")
        self.setFont(font_ui(9.5, QFont.Weight.Bold if self.is_new_btn else QFont.Weight.DemiBold))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34 if self.is_new_btn else 30)
        self._update_style()

    def _update_style(self):
        is_dark = (getattr(self.theme, 'name', '') == 'dark')
        if self.is_new_btn:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.theme.cta_bg};
                    color: {self.theme.cta_text};
                    border: none;
                    border-radius: 9px;
                    padding: 0 12px;
                    text-align: center;
                    font-weight: 700;
                }}
                QPushButton:hover {{
                    background-color: {self.theme.cta_hover};
                }}
            """)
            return

        if self.is_selected:
            bg = "#2B2F3D" if is_dark else "#E2DDD3"
            text_color = self.theme.accent
            font_w = "bold"
        else:
            bg = "transparent"
            text_color = self.theme.text if is_dark else "#2D3748"
            font_w = "600"

        hover_bg = "#242835" if is_dark else "#EFEAE1"

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {text_color};
                border: none;
                border-radius: 8px;
                padding: 0 10px;
                text-align: left;
                font-weight: {font_w};
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
                border: none;
            }}
        """)


class SidebarSectionHeaderWidget(QWidget):
    """Header row for sections like 'Projects', 'Pinned', 'Chats' with action button on right."""
    action_clicked = Signal()

    def __init__(self, title: str, action_icon: str = "", theme: ThemeColors = DARK, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Otherwise the global "QWidget { background: surface }" painted a
        # lighter strip behind each section title in the darker sidebar.
        self.setStyleSheet("SidebarSectionHeaderWidget { background: transparent; }")
        self.theme = theme
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 10, 4, 4)
        layout.setSpacing(4)

        lbl = QLabel(title)
        lbl.setFont(font_ui(8.5, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {self.theme.dim}; border: none;")
        layout.addWidget(lbl, 1)

        if action_icon:
            btn = QPushButton(action_icon)
            btn.setFixedSize(20, 20)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {self.theme.dim};
                    border: none;
                    font-size: 13px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    color: {self.theme.text};
                }}
            """)
            btn.clicked.connect(self.action_clicked.emit)
            layout.addWidget(btn)


class ClaudeSubItemWidget(QWidget):
    """Indented sub-item widget for nested list items."""
    def __init__(self, text: str, theme: ThemeColors = DARK, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.theme = theme
        self.setFixedHeight(26)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 1, 4, 1)
        layout.setSpacing(6)

        bullet = QLabel("o")
        bullet.setFont(font_ui(8))
        bullet.setStyleSheet(f"color: {self.theme.dim}; background: transparent; border: none;")
        layout.addWidget(bullet)

        lbl = QLabel(text)
        lbl.setFont(font_ui(8.5))
        lbl.setStyleSheet(f"color: {self.theme.dim}; background: transparent; border: none;")
        layout.addWidget(lbl, 1)

        is_dark = getattr(self.theme, 'name', 'dark') == 'dark'
        hover_bg = "#302A24" if is_dark else "#ECE6DB"
        self.setStyleSheet(f"""
            ClaudeSubItemWidget {{
                background-color: transparent;
                border-radius: 5px;
            }}
            ClaudeSubItemWidget:hover {{
                background-color: {hover_bg};
            }}
        """)


class SidebarFooterWidget(QWidget):
    """Bottom footer bar showing user profile, avatar, and download icon."""
    def __init__(self, username: str = "Hoàng-kun · Free", avatar_char: str = "H", theme: ThemeColors = DARK, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.theme = theme
        self.setFixedHeight(44)
        self.setup_ui(username, avatar_char)

    def setup_ui(self, username: str, avatar_char: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # Avatar circle
        avatar_lbl = QLabel(avatar_char)
        avatar_lbl.setFixedSize(26, 26)
        avatar_lbl.setAlignment(Qt.AlignCenter)
        avatar_lbl.setFont(font_ui(9, QFont.Weight.Bold))
        is_dark = getattr(self.theme, 'name', 'dark') == 'dark'
        avatar_bg = "#332D27" if is_dark else "#E2DDD3"
        avatar_fg = "#F0EBE3" if is_dark else "#201C17"
        avatar_lbl.setStyleSheet(f"""
            background-color: {avatar_bg};
            color: {avatar_fg};
            border-radius: 13px;
            border: none;
        """)
        layout.addWidget(avatar_lbl)

        # Username & Plan text
        user_lbl = QLabel(f"{username} ˅")
        user_lbl.setFont(font_ui(8.5, QFont.Weight.DemiBold))
        user_lbl.setStyleSheet(f"color: {self.theme.text}; background: transparent; border: none;")
        layout.addWidget(user_lbl, 1)

        # Right download icon
        dl_btn = QPushButton("⤓")
        dl_btn.setFixedSize(22, 22)
        dl_btn.setCursor(Qt.PointingHandCursor)
        dl_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {self.theme.dim};
                border: none;
                font-size: 13px;
            }}
            QPushButton:hover {{
                color: {self.theme.text};
            }}
        """)
        layout.addWidget(dl_btn)


# ────────────────────────────── Claude Minimal Session Item ────────────

class CloseIconButton(QPushButton):
    """Small round button with a vector × (the '✕' glyph rendered empty)."""

    def __init__(self, theme: ThemeColors, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hovered = self.underMouse()
        if hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.theme.raised))
            p.drawEllipse(QRectF(1, 1, 24, 24))
        pen = QPen(QColor(self.theme.text if hovered else self.theme.dim), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(9, 9, 17, 17)
        p.drawLine(17, 9, 9, 17)
        p.end()


class SelectCircle(QPushButton):
    """Vector selection circle: outline when idle, filled check when selected."""

    def __init__(self, theme: ThemeColors, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._checked = False
        self.setFixedSize(18, 18)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def set_checked(self, checked: bool) -> None:
        self._checked = checked
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(3.5, 3.5, 11, 11)
        if self._checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.theme.accent))
            p.drawEllipse(r)
            pen = QPen(QColor(self.theme.accent_text), 1.6)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(6.4, 9.2)
            path.lineTo(8.3, 11.0)
            path.lineTo(11.8, 7.3)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        else:
            col = QColor(self.theme.accent if self.underMouse() else self.theme.dim)
            p.setPen(QPen(col, 1.3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r)
        p.end()


class ClaudeSessionItemWidget(QWidget):
    """Minimal Claude-style session row with circle bullet, hover lift, and inline edit."""

    clicked = Signal(str)                # session_id
    checked_toggled = Signal(str, bool)  # session_id, checked
    renamed = Signal(str, str)           # session_id, new_name
    pin_toggled = Signal(str, bool)      # session_id, is_pinned
    deleted = Signal(str)                # session_id

    def __init__(
        self,
        session_info: dict,
        is_active: bool = False,
        theme: ThemeColors = DARK,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.info = session_info
        self.session_id = session_info["session_id"]
        self.is_active = is_active
        self.theme = theme
        self.is_checked = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self.setup_ui()

    def setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        # Selection circle (click / Ctrl+click to pick sessions for AI summary)
        self.bullet_btn = SelectCircle(self.theme)
        self.bullet_btn.setToolTip("Chọn phiên để tóm tắt / xoá nhiều phiên")
        self.bullet_btn.clicked.connect(self._toggle_check)
        layout.addWidget(self.bullet_btn)

        # Session Title
        title_text = self.info.get("title", f"Phiên {self.session_id}")
        self.title_lbl = ElidedLabel(title_text)
        self.title_lbl.setWordWrap(False)
        sentences = self.info.get("sentences", 0)
        start_dt = self.info.get("start_dt")
        when = start_dt.strftime("%d/%m/%Y %H:%M") if start_dt else ""
        self.setToolTip(
            f"{title_text}\n{when} · {sentences} câu · {self.info.get('duration_str', '')}\n"
            "Nhấp đúp để đổi tên · Chuột phải để ghim / xoá"
        )
        weight = QFont.Weight.DemiBold if self.is_active else QFont.Weight.Normal
        self.title_lbl.setFont(font_ui(9, weight))
        title_color = self.theme.text if self.is_active else self.theme.dim
        self.title_lbl.setStyleSheet(f"color: {title_color}; background: transparent; border: none;")
        layout.addWidget(self.title_lbl, 1)

        # Inline Rename LineEdit
        self.rename_edit = QLineEdit(title_text)
        self.rename_edit.setFont(font_ui(9))
        self.rename_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {self.theme.surface};
                color: {self.theme.text};
                border: 1px solid {self.theme.accent};
                border-radius: 4px;
                padding: 1px 4px;
            }}
        """)
        self.rename_edit.hide()
        # Return *or* clicking elsewhere commits (returnPressed alone left the
        # editor stuck open when focus moved away).
        self.rename_edit.editingFinished.connect(self._finish_rename)
        layout.addWidget(self.rename_edit, 1)

        self._update_style()

    def _update_style(self) -> None:
        is_dark = (getattr(self.theme, 'name', '') == 'dark')
        if self.is_active:
            active_bg = "rgba(16, 185, 129, 0.15)" if is_dark else "#DCFCE7"
            self.setStyleSheet(f"""
                ClaudeSessionItemWidget {{
                    background-color: {active_bg};
                    border: none;
                    border-radius: 8px;
                }}
            """)
            self.title_lbl.setStyleSheet(f"color: {self.theme.text}; font-weight: bold; background: transparent; border: none;")
        else:
            hover_bg = "#242835" if is_dark else "#EFEAE1"
            self.setStyleSheet(f"""
                ClaudeSessionItemWidget {{
                    background-color: transparent;
                    border: none;
                    border-radius: 8px;
                }}
                ClaudeSessionItemWidget:hover {{
                    background-color: {hover_bg};
                    border: none;
                }}
            """)
            self.title_lbl.setStyleSheet(f"color: {self.theme.dim}; font-weight: 500; background: transparent; border: none;")

    def set_checked(self, checked: bool) -> None:
        self.is_checked = checked
        self.bullet_btn.set_checked(checked)

    def _toggle_check(self) -> None:
        self.set_checked(not self.is_checked)
        self.checked_toggled.emit(self.session_id, self.is_checked)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            if event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                self._toggle_check()
            else:
                self.clicked.emit(self.session_id)
        elif event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._start_rename()
        super().mouseDoubleClickEvent(event)

    def _start_rename(self) -> None:
        self.title_lbl.hide()
        self.rename_edit.setText(self.info.get("title", ""))
        self.rename_edit.show()
        self.rename_edit.setFocus()
        self.rename_edit.selectAll()

    def _cancel_rename(self) -> None:
        self.rename_edit.hide()
        self.title_lbl.show()

    def _finish_rename(self) -> None:
        if self.rename_edit.isHidden():
            return
        new_text = self.rename_edit.text().strip()
        if new_text and new_text != self.info.get("title"):
            self.info["title"] = new_text
            self.title_lbl.setText(new_text)
            self.renamed.emit(self.session_id, new_text)
        self.rename_edit.hide()
        self.title_lbl.show()

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {self.theme.surface};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 8px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 16px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {self.theme.raised};
                color: {self.theme.accent};
            }}
        """)

        is_pinned = self.info.get("is_pinned", False)
        pin_action = QAction("Bỏ ghim" if is_pinned else "Ghim phiên", self)
        pin_action.triggered.connect(lambda: self.pin_toggled.emit(self.session_id, not is_pinned))
        menu.addAction(pin_action)

        rename_action = QAction("Đổi tên", self)
        rename_action.triggered.connect(self._start_rename)
        menu.addAction(rename_action)

        menu.addSeparator()

        del_action = QAction("Xoá phiên", self)
        del_action.triggered.connect(lambda: self.deleted.emit(self.session_id))
        menu.addAction(del_action)

        menu.exec(pos)


# ─────────────────────────────── Summary Modal Dialog ─────────────────

class SummaryDialog(QDialog):
    """Modal dialog displaying the AI generated summary."""

    def __init__(self, summary_text: str = "", theme: ThemeColors = DARK, parent=None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.summary_text = summary_text
        self.setWindowTitle("Tóm tắt phiên bằng AI")
        self.setMinimumSize(560, 440)
        self.resize(640, 500)
        self.setup_ui()

    def setup_ui(self) -> None:
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {self.theme.surface};
                color: {self.theme.text};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header Title
        title_lbl = QLabel("Tóm tắt nội dung phiên")
        title_lbl.setFont(font_ui(12, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {self.theme.text}; border: none;")
        layout.addWidget(title_lbl)

        # Text Display Box
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setFont(font_ui(10))
        self.text_area.setPlainText(self.summary_text)
        self.text_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {self.theme.bg};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 10px;
                padding: 14px;
                line-height: 1.5;
            }}
        """)
        layout.addWidget(self.text_area, 1)

        # Action Buttons (No emoji icons)
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        copy_btn = ElasticButton("Sao chép")
        copy_btn.setFont(font_ui(9, QFont.Weight.DemiBold))
        copy_btn.setFixedHeight(34)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 7px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                border-color: {self.theme.accent};
                color: {self.theme.accent};
            }}
        """)
        copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_bar.addWidget(copy_btn)

        save_md_btn = ElasticButton("Lưu .md")
        save_md_btn.setFont(font_ui(9, QFont.Weight.DemiBold))
        save_md_btn.setFixedHeight(34)
        save_md_btn.setCursor(Qt.PointingHandCursor)
        save_md_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 7px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                border-color: {self.theme.accent};
                color: {self.theme.accent};
            }}
        """)
        save_md_btn.clicked.connect(self._save_to_file)
        btn_bar.addWidget(save_md_btn)

        btn_bar.addStretch()

        close_btn = ElasticButton("Đóng")
        close_btn.setFont(font_ui(9, QFont.Weight.DemiBold))
        close_btn.setFixedHeight(34)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.accent};
                color: {self.theme.accent_text};
                border: none;
                border-radius: 7px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        close_btn.clicked.connect(self.accept)
        btn_bar.addWidget(close_btn)

        layout.addLayout(btn_bar)

    def set_content(self, text: str) -> None:
        self.summary_text = text
        self.text_area.setPlainText(text)

    def _copy_to_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text_area.toPlainText())
        QMessageBox.information(self, "Đã sao chép", "Đã sao chép nội dung tóm tắt vào bộ nhớ tạm!")

    def _save_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu tóm tắt",
            f"tom_tat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
            "Markdown (*.md)",
        )
        if path:
            try:
                Path(path).write_text(self.text_area.toPlainText(), encoding="utf-8")
                QMessageBox.information(self, "Đã lưu", f"Đã lưu bản tóm tắt tại:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể lưu file: {e}")



# ───────────────────────────────────── New Session Dialog ──────────────

class NewSessionDialog(QDialog):
    """Modern modal dialog prompting user for video name / meeting topic to prime AI context."""

    def __init__(self, parent=None, theme: Optional[ThemeColors] = None, default_name: str = ""):
        super().__init__(parent)
        self.theme = theme or DARK
        self.setWindowTitle("Tạo Phiên Dịch Mới")
        self.setFixedWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {self.theme.bg};
                color: {self.theme.text};
                border-radius: 12px;
            }}
            QLabel {{
                color: {self.theme.text};
            }}
            QLineEdit {{
                background-color: {self.theme.surface};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1px solid {self.theme.teal};
            }}
            QPushButton {{
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 500;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # Header
        header_lbl = QLabel("Tạo Phiên Dịch Mới")
        header_lbl.setFont(font_ui(12, QFont.Weight.Bold))
        header_lbl.setStyleSheet(f"color: {self.theme.text};")
        layout.addWidget(header_lbl)

        # Description / Tip
        tip_lbl = QLabel(
            "<b>Mẹo dịch chuẩn:</b> Nhập tên video, phim hoặc nội dung cuộc họp để mô hình AI "
            "hiểu đúng ngữ cảnh, tự động xưng hô chuẩn và dịch đúng thuật ngữ chuyên ngành."
        )
        tip_lbl.setWordWrap(True)
        tip_lbl.setFont(font_ui(9))
        tip_lbl.setStyleSheet(f"color: {self.theme.dim}; line-height: 1.4;")
        layout.addWidget(tip_lbl)

        # Input
        self.input_field = QLineEdit(self)
        self.input_field.setPlaceholderText("Ví dụ: Phim Oppenheimer, Họp kỹ thuật AI, Video du lịch...")
        if default_name:
            self.input_field.setText(default_name)
            self.input_field.selectAll()
        layout.addWidget(self.input_field)

        # Quick preset chips
        chips_lbl = QLabel("Gợi ý chủ đề nhanh:")
        chips_lbl.setFont(font_ui(8.5, QFont.Weight.Medium))
        chips_lbl.setStyleSheet(f"color: {self.theme.dim};")
        layout.addWidget(chips_lbl)

        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(6)
        presets = [
            ("Phim ảnh", "Phim điện ảnh / Phim dài tập"),
            ("Cuộc họp", "Cuộc họp công việc / Thảo luận dự án"),
            ("Công nghệ", "Lập trình / Công nghệ phần mềm"),
            ("Học tập", "Bài giảng học thuật / Khóa học"),
            ("Phỏng vấn", "Talkshow / Phỏng vấn"),
        ]
        for label, full_text in presets:
            chip_btn = QPushButton(label)
            chip_btn.setCursor(Qt.PointingHandCursor)
            chip_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.theme.raised};
                    color: {self.theme.text};
                    border: 1px solid {self.theme.border};
                    border-radius: 6px;
                    padding: 5px 8px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background-color: {self.theme.surface};
                    border-color: {self.theme.teal};
                }}
            """)
            chip_btn.clicked.connect(lambda _, txt=full_text: self._apply_preset(txt))
            chips_layout.addWidget(chip_btn)

        layout.addLayout(chips_layout)
        layout.addSpacing(6)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.skip_btn = QPushButton("Bỏ qua")
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {self.theme.dim};
                border: 1px solid {self.theme.border};
            }}
            QPushButton:hover {{
                color: {self.theme.text};
                background-color: {self.theme.raised};
            }}
        """)
        self.skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.skip_btn)

        self.start_btn = QPushButton("Bắt đầu phiên")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.teal};
                color: #000000;
                border: none;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #38bdf8;
            }}
        """)
        self.start_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.start_btn)

        layout.addLayout(btn_layout)

    def _apply_preset(self, text: str) -> None:
        self.input_field.setText(text)
        self.input_field.setFocus()

    def get_session_name(self) -> str:
        return self.input_field.text().strip()


class SidebarResizeHandle(QWidget):
    """Draggable vertical bar for freely resizing the sidebar width."""

    def __init__(self, target_sidebar: QWidget, panel: 'TranscriptPanel', parent=None):
        super().__init__(parent)
        self.sidebar = target_sidebar
        self.panel = panel
        self.setFixedWidth(5)
        self.setCursor(Qt.SplitHCursor)
        self._dragging = False
        self._drag_start_x = 0
        self._start_width = 240
        self.setStyleSheet(f"""
            SidebarResizeHandle {{
                background-color: transparent;
            }}
            SidebarResizeHandle:hover {{
                background-color: {self.panel.theme.accent};
            }}
        """)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start_x = event.globalPosition().toPoint().x()
            self._start_width = self.sidebar.width()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            delta = event.globalPosition().toPoint().x() - self._drag_start_x
            new_w = max(180, min(520, self._start_width + delta))
            self.sidebar.setFixedWidth(new_w)
            self.panel._saved_sidebar_width = new_w
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()


# ───────────────────────────────────── Main Panel Widget ──────────────

class TranscriptPanel(QWidget):
    """Full-featured conversation history with Claude-styled left sidebar & AI summarizer."""

    open_settings_requested = Signal()

    def __init__(
        self,
        session_mgr_or_session=None,
        settings: Optional[AppSettings] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.theme = get_theme(settings.data.ui.theme if settings else "dark")
        self._saved_sidebar_width = 240

        # Support both SessionManager and TranscriptSession
        if isinstance(session_mgr_or_session, SessionManager):
            self.session_mgr = session_mgr_or_session
            self.session = self.session_mgr.active_session
        elif isinstance(session_mgr_or_session, TranscriptSession):
            self.session = session_mgr_or_session
            self.session_mgr = SessionManager(self.session.src_lang, self.session.tgt_lang)
            self.session_mgr.active_session = self.session
        else:
            self.session_mgr = SessionManager()
            self.session = self.session_mgr.active_session

        self.entry_widgets: List[TranscriptEntryWidget] = []
        self.selected_session_ids: Set[str] = set()
        self._user_scrolled_up = False
        self._unread_count = 0
        self._summarize_worker: Optional[SummarizeWorker] = None

        self.setup_ui()

        # Theme changes are handled by MainWindow rebuilding the page; a full
        # restyle on every settings change (slider ticks…) was wasted work.
        self.session_mgr.session_switched.connect(self.set_session)
        self.session_mgr.session_list_changed.connect(self.reload_sessions_list)
        self.session_mgr.paused_changed.connect(self._update_pause_ui)

        if self.session:
            self.set_session(self.session)

    def apply_theme_style(self) -> None:
        apply_theme(self, self.theme)

    def _build_empty_state(self) -> QWidget:
        t = self.theme
        box = QWidget()
        box.setObjectName("EmptyState")
        box.setStyleSheet(f"QWidget#EmptyState {{ background: {t.surface}; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(40, 40, 40, 60)
        lay.setSpacing(10)
        lay.addStretch(1)

        title = QLabel("Chưa có câu nào trong phiên này")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(font_ui(12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {t.text};")
        lay.addWidget(title)

        hint = QLabel(
            "Phát video, cuộc họp hoặc podcast trên máy tính — phụ đề dịch sẽ hiện "
            "trên màn hình và được lưu lại tại đây.\n"
            "Ctrl+Alt+P: tạm dừng / tiếp tục  ·  Ctrl+Alt+E: ẩn / hiện cửa sổ"
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setFont(font_ui(9.5))
        hint.setStyleSheet(f"color: {t.dim};")
        lay.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        open_settings = ElasticButton("Chọn ngôn ngữ và mô hình")
        open_settings.setFont(font_ui(9, QFont.Weight.DemiBold))
        open_settings.setFixedHeight(34)
        open_settings.setStyleSheet(f"""
            QPushButton {{
                background-color: {t.raised};
                color: {t.text};
                border: 1px solid {t.border};
                border-radius: 9px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ border-color: {t.accent}; color: {t.accent}; }}
        """)
        open_settings.clicked.connect(self.open_settings_requested.emit)
        btn_row.addWidget(open_settings)
        btn_row.addStretch(1)
        lay.addSpacing(6)
        lay.addLayout(btn_row)
        lay.addStretch(2)
        return box

    def _update_empty_state(self) -> None:
        empty = not (self.session and self.session.entries)
        self.empty_state.setVisible(empty)
        self.scroll_area.setVisible(not empty)

    def setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        # Embedded in MainWindow's card: no second border/radius inside it.
        self.container.setStyleSheet("QFrame#MainContainer { background: transparent; border: none; }")
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        main_layout.addWidget(self.container)

        # ── 1. Body Layout (Split View: LEFT Sidebar + CENTER Content + RIGHT Sidebar) ──
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # ── LEFT Sidebar (Collapsible, resizable width: default 240px) ─────
        self.sidebar = QFrame()
        self.sidebar.setObjectName("LeftSidebar")
        self.sidebar.setFixedWidth(self._saved_sidebar_width)
        self.sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        # Scoped by objectName: a bare "QFrame { … }" also matched every QLabel
        # (QLabel is a QFrame) and gave each one a border + background.
        self.sidebar.setStyleSheet(f"""
            QFrame#LeftSidebar {{
                border: none;
                border-right: 1px solid {self.theme.border};
                background-color: {self.theme.bg};
                border-bottom-left-radius: 16px;
            }}
            QFrame#LeftSidebar QLabel {{ background: transparent; }}
            QFrame#LeftSidebar QScrollArea, QFrame#LeftSidebar QScrollArea > QWidget > QWidget {{
                background: transparent;
            }}
        """)
        self._sidebar_expanded = True
        self._sidebar_anim = QPropertyAnimation(self, b"sidebarWidth", self)
        self._sidebar_anim.setDuration(220)
        self._sidebar_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._sidebar_anim.finished.connect(self._on_sidebar_anim_finished)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        # 1. Top Icon Action Bar (≡, ⌕)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(2, 0, 2, 4)
        top_bar.setSpacing(2)

        self.sidebar_toggle_btn = SidebarIconButton("\u2261", self.theme, "Thu gọn thanh bên")
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        top_bar.addWidget(self.sidebar_toggle_btn)

        self.search_toggle_btn = SidebarIconButton("⌕", self.theme, "Tìm kiếm phiên")
        self.search_toggle_btn.clicked.connect(self._toggle_search_box)
        top_bar.addWidget(self.search_toggle_btn)

        top_bar.addStretch()

        sidebar_layout.addLayout(top_bar)

        # 2. Action Items (+ New, Artifacts, Customize) - Pure Clean Typography, NO EMOJIS
        self.action_new_btn = SidebarActionItemWidget("+", "Tạo phiên mới", self.theme)
        self.action_new_btn.clicked.connect(self._create_new_session)
        sidebar_layout.addWidget(self.action_new_btn)

        self.action_artifacts_btn = SidebarActionItemWidget("", "Tóm tắt và xuất file", self.theme)
        self.action_artifacts_btn.setToolTip("Mở bảng Tóm tắt AI và Xuất transcript (.srt / .txt / .md)")
        self.action_artifacts_btn.clicked.connect(self._open_right_sidebar_and_export)
        sidebar_layout.addWidget(self.action_artifacts_btn)

        # Collapsible Cross-session search box
        self.cross_search_input = QLineEdit()
        self.cross_search_input.setPlaceholderText("Tìm kiếm phiên...")
        self.cross_search_input.setFont(font_ui(8.5))
        self.cross_search_input.setFixedHeight(28)
        self.cross_search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 6px;
                padding: 0 8px;
            }}
        """)
        self.cross_search_input.textChanged.connect(self._on_cross_search_changed)
        self.cross_search_input.hide()
        sidebar_layout.addWidget(self.cross_search_input)

        # 4. Scrollable Container for Projects, Pinned, Chats
        self.sessions_scroll = QScrollArea()
        self.sessions_scroll.setWidgetResizable(True)
        self.sessions_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sessions_scroll.setFrameShape(QFrame.NoFrame)
        self.sessions_scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 5px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {self.theme.border_strong};
                border-radius: 3px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)
        self.sessions_container = QWidget()
        self.sessions_container.setObjectName("SessionsContainer")
        self.sessions_container.setStyleSheet("QWidget#SessionsContainer { background: transparent; }")
        self.sessions_layout = QVBoxLayout(self.sessions_container)
        self.sessions_layout.setContentsMargins(0, 4, 0, 4)
        self.sessions_layout.setSpacing(2)
        self.sessions_scroll.setWidget(self.sessions_container)
        sidebar_layout.addWidget(self.sessions_scroll, 1)

        body_layout.addWidget(self.sidebar, 0)

        # Draggable Sidebar Resize Handle
        self.resize_handle = SidebarResizeHandle(self.sidebar, self)
        body_layout.addWidget(self.resize_handle, 0)

        # ── CENTER Content Area (Header + Scrollable Transcript) ─────
        self.right_wrapper = QWidget()
        self.right_wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(self.right_wrapper)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # ── Header Bar (Playful Clean) ──
        header = QFrame()
        header.setObjectName("TranscriptHeader")
        header.setFixedHeight(50)
        header.setStyleSheet(
            f"QFrame#TranscriptHeader {{ border: none; border-bottom: 1px solid {self.theme.border}; "
            f"background: transparent; }}"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 14, 0)
        header_layout.setSpacing(10)

        # Persistent Top-Left Toggle Button (Shown ONLY when sidebar is 100% closed)
        self.center_sidebar_toggle_btn = SidebarIconButton("\u2261", self.theme, "Mở thanh bên")
        self.center_sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        self.center_sidebar_toggle_btn.hide()
        header_layout.addWidget(self.center_sidebar_toggle_btn)

        # Active Session Title
        self.header_title_lbl = QLabel(self.session.display_title if self.session else "Phiên hiện tại")
        self.header_title_lbl.setFont(font_ui(10.5, QFont.Weight.Bold))
        self.header_title_lbl.setStyleSheet(f"color: {self.theme.text}; border: none;")
        header_layout.addWidget(self.header_title_lbl)

        header_layout.addStretch(1)

        # Pause / Resume Button (placed right next to search box)
        self.pause_btn = ElasticButton("Tạm dừng")
        self.pause_btn.setFont(font_ui(8.5, QFont.Weight.Bold))
        self.pause_btn.setFixedHeight(28)
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 8px;
                padding: 0 10px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                border-color: {self.theme.accent};
                color: {self.theme.accent};
            }}
        """)
        self.pause_btn.clicked.connect(self._toggle_pause)
        header_layout.addWidget(self.pause_btn)

        # In-Session Search
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm trong phiên...")
        self.search_input.setFont(font_ui(8.5))
        self.search_input.setFixedWidth(160)
        self.search_input.setFixedHeight(28)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {self.theme.surface};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 14px;
                padding: 0 12px;
            }}
            QLineEdit:focus {{
                border-color: {self.theme.accent};
            }}
        """)
        self.search_input.textChanged.connect(self.filter_entries)
        header_layout.addWidget(self.search_input)

        right_layout.addWidget(header)

        # ── Scrollable Transcript Entries List ──
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {self.theme.border_strong};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)
        self.entries_container = QWidget()
        self.entries_container.setObjectName("EntriesContainer")
        self.entries_container.setStyleSheet(
            f"QWidget#EntriesContainer {{ background: {self.theme.surface}; }}"
        )
        self.entries_layout = QVBoxLayout(self.entries_container)
        self.entries_layout.setContentsMargins(18, 16, 18, 16)
        self.entries_layout.setSpacing(8)
        # A trailing stretch (not setAlignment(AlignTop)) keeps cards top-aligned
        # *and* lets word-wrapped cards get their real height-for-width. With
        # AlignTop the layout under-sized them and the cards overlapped.
        self.entries_layout.addStretch(1)
        self.scroll_area.setWidget(self.entries_container)
        right_layout.addWidget(self.scroll_area, 1)

        # Empty state (shown when the session has no sentences yet)
        self.empty_state = self._build_empty_state()
        right_layout.addWidget(self.empty_state, 1)
        self.empty_state.hide()

        # Floating "↓ Câu mới" Pill
        self.new_items_btn = ElasticButton("↓ Câu mới", self.right_wrapper)
        self.new_items_btn.setCursor(Qt.PointingHandCursor)
        self.new_items_btn.setFont(font_ui(9, QFont.Weight.DemiBold))
        self.new_items_btn.setFixedSize(110, 30)
        self.new_items_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.accent};
                color: {self.theme.accent_text};
                border: 1px solid {self.theme.border_strong};
                border-radius: 15px;
            }}
        """)
        self.new_items_btn.hide()
        self.new_items_btn.clicked.connect(self._on_click_new_items)

        body_layout.addWidget(self.right_wrapper, 1)

        # ── RIGHT Sidebar (Tóm tắt AI & Xuất Transcript) ────────────
        self.right_sidebar = QFrame()
        self.right_sidebar.setObjectName("RightSidebar")
        self.right_sidebar.setMinimumWidth(0)
        self.right_sidebar.setMaximumWidth(0)  # Start collapsed
        self.right_sidebar.setStyleSheet(f"""
            QFrame#RightSidebar {{
                border: none;
                border-left: 1px solid {self.theme.border};
                background: {self.theme.bg};
                border-bottom-right-radius: 16px;
            }}
            QFrame#RightSidebar QLabel {{ background: transparent; }}
        """)
        self._right_sidebar_expanded = False  # Start collapsed
        self._right_sidebar_anim = QPropertyAnimation(self.right_sidebar, b"maximumWidth", self)
        self._right_sidebar_anim.setDuration(220)
        self._right_sidebar_anim.setEasingCurve(QEasingCurve.OutCubic)

        right_sidebar_layout = QVBoxLayout(self.right_sidebar)
        right_sidebar_layout.setContentsMargins(14, 14, 14, 14)
        right_sidebar_layout.setSpacing(10)

        # Right Sidebar Header
        rs_top = QHBoxLayout()
        rs_top.setContentsMargins(0, 0, 0, 0)
        rs_title = QLabel("Công cụ")
        rs_title.setFont(font_ui(10, QFont.Weight.Bold))
        rs_title.setStyleSheet(f"color: {self.theme.text}; border: none;")
        rs_top.addWidget(rs_title, 1)

        close_rs_btn = CloseIconButton(self.theme)
        close_rs_btn.setToolTip("Đóng thanh công cụ")
        close_rs_btn.clicked.connect(self._toggle_right_sidebar)
        rs_top.addWidget(close_rs_btn)
        right_sidebar_layout.addLayout(rs_top)

        # Thin separator
        div1 = QFrame()
        div1.setFixedHeight(1)
        div1.setStyleSheet(f"background: {self.theme.border};")
        right_sidebar_layout.addWidget(div1)

        # ── Section 1: Tóm tắt AI ──
        sum_lbl = QLabel("TÓM TẮT AI")
        sum_lbl.setFont(font_ui(7.5, QFont.Weight.Bold))
        sum_lbl.setStyleSheet(f"color: {self.theme.dim}; border: none; letter-spacing: 1px;")
        right_sidebar_layout.addWidget(sum_lbl)

        sum_desc = QLabel("Dùng Gemini AI tóm tắt phiên dịch.")
        sum_desc.setFont(font_ui(8))
        sum_desc.setStyleSheet(f"color: {self.theme.dim}; border: none;")
        sum_desc.setWordWrap(True)
        right_sidebar_layout.addWidget(sum_desc)

        self.summarize_btn = ElasticButton("Tóm tắt AI")
        self.summarize_btn.setFont(font_ui(8.5, QFont.Weight.DemiBold))
        self.summarize_btn.setFixedHeight(32)
        self.summarize_btn.setCursor(Qt.PointingHandCursor)
        self.summarize_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.cta_bg};
                color: {self.theme.cta_text};
                border: none;
                border-radius: 8px;
                padding: 0 10px;
            }}
            QPushButton:hover {{ background-color: {self.theme.cta_hover}; }}
            QPushButton:disabled {{ background-color: {self.theme.raised}; color: {self.theme.dim}; }}
        """)
        self.summarize_btn.clicked.connect(self._summarize_selected_sessions)
        right_sidebar_layout.addWidget(self.summarize_btn)

        # Inline Summary Result Container
        self.summary_container = QWidget()
        sum_container_layout = QVBoxLayout(self.summary_container)
        sum_container_layout.setContentsMargins(0, 0, 0, 0)
        sum_container_layout.setSpacing(6)
        self.summary_text_area = QTextEdit()
        self.summary_text_area.setReadOnly(True)
        self.summary_text_area.setFont(font_ui(8.5))
        self.summary_text_area.setMaximumHeight(140)
        self.summary_text_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        sum_container_layout.addWidget(self.summary_text_area)
        sum_action_btns = QHBoxLayout()
        sum_action_btns.setSpacing(4)
        self.copy_summary_btn = ElasticButton("Sao chép")
        self.copy_summary_btn.setFont(font_ui(8, QFont.Weight.DemiBold))
        self.copy_summary_btn.setFixedHeight(24)
        self.copy_summary_btn.setCursor(Qt.PointingHandCursor)
        self.copy_summary_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 4px;
                padding: 0 6px;
            }}
            QPushButton:hover {{
                color: {self.theme.accent};
                border-color: {self.theme.accent};
            }}
        """)
        self.copy_summary_btn.clicked.connect(self._copy_right_summary)
        sum_action_btns.addWidget(self.copy_summary_btn)
        self.save_summary_btn = ElasticButton("Lưu file")
        self.save_summary_btn.setFont(font_ui(8, QFont.Weight.DemiBold))
        self.save_summary_btn.setFixedHeight(24)
        self.save_summary_btn.setCursor(Qt.PointingHandCursor)
        self.save_summary_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 4px;
                padding: 0 6px;
            }}
            QPushButton:hover {{
                color: {self.theme.accent};
                border-color: {self.theme.accent};
            }}
        """)
        self.save_summary_btn.clicked.connect(self._save_right_summary)
        sum_action_btns.addWidget(self.save_summary_btn)
        sum_container_layout.addLayout(sum_action_btns)
        self.summary_container.hide()
        right_sidebar_layout.addWidget(self.summary_container)

        # Separator
        div2 = QFrame()
        div2.setFixedHeight(1)
        div2.setStyleSheet(f"background: {self.theme.border};")
        right_sidebar_layout.addWidget(div2)

        # ── Section 2: Xuất Transcript ──
        exp_lbl = QLabel("XUẤT TRANSCRIPT")
        exp_lbl.setFont(font_ui(7.5, QFont.Weight.Bold))
        exp_lbl.setStyleSheet(f"color: {self.theme.dim}; border: none; letter-spacing: 1px;")
        right_sidebar_layout.addWidget(exp_lbl)

        tags_layout = QHBoxLayout()
        tags_layout.setSpacing(4)
        self.format_group = QButtonGroup(self)
        self.format_group.setExclusive(True)
        for fmt in [".srt", ".txt", ".md"]:
            btn = FormatButton(fmt, self.theme)
            self.format_group.addButton(btn)
            tags_layout.addWidget(btn)
        self.format_group.buttons()[0].setChecked(True)
        right_sidebar_layout.addLayout(tags_layout)

        opts_layout = QHBoxLayout()
        self.toggle_src = ToggleCheckBox("Bản gốc", self.theme)
        self.toggle_src.setChecked(True)
        opts_layout.addWidget(self.toggle_src)
        self.toggle_ts = ToggleCheckBox("Thời gian", self.theme)
        self.toggle_ts.setChecked(True)
        opts_layout.addWidget(self.toggle_ts)
        right_sidebar_layout.addLayout(opts_layout)

        self.rs_export_btn = ElasticButton("Xuất file...")
        self.rs_export_btn.setFont(font_ui(8.5, QFont.Weight.DemiBold))
        self.rs_export_btn.setFixedHeight(32)
        self.rs_export_btn.setCursor(Qt.PointingHandCursor)
        self.rs_export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 7px;
                padding: 0 12px;
            }}
            QPushButton:hover {{
                border-color: {self.theme.accent};
                color: {self.theme.accent};
            }}
        """)
        self.rs_export_btn.clicked.connect(self.export_transcript)
        right_sidebar_layout.addWidget(self.rs_export_btn)
        # Pack sections at the top (they were spread over the full height).
        right_sidebar_layout.addStretch(1)

        self.right_sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        body_layout.addWidget(self.right_sidebar, 0)

        # Smooth scrollbar animation
        vbar = self.scroll_area.verticalScrollBar()
        self._scroll_anim = QPropertyAnimation(vbar, b"value", vbar)
        self._scroll_anim.setDuration(220)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
        vbar.valueChanged.connect(self._on_scroll_changed)

        container_layout.addWidget(body)
        self.reload_sessions_list()

    # ────────────────────────────── Session Management ────────────────

    def set_session(self, session: TranscriptSession) -> None:
        # Track what we are actually connected to. The old logic compared
        # against self.session, which __init__ had already set — so the
        # session active at startup was never connected and live sentences
        # did not appear in this panel until the user switched sessions.
        connected = getattr(self, "_connected_session", None)
        if connected is not None and connected is not session:
            try:
                connected.entry_added.disconnect(self.on_entry_added)
                connected.session_updated.disconnect(self.update_meta)
            except (RuntimeError, TypeError):
                pass
            self._connected_session = None

        self.session = session
        if self.session:
            if getattr(self, "_connected_session", None) is not session:
                self.session.entry_added.connect(self.on_entry_added)
                self.session.session_updated.connect(self.update_meta)
                self._connected_session = session
            self.header_title_lbl.setText(self.session.display_title)
            self.reload_entries()
            self.update_meta()
            self._update_pause_ui(self.session.is_paused)

        self.reload_sessions_list()

    def reload_entries(self) -> None:
        for w in getattr(self, "entry_widgets", []):
            try:
                self.entries_layout.removeWidget(w)
                w.deleteLater()
            except Exception:
                pass

        self.entry_widgets = []
        self._unread_count = 0
        self.new_items_btn.hide()
        self.entries_container.setUpdatesEnabled(False)
        if self.session:
            last = len(self.session.entries) - 1
            for i, entry in enumerate(self.session.entries):
                self.add_entry_widget(entry, i == last)
        self.entries_container.setUpdatesEnabled(True)
        self._update_empty_state()
        if self.entry_widgets:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._jump_to_bottom)

    def reload_sessions_list(self) -> None:
        while self.sessions_layout.count():
            item = self.sessions_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        query = self.cross_search_input.text().strip() if hasattr(self, "cross_search_input") else ""
        sessions = self.session_mgr.list_sessions(query)

        active_sid = self.session.session_id if self.session else ""

        if not sessions:
            msg = f"Không có phiên nào khớp “{query}”" if query else "Chưa có phiên nào"
            lbl = QLabel(msg)
            lbl.setWordWrap(True)
            lbl.setFont(font_ui(8.5))
            lbl.setStyleSheet(f"color: {self.theme.dim}; padding: 12px; border: none;")
            self.sessions_layout.addWidget(lbl)
            self.sessions_layout.addStretch(1)
            return

        pinned_sessions = [s for s in sessions if s.get("is_pinned")]
        chats_sessions = [s for s in sessions if not s.get("is_pinned")]

        # Pinned section (only when something is pinned — no empty headers)
        if pinned_sessions:
            self.sessions_layout.addWidget(
                SidebarSectionHeaderWidget("Đã ghim", action_icon="", theme=self.theme)
            )
            for s in pinned_sessions:
                self._add_claude_session_item(s, active_sid)

        # Recent sessions grouped by day ("Hôm nay", "Hôm qua", "7 ngày qua", MM/YYYY)
        current_group = None
        for s in chats_sessions:
            group = s.get("day_group") or "Khác"
            if group != current_group:
                current_group = group
                self.sessions_layout.addWidget(
                    SidebarSectionHeaderWidget(group, action_icon="", theme=self.theme)
                )
            self._add_claude_session_item(s, active_sid)

        self.sessions_layout.addStretch(1)

    def _add_claude_session_item(self, session_info: dict, active_sid: str) -> None:
        is_active = (session_info["session_id"] == active_sid)
        w = ClaudeSessionItemWidget(session_info, is_active=is_active, theme=self.theme)
        w.set_checked(session_info["session_id"] in self.selected_session_ids)

        w.clicked.connect(self._on_session_clicked)
        w.checked_toggled.connect(self._on_session_checked)
        w.renamed.connect(self._on_session_renamed)
        w.pin_toggled.connect(self._on_session_pin_toggled)
        w.deleted.connect(self._on_session_deleted)

        self.sessions_layout.addWidget(w)

    def _create_new_session(self) -> None:
        default_name = f"Phiên {datetime.now().strftime('%d/%m %H:%M')}"
        dlg = NewSessionDialog(self, theme=self.theme, default_name="")
        if dlg.exec() == QDialog.Accepted:
            raw_name = dlg.get_session_name()
            session_name = raw_name if raw_name else default_name
            self.session_mgr.create_session(session_name)

    def _on_session_clicked(self, session_id: str) -> None:
        self.session_mgr.switch_to(session_id)

    def _on_session_checked(self, session_id: str, checked: bool) -> None:
        if checked:
            self.selected_session_ids.add(session_id)
        else:
            self.selected_session_ids.discard(session_id)

    def _on_session_renamed(self, session_id: str, new_name: str) -> None:
        self.session_mgr.rename_session(session_id, new_name)
        if self.session and self.session.session_id == session_id:
            self.header_title_lbl.setText(new_name)

    def _on_session_pin_toggled(self, session_id: str, is_pinned: bool) -> None:
        self.session_mgr.pin_session(session_id, is_pinned)

    def _on_session_deleted(self, session_id: str) -> None:
        if self.selected_session_ids and (session_id in self.selected_session_ids or len(self.selected_session_ids) > 1):
            self._delete_selected_sessions()
            return

        reply = QMessageBox.question(
            self,
            "Xác nhận xoá",
            "Bạn có chắc muốn xoá phiên này không? Dữ liệu đã xoá sẽ không thể khôi phục.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.selected_session_ids.discard(session_id)
            self.session_mgr.delete_session(session_id)

    def _delete_selected_sessions(self) -> None:
        target_ids = list(self.selected_session_ids) if self.selected_session_ids else ([self.session.session_id] if self.session else [])
        if not target_ids:
            return

        count = len(target_ids)
        msg = f"Bạn có chắc muốn xoá {count} phiên đã chọn không?" if count > 1 else "Bạn có chắc muốn xoá phiên này không?"
        reply = QMessageBox.question(
            self,
            "Xác nhận xoá phiên",
            f"{msg}\nDữ liệu đã xoá sẽ không thể khôi phục.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.selected_session_ids.clear()
            self.session_mgr.delete_sessions(target_ids)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete or (event.key() == Qt.Key_Backspace and event.modifiers() & Qt.ControlModifier):
            self._delete_selected_sessions()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_cross_search_changed(self, _text: str) -> None:
        self.reload_sessions_list()

    def _toggle_pause(self) -> None:
        if self.session:
            self.session.toggle_pause()

    def _update_pause_ui(self, is_paused: bool) -> None:
        if is_paused:
            self.pause_btn.setText("Tiếp tục")
            self.pause_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.theme.accent};
                    color: {self.theme.accent_text};
                    border: none;
                    border-radius: 6px;
                    padding: 0 4px;
                    text-align: center;
                }}
            """)
        else:
            self.pause_btn.setText("Tạm dừng")
            self.pause_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.theme.raised};
                    color: {self.theme.text};
                    border: 1px solid {self.theme.border};
                    border-radius: 6px;
                    padding: 0 4px;
                    text-align: center;
                }}
                QPushButton:hover {{
                    border-color: {self.theme.accent};
                    color: {self.theme.accent};
                }}
            """)

    # ────────────────────────────── AI Summarization ──────────────────

    def _summarize_selected_sessions(self) -> None:
        target_ids = list(self.selected_session_ids)
        if not target_ids:
            if self.session and self.session.entries:
                target_ids = [self.session.session_id]
            else:
                QMessageBox.information(
                    self,
                    "Chọn phiên",
                    "Vui lòng nhấn vào vòng tròn ○ trước các phiên để chọn trước khi tóm tắt!",
                )
                return

        content = self.session_mgr.get_sessions_content(target_ids)
        if not content.strip():
            QMessageBox.information(
                self,
                "Phiên trống",
                "Các phiên đã chọn không có câu dịch nào để tóm tắt.",
            )
            return

        api_key = self.settings.data.summary.api_key if self.settings else ""
        if not api_key:
            key, ok = QInputDialog.getText(
                self,
                "Nhập Gemini API Key",
                "Để sử dụng tính năng tóm tắt AI, vui lòng nhập Google Gemini API Key:\n"
                "(Bạn có thể lấy miễn phí tại https://aistudio.google.com/apikey)",
                QLineEdit.Password,
            )
            if ok and key.strip():
                api_key = key.strip()
                if self.settings:
                    self.settings.update(summary={"api_key": api_key})
            else:
                return

        dialog = SummaryDialog("Đang kết nối Gemini AI và phân tích nội dung phiên...\nVui lòng đợi trong giây lát.", self.theme, self)
        dialog.show()

        style = self.settings.data.summary.style if self.settings else "bullet"
        tgt_lang = self.settings.data.ui.tgt_lang if self.settings else "vi"

        self._summarize_worker = SummarizeWorker(
            api_key=api_key,
            content=content,
            model=self.settings.data.summary.model if self.settings else "gemini-2.0-flash",
            style=style,
            target_lang=tgt_lang,
            parent=self,
        )
        # Prevent double submissions while the request is running.
        self.summarize_btn.setEnabled(False)
        self.summarize_btn.setText("Đang tóm tắt…")

        def _done():
            self.summarize_btn.setEnabled(True)
            self.summarize_btn.setText("Tóm tắt AI")

        def on_finished(summary_text: str):
            _done()
            dialog.set_content(summary_text)
            if hasattr(self, "summary_text_area") and self.summary_text_area:
                self.summary_text_area.setPlainText(summary_text)
            if hasattr(self, "summary_container") and self.summary_container:
                self.summary_container.show()

        def on_error(err_msg: str):
            _done()
            dialog.set_content(f"Không thể tạo tóm tắt:\n\n{err_msg}")

        self._summarize_worker.finished.connect(on_finished)
        self._summarize_worker.error.connect(on_error)
        self._summarize_worker.start()

    # ────────────────────────────── Entries & UI Events ───────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_new_items_btn()

    def _position_new_items_btn(self) -> None:
        if not hasattr(self, "new_items_btn") or not self.new_items_btn:
            return
        # The pill lives in right_wrapper; the scroll area sits below the
        # header there, so use its geometry (the old math ignored the header).
        geo = self.scroll_area.geometry()
        btn = self.new_items_btn
        x = geo.x() + (geo.width() - btn.width()) // 2
        y = geo.y() + geo.height() - btn.height() - 16
        btn.move(max(10, x), max(10, y))
        btn.raise_()

    def _on_scroll_changed(self, value: int) -> None:
        vbar = self.scroll_area.verticalScrollBar()
        at_bottom = (vbar.maximum() - value) <= 45
        if at_bottom:
            self._user_scrolled_up = False
            self._unread_count = 0
            self.new_items_btn.hide()
        elif not self._scroll_anim.state() == QPropertyAnimation.Running:
            self._user_scrolled_up = True

    def _get_sidebar_width(self) -> int:
        return self.sidebar.width()

    def _set_sidebar_width(self, w: int) -> None:
        self.sidebar.setFixedWidth(w)

    sidebarWidth = Property(int, _get_sidebar_width, _set_sidebar_width)

    def _toggle_sidebar(self) -> None:
        self._sidebar_anim.stop()
        curr_width = self.sidebar.width()
        if self._sidebar_expanded:
            if curr_width >= 180:
                self._saved_sidebar_width = curr_width
            self._sidebar_expanded = False
            if hasattr(self, "resize_handle"):
                self.resize_handle.hide()
            self.sessions_scroll.hide()
            self.action_new_btn.hide()
            self.action_artifacts_btn.hide()
            self.search_toggle_btn.hide()
            self.sidebar_toggle_btn.hide()
            if self.cross_search_input.isVisible():
                self.cross_search_input.hide()
            self.center_sidebar_toggle_btn.show()
            self._sidebar_anim.setStartValue(curr_width)
            self._sidebar_anim.setEndValue(0)
        else:
            self._sidebar_expanded = True
            self.center_sidebar_toggle_btn.hide()
            self.sidebar.show()
            if hasattr(self, "resize_handle"):
                self.resize_handle.show()
            self.sidebar_toggle_btn.show()
            self.sessions_scroll.show()
            self.action_new_btn.show()
            self.action_artifacts_btn.show()
            self.search_toggle_btn.show()
            target_w = getattr(self, "_saved_sidebar_width", 240)
            self._sidebar_anim.setStartValue(curr_width)
            self._sidebar_anim.setEndValue(target_w)
        self._sidebar_anim.start()

    def _on_sidebar_anim_finished(self) -> None:
        if not self._sidebar_expanded:
            self.sidebar.hide()
            if hasattr(self, "resize_handle"):
                self.resize_handle.hide()
            self.sidebar.setFixedWidth(0)
        else:
            self.sidebar.show()
            if hasattr(self, "resize_handle"):
                self.resize_handle.show()
            target_w = getattr(self, "_saved_sidebar_width", 240)
            self.sidebar.setFixedWidth(target_w)

    def _toggle_search_box(self) -> None:
        if self.cross_search_input.isVisible():
            self.cross_search_input.hide()
        else:
            self.cross_search_input.show()
            self.cross_search_input.setFocus()

    def _toggle_right_sidebar(self) -> None:
        self._right_sidebar_anim.stop()
        if self._right_sidebar_expanded:
            self._right_sidebar_anim.setStartValue(self.right_sidebar.maximumWidth())
            self._right_sidebar_anim.setEndValue(0)
            self._right_sidebar_expanded = False
        else:
            self.right_sidebar.show()
            self._right_sidebar_anim.setStartValue(self.right_sidebar.maximumWidth())
            self._right_sidebar_anim.setEndValue(250)
            self._right_sidebar_expanded = True
        self._right_sidebar_anim.start()

    def _open_right_sidebar_and_export(self) -> None:
        """Toggles the right sidebar (Công cụ / Xuất) open and closed."""
        self._toggle_right_sidebar()

    def _copy_right_summary(self) -> None:
        text = self.summary_text_area.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Đã sao chép", "Đã sao chép nội dung tóm tắt vào bộ nhớ tạm!")

    def _save_right_summary(self) -> None:
        text = self.summary_text_area.toPlainText().strip()
        if text:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Lưu tóm tắt",
                "summary.txt",
                "Text Files (*.txt);;Markdown Files (*.md)",
            )
            if file_path:
                try:
                    Path(file_path).write_text(text, encoding="utf-8")
                    QMessageBox.information(self, "Đã lưu", f"Đã lưu bản tóm tắt tại:\n{file_path}")
                except Exception as e:
                    QMessageBox.warning(self, "Lỗi lưu file", f"Không thể lưu file: {e}")

    def _on_click_new_items(self) -> None:
        self._user_scrolled_up = False
        self._unread_count = 0
        self.new_items_btn.hide()
        self._smooth_scroll_to_bottom()

    def _smooth_scroll_to_bottom(self) -> None:
        # (no processEvents(): re-entering the event loop from a slot could
        # run other slots mid-update)
        vbar = self.scroll_area.verticalScrollBar()
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(vbar.value())
        self._scroll_anim.setEndValue(vbar.maximum())
        self._scroll_anim.start()

    def _jump_to_bottom(self) -> None:
        vbar = self.scroll_area.verticalScrollBar()
        self._scroll_anim.stop()
        vbar.setValue(vbar.maximum())

    def on_entry_added(self, entry: TranscriptEntry) -> None:
        if self.entry_widgets:
            self.entry_widgets[-1].set_latest(False)

        self.add_entry_widget(entry, True)
        self.update_meta()
        self._update_empty_state()

        from PySide6.QtCore import QTimer

        if self._user_scrolled_up:
            # Reading older lines: don't yank the view — count and offer a jump.
            self._unread_count += 1
            self.new_items_btn.setText(f"↓ {self._unread_count} câu mới")
            self._position_new_items_btn()
            self.new_items_btn.show()
        else:
            # Wait for the new card to be laid out before scrolling.
            QTimer.singleShot(0, self._smooth_scroll_to_bottom)

    def add_entry_widget(self, entry: TranscriptEntry, is_latest: bool) -> None:
        w = TranscriptEntryWidget(entry, self.theme, is_latest)
        # Insert above the trailing stretch.
        self.entries_layout.insertWidget(self.entries_layout.count() - 1, w)
        self.entry_widgets.append(w)

        text = self.search_input.text().lower()
        if text:
            visible = text in (entry.source_text or "").lower() or text in (entry.target_text or "").lower()
            w.setVisible(visible)

    def update_meta(self) -> None:
        if not self.session:
            return
        self.header_title_lbl.setText(self.session.display_title)

    def filter_entries(self, text: str) -> None:
        text = text.lower()
        for w in self.entry_widgets:
            if not text:
                w.setVisible(True)
            else:
                entry = w.entry
                visible = text in (entry.source_text or "").lower() or text in (entry.target_text or "").lower()
                w.setVisible(visible)

    def export_transcript(self) -> None:
        checked_btn = self.format_group.checkedButton()
        ext = checked_btn.text() if checked_btn else ".srt"

        sid = self.session.session_id if self.session else "export"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Xuất Transcript",
            f"transcript_{sid}{ext}",
            f"File {ext.upper()} (*{ext})",
        )
        if not file_path:
            return

        inc_src = self.toggle_src.isChecked()
        inc_ts = self.toggle_ts.isChecked()

        if self.session:
            if ext == ".srt":
                content = self.session.export_srt(include_source=inc_src, include_timestamp=inc_ts)
            elif ext == ".txt":
                content = self.session.export_txt(include_source=inc_src, include_timestamp=inc_ts)
            else:
                content = self.session.export_md(include_source=inc_src, include_timestamp=inc_ts)

            try:
                # utf-8-sig: Windows players / Notepad detect Vietnamese correctly.
                encoding = "utf-8-sig" if ext in (".srt", ".txt") else "utf-8"
                Path(file_path).write_text(content, encoding=encoding)
            except Exception as e:
                QMessageBox.warning(self, "Không thể lưu file", f"Lỗi khi lưu transcript:\n{e}")
                return
            QMessageBox.information(
                self,
                "Đã xuất transcript",
                f"Đã lưu {len(self.session.entries)} câu vào:\n{file_path}",
            )


# ───────────────────────────────────── Standalone Window ─────────────

class TranscriptWindow(QWidget):
    def __init__(self, session_mgr_or_session=None, settings: Optional[AppSettings] = None, parent=None):
        super().__init__()
        from pathlib import Path
        icon_path = Path(__file__).parent.parent / "rtt_icon.ico"
        if icon_path.exists():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(600, 420)
        self.resize(760, 540)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.panel = TranscriptPanel(session_mgr_or_session, settings, self)
        main_layout.addWidget(self.panel)

        self.drag_pos = None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and event.pos().y() < 50:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton and self.drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, _event: QMouseEvent):
        self.drag_pos = None


def main():
    app = QApplication(sys.argv)
    settings = AppSettings()
    mgr = SessionManager("en", "vi")
    session = mgr.active_session
    session.add_entry("We call that gap the ear-voice span.", "Khoảng cách đó gọi là ear-voice span.")
    session.add_entry("It is usually two to four seconds.", "Nó thường kéo dài hai đến bốn giây.")

    win = TranscriptWindow(mgr, settings)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
