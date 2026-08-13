"""Transcript Panel & Window UI — 720px real-time conversation history logger & exporter.

Matches design spec sections 5a and 6c:
  - Header: title, live metadata (time · count · EN→VI), search box, export button.
  - Left panel: scrolling list of committed sentences (time, source in teal, translation in text color).
    Latest committed sentence highlighted with left accent border and subtle background tint.
  - Right sidebar (200px):
    - Export format tags (.srt, .txt, .md)
    - Export options (Bản gốc, Timestamp)
    - Past sessions list ("Hôm nay · 14:02 · 18′", "Hôm qua · 21:40 · 96′")
    - Footer note ("Chỉ lưu trên máy. Tự xoá sau 7 ngày.")
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QRectF, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rtt.history import TranscriptEntry, TranscriptManager, TranscriptSession
from rtt.settings import AppSettings
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

class TranscriptEntryWidget(QFrame):
    """Single row in the transcript list."""

    def __init__(self, entry: TranscriptEntry, theme: ThemeColors = DARK, is_latest: bool = False, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.theme = theme
        self.is_latest = is_latest
        self.setup_ui()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(14)

        # Time column
        st = getattr(self.entry, 'start_time_s', getattr(self.entry, 'start_time', 0.0))
        time_str = getattr(self.entry, 'time_str', '') or f"{(int(st)//60):02d}:{(int(st)%60):02d}"
        time_lbl = QLabel(time_str)
        time_lbl.setFont(font_mono(9))
        time_lbl.setFixedWidth(52)
        time_lbl.setAlignment(Qt.AlignTop | Qt.AlignRight)
        time_color = self.theme.accent if self.is_latest else self.theme.dim
        time_lbl.setStyleSheet(f"color: {time_color}; background: transparent; border: none;")
        layout.addWidget(time_lbl)

        # Content column (Source text + Target text)
        content_box = QWidget()
        content_box.setStyleSheet("background: transparent; border: none;")
        content_layout = QVBoxLayout(content_box)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(3)

        if self.entry.source_text:
            src_lbl = QLabel(self.entry.source_text)
            src_lbl.setFont(font_ui(9))
            src_lbl.setStyleSheet(f"color: {self.theme.teal}; opacity: 0.85; background: transparent; border: none;")
            src_lbl.setWordWrap(True)
            content_layout.addWidget(src_lbl)

        if self.entry.target_text:
            tgt_lbl = QLabel(self.entry.target_text)
            tgt_weight = QFont.Weight.DemiBold if self.is_latest else QFont.Weight.Normal
            tgt_lbl.setFont(font_ui(11, tgt_weight))
            tgt_lbl.setStyleSheet(f"color: {self.theme.text}; background: transparent; border: none;")
            tgt_lbl.setWordWrap(True)
            content_layout.addWidget(tgt_lbl)

        layout.addWidget(content_box, 1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        if self.is_latest:
            # background tint rgba(255,255,255,0.03)
            painter.fillRect(self.rect(), QColor(255, 255, 255, 8))
            # left accent border 2px
            painter.setPen(QPen(QColor(self.theme.accent), 2))
            painter.drawLine(1, 0, 1, self.height())


class FormatButton(QPushButton):
    def __init__(self, text, theme):
        super().__init__(text)
        self.theme = theme
        self.setFont(font_ui(9, QFont.Weight.Medium))
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setFixedHeight(28)
        self.setStyleSheet(self._get_style(False))
        self.toggled.connect(lambda c: self.setStyleSheet(self._get_style(c)))

    def _get_style(self, checked):
        if checked:
            return f"""
                QPushButton {{
                    background-color: {self.theme.accent};
                    color: {self.theme.accent_text};
                    border: none;
                    border-radius: 6px;
                    padding: 0 12px;
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background-color: {self.theme.raised};
                    color: {self.theme.dim};
                    border: 1px solid {self.theme.border};
                    border-radius: 6px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    color: {self.theme.text};
                }}
            """


class ToggleCheckBox(QCheckBox):
    def __init__(self, text, theme):
        super().__init__(text)
        self.theme = theme
        self.setFont(font_ui(9))
        self.setStyleSheet(f"""
            QCheckBox {{
                color: {self.theme.text};
                font-size: 12px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 32px;
                height: 18px;
                border-radius: 9px;
            }}
            QCheckBox::indicator:unchecked {{
                background-color: {self.theme.border_strong};
            }}
            QCheckBox::indicator:checked {{
                background-color: {self.theme.accent};
            }}
        """)


# ───────────────────────────────────── Panel Widget ───────────────────

class TranscriptPanel(QWidget):
    """Pure widget panel for live transcript logger & export."""

    def __init__(self, session: Optional[TranscriptSession] = None, settings: Optional[AppSettings] = None, parent=None):
        super().__init__(parent)
        self.session = session
        self.settings = settings
        self.theme = get_theme(settings.data.ui.theme if settings else "dark")
        self.entry_widgets: List[TranscriptEntryWidget] = []
        self._user_scrolled_up = False
        self._unread_count = 0

        self.setup_ui()
        if session:
            self.set_session(session)

        if self.settings:
            self.settings.changed.connect(self._on_settings_changed)

    def _on_settings_changed(self):
        if self.settings:
            self.theme = get_theme(self.settings.data.ui.theme)
            self.apply_theme_style()

    def apply_theme_style(self):
        apply_theme(self, self.theme)

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.container = QFrame(self)
        self.container.setObjectName("MainContainer")
        self.container.setStyleSheet(f"""
            QFrame#MainContainer {{
                background-color: {self.theme.surface};
                border-radius: 14px;
                border: 1px solid {self.theme.border};
            }}
        """)
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        main_layout.addWidget(self.container)

        # ── 1. Header Bar ──────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet(f"border-bottom: 1px solid {self.theme.border}; background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(12)

        title_lbl = QLabel("Phiên hiện tại")
        title_lbl.setFont(font_ui(11, QFont.Weight.DemiBold))
        title_lbl.setStyleSheet(f"color: {self.theme.text}; border: none;")
        header_layout.addWidget(title_lbl)

        self.meta_lbl = QLabel("00:00 · 0 câu · EN → VI")
        self.meta_lbl.setFont(font_mono(9))
        self.meta_lbl.setStyleSheet(f"color: {self.theme.dim}; border: none;")
        header_layout.addWidget(self.meta_lbl)

        header_layout.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm trong transcript")
        self.search_input.setFont(font_ui(9))
        self.search_input.setFixedWidth(190)
        self.search_input.setFixedHeight(30)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 15px;
                padding: 0 12px;
            }}
        """)
        self.search_input.textChanged.connect(self.filter_entries)
        header_layout.addWidget(self.search_input)

        export_btn = QPushButton("Xuất .srt")
        export_btn.setFont(font_ui(9, QFont.Weight.DemiBold))
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.setFixedHeight(30)
        export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.accent};
                color: {self.theme.accent_text};
                border: none;
                border-radius: 15px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)
        export_btn.clicked.connect(self.export_transcript)
        header_layout.addWidget(export_btn)

        container_layout.addWidget(header)

        # ── 2. Body Layout (Left Panel + Right Sidebar) ──────────
        body = QWidget(self.container)
        body.setStyleSheet("border: none; background: transparent;")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Left Panel (Transcript list)
        self.left_wrapper = QWidget(body)
        self.left_wrapper.setStyleSheet("border: none; background: transparent;")
        left_layout = QVBoxLayout(self.left_wrapper)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self.left_wrapper)
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
        self.entries_layout = QVBoxLayout(self.entries_container)
        self.entries_layout.setContentsMargins(16, 16, 16, 16)
        self.entries_layout.setSpacing(4)
        self.entries_layout.setAlignment(Qt.AlignTop)

        self.scroll_area.setWidget(self.entries_container)
        left_layout.addWidget(self.scroll_area, 1)

        # Floating "↓ Câu mới" Pill Button
        self.new_items_btn = QPushButton("↓ Câu mới", self.left_wrapper)
        self.new_items_btn.setFont(font_ui(9, QFont.Weight.DemiBold))
        self.new_items_btn.setCursor(Qt.PointingHandCursor)
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

        body_layout.addWidget(self.left_wrapper, 1)

        # Smooth scrollbar animation
        vbar = self.scroll_area.verticalScrollBar()
        self._scroll_anim = QPropertyAnimation(vbar, b"value", vbar)
        self._scroll_anim.setDuration(220)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Detect user scroll position
        vbar.valueChanged.connect(self._on_scroll_changed)

        # ── Right Sidebar (200px) ──────────────────────────────────
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(f"border-left: 1px solid {self.theme.border}; background: transparent;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(16)

        # Section 1: XUẤT
        sec1 = QVBoxLayout()
        sec1.setSpacing(8)
        lbl1 = QLabel("XUẤT")
        lbl1.setFont(font_mono(8, QFont.Weight.Bold))
        lbl1.setStyleSheet(f"color: {self.theme.dim}; border: none; letter-spacing: 0.1em;")
        sec1.addWidget(lbl1)

        tags_layout = QHBoxLayout()
        tags_layout.setSpacing(6)
        self.format_group = QButtonGroup(self)
        self.format_group.setExclusive(True)
        for fmt in [".srt", ".txt", ".md"]:
            btn = FormatButton(fmt, self.theme)
            self.format_group.addButton(btn)
            tags_layout.addWidget(btn)
        self.format_group.buttons()[0].setChecked(True)

        sec1.addLayout(tags_layout)
        sidebar_layout.addLayout(sec1)

        # Section 2: NỘI DUNG XUẤT
        sec2 = QVBoxLayout()
        sec2.setSpacing(8)
        lbl2 = QLabel("NỘI DUNG XUẤT")
        lbl2.setFont(font_mono(8, QFont.Weight.Bold))
        lbl2.setStyleSheet(f"color: {self.theme.dim}; border: none; letter-spacing: 0.1em;")
        sec2.addWidget(lbl2)

        self.toggle_src = ToggleCheckBox("Bản gốc", self.theme)
        self.toggle_src.setChecked(True)
        sec2.addWidget(self.toggle_src)

        self.toggle_ts = ToggleCheckBox("Timestamp", self.theme)
        self.toggle_ts.setChecked(True)
        sec2.addWidget(self.toggle_ts)

        sidebar_layout.addLayout(sec2)

        # Section 3: PHIÊN TRƯỚC
        sec3 = QVBoxLayout()
        sec3.setSpacing(8)
        lbl3 = QLabel("PHIÊN TRƯỚC")
        lbl3.setFont(font_mono(8, QFont.Weight.Bold))
        lbl3.setStyleSheet(f"color: {self.theme.dim}; border: none; letter-spacing: 0.1em;")
        sec3.addWidget(lbl3)

        self.past_sessions_layout = QVBoxLayout()
        self.past_sessions_layout.setSpacing(4)
        sec3.addLayout(self.past_sessions_layout)

        sidebar_layout.addLayout(sec3)
        sidebar_layout.addStretch()

        # Footer
        footer_lbl = QLabel("Chỉ lưu trên máy.\nTự xoá sau 7 ngày.")
        footer_lbl.setFont(font_ui(8))
        footer_lbl.setStyleSheet(f"color: {self.theme.dim}; opacity: 0.7; border: none;")
        footer_lbl.setWordWrap(True)
        sidebar_layout.addWidget(footer_lbl)

        body_layout.addWidget(sidebar)
        container_layout.addWidget(body)

        self.populate_past_sessions()

    def set_session(self, session: TranscriptSession):
        if self.session:
            try:
                self.session.entry_added.disconnect(self.on_entry_added)
                self.session.session_updated.disconnect(self.update_meta)
            except Exception:
                pass

        self.session = session
        if self.session:
            self.session.entry_added.connect(self.on_entry_added)
            self.session.session_updated.connect(self.update_meta)
            self.reload_entries()
            self.update_meta()

    def reload_entries(self):
        # Clear existing entries
        for w in getattr(self, "entry_widgets", []):
            try:
                self.entries_layout.removeWidget(w)
                w.deleteLater()
            except Exception:
                pass

        self.entry_widgets = []
        if self.session:
            for i, entry in enumerate(self.session.entries):
                is_latest = (i == len(self.session.entries) - 1)
                self.add_entry_widget(entry, is_latest)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "new_items_btn") and self.new_items_btn:
            x = (self.scroll_area.width() - self.new_items_btn.width()) // 2
            y = self.scroll_area.height() - self.new_items_btn.height() - 14
            self.new_items_btn.move(max(10, x), max(10, y))

    def _on_scroll_changed(self, value: int) -> None:
        vbar = self.scroll_area.verticalScrollBar()
        at_bottom = (vbar.maximum() - value) <= 45
        if at_bottom:
            self._user_scrolled_up = False
            self._unread_count = 0
            self.new_items_btn.hide()
        else:
            self._user_scrolled_up = True

    def _on_click_new_items(self) -> None:
        self._user_scrolled_up = False
        self._unread_count = 0
        self.new_items_btn.hide()
        self._smooth_scroll_to_bottom()

    def _smooth_scroll_to_bottom(self) -> None:
        QApplication.processEvents()
        vbar = self.scroll_area.verticalScrollBar()
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(vbar.value())
        self._scroll_anim.setEndValue(vbar.maximum())
        self._scroll_anim.start()

    def _force_scroll_to_bottom(self) -> None:
        QApplication.processEvents()
        vbar = self.scroll_area.verticalScrollBar()
        vbar.setValue(vbar.maximum())
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(vbar.value())
        self._scroll_anim.setEndValue(vbar.maximum())
        self._scroll_anim.start()

    def on_entry_added(self, entry: TranscriptEntry):
        if self.entry_widgets:
            prev = self.entry_widgets[-1]
            prev.is_latest = False
            prev.setup_ui()
            prev.update()

        self.add_entry_widget(entry, True)
        self.update_meta()

        self._user_scrolled_up = False
        self._unread_count = 0
        self.new_items_btn.hide()

        from PySide6.QtCore import QTimer
        QTimer.singleShot(30, self._force_scroll_to_bottom)
        QTimer.singleShot(100, self._force_scroll_to_bottom)

    def add_entry_widget(self, entry: TranscriptEntry, is_latest: bool):
        w = TranscriptEntryWidget(entry, self.theme, is_latest)
        self.entries_layout.addWidget(w)
        self.entry_widgets.append(w)

        text = self.search_input.text().lower()
        if text:
            visible = text in (entry.source_text or "").lower() or text in (entry.target_text or "").lower()
            w.setVisible(visible)

    def update_meta(self):
        if not self.session:
            return

        duration = self.session.get_duration() if hasattr(self.session, 'get_duration') else 0
        mins = int(duration // 60)
        secs = int(duration % 60)
        count = len(self.session.entries)

        src = getattr(self.session, 'src_lang', 'EN').upper()
        tgt = getattr(self.session, 'tgt_lang', 'VI').upper()

        self.meta_lbl.setText(f"{mins:02d}:{secs:02d} · {count} câu · {src} → {tgt}")

    def filter_entries(self, text: str):
        text = text.lower()
        for w in self.entry_widgets:
            if not text:
                w.setVisible(True)
            else:
                entry = w.entry
                visible = text in (entry.source_text or "").lower() or text in (entry.target_text or "").lower()
                w.setVisible(visible)

    def populate_past_sessions(self):
        try:
            sessions = TranscriptManager.list_past_sessions()
        except Exception:
            sessions = []

        if sessions:
            for s in sessions[:3]:
                lbl = QLabel(s.get("summary_label", s.get("label", "")))
                lbl.setFont(font_ui(9))
                lbl.setStyleSheet(f"color: {self.theme.dim}; border: none;")
                self.past_sessions_layout.addWidget(lbl)
        else:
            empty_lbl = QLabel("Chưa có phiên cũ")
            empty_lbl.setFont(font_ui(9))
            empty_lbl.setStyleSheet(f"color: {self.theme.dim}; border: none;")
            self.past_sessions_layout.addWidget(empty_lbl)

    def export_transcript(self):
        checked_btn = self.format_group.checkedButton()
        ext = checked_btn.text() if checked_btn else ".srt"

        file_path, _ = QFileDialog.getSaveFileName(self, "Xuất Transcript", f"transcript_{self.session.session_id if self.session else 'export'}{ext}", f"File {ext.upper()} (*{ext})")
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
                Path(file_path).write_text(content, encoding="utf-8")
            except Exception as e:
                print("Lỗi khi lưu:", e)


# ───────────────────────────────────── Standalone Window ─────────────

class TranscriptWindow(QWidget):
    def __init__(self, session: Optional[TranscriptSession] = None, settings: Optional[AppSettings] = None, parent=None):
        super().__init__()
        from pathlib import Path
        icon_path = Path(__file__).parent.parent / "rtt_icon.ico"
        if icon_path.exists():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(560, 380)
        self.resize(720, 520)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.panel = TranscriptPanel(session, settings, self)
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
    session = TranscriptSession("en", "vi")
    session.add_entry("We call that gap the ear-voice span.", "Khoảng cách đó gọi là ear-voice span.")
    session.add_entry("It is usually two to four seconds.", "Nó thường kéo dài hai đến bốn giây.")

    win = TranscriptWindow(session, settings)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
