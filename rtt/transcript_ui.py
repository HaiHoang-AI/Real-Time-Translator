import sys
import os
from datetime import datetime, timedelta
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, Slot, QSize, QPoint, QRect, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QFont, QColor, QPainter, QPainterPath, QMouseEvent, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QScrollArea, QFrame, QCheckBox, 
    QFileDialog, QSizePolicy, QButtonGroup, QScrollBar, QSizeGrip
)

from rtt.theme import get_theme, ThemeColors, DARK, font_ui as _font_ui_str, font_mono as _font_mono_str, apply_theme
from rtt.settings import AppSettings
# In a real scenario, this import is valid. For tests, we mock it below if missing.
try:
    from rtt.history import TranscriptSession, TranscriptEntry, TranscriptManager
except ImportError:
    # Mock classes for standalone execution if rtt.history is not available
    class TranscriptEntry:
        def __init__(self, start, end, src, tgt):
            self.start_time = start
            self.end_time = end
            self.source_text = src
            self.target_text = tgt

    class TranscriptSession(QWidget):
        entry_added = Signal(TranscriptEntry)
        session_updated = Signal()
        def __init__(self):
            super().__init__()
            self.id = "session_mock"
            self.start_time = datetime.now() - timedelta(minutes=18)
            self.src_lang = "EN"
            self.tgt_lang = "VI"
            self.entries = [
                TranscriptEntry(0.5, 2.0, "Hello world", "Xin chào thế giới"),
                TranscriptEntry(3.0, 5.0, "This is a test transcript.", "Đây là bản ghi âm thử nghiệm.")
            ]
            
        def get_duration(self):
            return 18 * 60

    class TranscriptManager:
        @staticmethod
        def list_past_sessions():
            return [
                {"label": "Hôm nay · 14:02 · 18′", "id": "ses1"},
                {"label": "Hôm qua · 21:40 · 96′", "id": "ses2"}
            ]


def font_ui(weight=400):
    f = QFont(_font_ui_str())
    if isinstance(weight, QFont.Weight): f.setWeight(weight)
    elif isinstance(weight, int): f.setWeight(QFont.Weight(min(99, max(1, weight * 10 if weight <= 9 else weight))))
    return f

def font_mono(weight=400):
    f = QFont(_font_mono_str())
    if isinstance(weight, QFont.Weight): f.setWeight(weight)
    elif isinstance(weight, int): f.setWeight(QFont.Weight(min(99, max(1, weight * 10 if weight <= 9 else weight))))
    return f


class TranscriptEntryWidget(QWidget):
    def __init__(self, entry: TranscriptEntry, theme: ThemeColors, is_latest=False):
        super().__init__()
        self.entry = entry
        self.theme = theme
        self.is_latest = is_latest
        self.setup_ui()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 8, 8)
        layout.setSpacing(12)

        # Time column
        time_str = getattr(self.entry, 'time_str', '') or f"{(getattr(self.entry, 'start_time_s', 0)//60):02.0f}:{(getattr(self.entry, 'start_time_s', 0)%60):02.0f}"
        time_lbl = QLabel(time_str)
        time_lbl.setFont(font_mono(400))
        time_lbl.setFixedWidth(52)
        time_lbl.setAlignment(Qt.AlignTop | Qt.AlignRight)
        if self.is_latest:
            time_lbl.setStyleSheet(f"color: {self.theme.accent}; font-size: 10.5px;")
        else:
            time_lbl.setStyleSheet(f"color: {self.theme.dim}; font-size: 10.5px;")
        
        layout.addWidget(time_lbl)

        # Content
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        if self.entry.source_text:
            src_lbl = QLabel(self.entry.source_text)
            src_lbl.setFont(font_ui(400))
            src_lbl.setStyleSheet(f"color: {self.theme.teal}; font-size: 11.5px;")
            src_lbl.setWordWrap(True)
            content_layout.addWidget(src_lbl)

        if self.entry.target_text:
            tgt_lbl = QLabel(self.entry.target_text)
            tgt_lbl.setFont(font_ui(500))
            tgt_lbl.setStyleSheet(f"color: {self.theme.text}; font-size: 14.5px;")
            tgt_lbl.setWordWrap(True)
            content_layout.addWidget(tgt_lbl)

        layout.addLayout(content_layout)

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
        self.setFont(font_ui(500))
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
                    border-radius: 4px;
                    padding: 0 12px;
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background-color: transparent;
                    color: {self.theme.text};
                    border: 1px solid {self.theme.border};
                    border-radius: 4px;
                    padding: 0 12px;
                }}
                QPushButton:hover {{
                    background-color: {self.theme.border};
                }}
            """


class ToggleCheckBox(QCheckBox):
    def __init__(self, text, theme):
        super().__init__(text)
        self.theme = theme
        self.setFont(font_ui(400))
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


class TranscriptWindow(QWidget):
    def __init__(self, session: TranscriptSession, settings: AppSettings = None, parent=None):
        super().__init__(parent)
        self.session = None
        self.settings = settings
        self.theme = get_theme(DARK)
        self.drag_pos = None
        self._user_scrolled_up = False
        self._unread_count = 0
        
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(560, 380)
        self.resize(720, 520)
        
        self.setup_ui()
        self.set_session(session)

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Container with rounded corners and background
        self.container = QFrame(self)
        self.container.setStyleSheet(f"""
            QFrame#MainContainer {{
                background-color: {self.theme.surface};
                border-radius: 14px;
                border: 1px solid {self.theme.border};
            }}
        """)
        self.container.setObjectName("MainContainer")
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # 1. Header Bar
        header = QFrame()
        header.setFixedHeight(50)
        header.setStyleSheet(f"border-bottom: 1px solid {self.theme.border};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(12)
        
        title_lbl = QLabel("Phiên hiện tại")
        title_lbl.setFont(font_ui(600))
        title_lbl.setStyleSheet(f"color: {self.theme.text}; font-size: 14px; border: none;")
        header_layout.addWidget(title_lbl)
        
        self.meta_lbl = QLabel("00:00 · 0 câu · EN → VI")
        self.meta_lbl.setFont(font_mono(400))
        self.meta_lbl.setStyleSheet(f"color: {self.theme.dim}; font-size: 10.5px; border: none;")
        header_layout.addWidget(self.meta_lbl)
        
        header_layout.addStretch()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm trong transcript")
        self.search_input.setFont(font_ui(400))
        self.search_input.setFixedWidth(190)
        self.search_input.setFixedHeight(30)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {self.theme.raised};
                color: {self.theme.text};
                border: 1px solid {self.theme.border};
                border-radius: 15px;
                padding: 0 12px;
                font-size: 12px;
            }}
        """)
        self.search_input.textChanged.connect(self.filter_entries)
        header_layout.addWidget(self.search_input)
        
        export_btn = QPushButton("Xuất .srt")
        export_btn.setFont(font_ui(500))
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.setFixedHeight(30)
        export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.accent};
                color: {self.theme.accent_text};
                border: none;
                border-radius: 15px;
                padding: 0 16px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {self.theme.accent};
                opacity: 0.9;
            }}
        """)
        export_btn.clicked.connect(self.export_transcript)
        header_layout.addWidget(export_btn)

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
        
        container_layout.addWidget(header)
        
        # 2. Body Layout
        body = QWidget(self.container)
        body.setStyleSheet("border: none;")
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
        
        self.entries_container = QWidget(self.scroll_area)
        self.entries_layout = QVBoxLayout(self.entries_container)
        self.entries_layout.setContentsMargins(16, 16, 16, 16)
        self.entries_layout.setSpacing(4)
        self.entries_layout.setAlignment(Qt.AlignTop)

        self.scroll_area.setWidget(self.entries_container)
        left_layout.addWidget(self.scroll_area, 1)

        # Floating "↓ Câu mới" Pill Button
        self.new_items_btn = QPushButton("↓ Câu mới", self.left_wrapper)
        self.new_items_btn.setFont(font_ui(500))
        self.new_items_btn.setCursor(Qt.PointingHandCursor)
        self.new_items_btn.setFixedSize(110, 30)
        self.new_items_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.theme.accent};
                color: {self.theme.accent_text};
                border: 1px solid {self.theme.border_strong};
                border-radius: 15px;
                font-size: 11.5px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                opacity: 0.92;
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
        
        # Right Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(f"border-left: 1px solid {self.theme.border};")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(20)
        
        # Section 1: XUẤT
        sec1 = QVBoxLayout()
        sec1.setSpacing(8)
        lbl1 = QLabel("XUẤT")
        lbl1.setFont(font_mono(600))
        lbl1.setStyleSheet(f"color: {self.theme.dim}; font-size: 9.5px; border: none;")
        sec1.addWidget(lbl1)
        
        tags_layout = QHBoxLayout()
        tags_layout.setSpacing(4)
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
        lbl2.setFont(font_mono(600))
        lbl2.setStyleSheet(f"color: {self.theme.dim}; font-size: 9.5px; border: none;")
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
        lbl3.setFont(font_mono(600))
        lbl3.setStyleSheet(f"color: {self.theme.dim}; font-size: 9.5px; border: none;")
        sec3.addWidget(lbl3)
        
        self.past_sessions_layout = QVBoxLayout()
        self.past_sessions_layout.setSpacing(4)
        sec3.addLayout(self.past_sessions_layout)
        
        sidebar_layout.addLayout(sec3)
        
        sidebar_layout.addStretch()
        
        # Footer
        footer_lbl = QLabel("Chỉ lưu trên máy. Tự xoá sau 7 ngày.")
        footer_lbl.setFont(font_ui(400))
        footer_lbl.setStyleSheet(f"color: {self.theme.dim}; font-size: 11.5px; border: none;")
        footer_lbl.setWordWrap(True)
        sidebar_layout.addWidget(footer_lbl)
        
        body_layout.addWidget(sidebar)
        
        # SizeGrip at bottom right
        grip_layout = QHBoxLayout()
        grip_layout.setContentsMargins(0, 0, 4, 4)
        grip_layout.addStretch(1)
        grip = QSizeGrip(self)
        grip.setFixedSize(14, 14)
        grip_layout.addWidget(grip)
        container_layout.addLayout(grip_layout)

        main_layout.addWidget(self.container)
        
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
        if not hasattr(self, "entries_layout") or not self.entries_layout:
            return

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

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Position floating "↓ Câu mới" pill near bottom center of left panel
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

    def on_entry_added(self, entry: TranscriptEntry):
        # Unmark previous latest
        if self.entry_widgets:
            prev = self.entry_widgets[-1]
            prev.is_latest = False
            prev.setup_ui()
            prev.update()
            
        self.add_entry_widget(entry, True)
        self.update_meta()
        
        if self._user_scrolled_up:
            self._unread_count += 1
            self.new_items_btn.setText(f"↓ {self._unread_count} câu mới")
            self.new_items_btn.show()
            self.new_items_btn.raise_()
        else:
            self._smooth_scroll_to_bottom()

    def add_entry_widget(self, entry: TranscriptEntry, is_latest: bool):
        w = TranscriptEntryWidget(entry, self.theme, is_latest)
        if hasattr(self, "entries_layout") and self.entries_layout:
            self.entries_layout.addWidget(w)
        self.entry_widgets.append(w)
        
        # Apply current filter
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
        
        src = getattr(self.session, 'src_lang', 'EN')
        tgt = getattr(self.session, 'tgt_lang', 'VI')
        
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
        except:
            sessions = []
            
        for s in sessions:
            lbl = QLabel(s.get("label", ""))
            lbl.setFont(font_ui(400))
            lbl.setStyleSheet(f"color: {self.theme.text}; font-size: 12px; border: none;")
            self.past_sessions_layout.addWidget(lbl)

    def export_transcript(self):
        checked_btn = self.format_group.checkedButton()
        ext = checked_btn.text() if checked_btn else ".srt"
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Lưu Transcript", f"transcript{ext}", f"Files (*{ext})")
        if file_path:
            # Generate export content based on toggles
            inc_src = self.toggle_src.isChecked()
            inc_ts = self.toggle_ts.isChecked()
            
            content = []
            if self.session:
                for i, entry in enumerate(self.session.entries):
                    if ext == ".srt":
                        # Simplistic SRT generation
                        content.append(str(i+1))
                        def format_ts(ts):
                            h = int(ts // 3600)
                            m = int((ts % 3600) // 60)
                            s = int(ts % 60)
                            ms = int((ts % 1) * 1000)
                            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                        st = getattr(entry, 'start_time_s', getattr(entry, 'start_time', 0.0))
                        et = getattr(entry, 'end_time_s', getattr(entry, 'end_time', st + 2.0))
                        start = format_ts(st)
                        end = format_ts(et)
                        content.append(f"{start} --> {end}")
                        
                        text = []
                        if inc_src and entry.source_text:
                            text.append(entry.source_text)
                        if entry.target_text:
                            text.append(entry.target_text)
                        content.append("\n".join(text))
                        content.append("")
                    else:
                        # TXT / MD
                        parts = []
                        if inc_ts:
                            st = getattr(entry, 'start_time_s', getattr(entry, 'start_time', 0.0))
                            mins = int(st // 60)
                            secs = int(st % 60)
                            parts.append(f"[{mins:02d}:{secs:02d}]")
                        
                        text = []
                        if inc_src and entry.source_text:
                            text.append(entry.source_text)
                        if entry.target_text:
                            text.append(entry.target_text)
                            
                        parts.append(" | ".join(text) if ext == ".txt" else "\n".join(text))
                        content.append(" ".join(parts))
                        if ext == ".md":
                            content.append("---")
            
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("\n".join(content))
            except Exception as e:
                print("Lỗi khi lưu:", e)

    # Allow dragging frameless window from header
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and event.pos().y() < 50:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton and self.drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
            
    def mouseReleaseEvent(self, event: QMouseEvent):
        self.drag_pos = None


def main():
    app = QApplication(sys.argv)
    
    # Mock settings and session
    settings = AppSettings() if hasattr(sys.modules[__name__], 'AppSettings') else None
    session = TranscriptSession()
    
    window = TranscriptWindow(session, settings)
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
