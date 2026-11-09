from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QStackedWidget, QSlider, QCheckBox, 
    QComboBox, QScrollArea, QLineEdit, QButtonGroup, 
    QGraphicsDropShadowEffect, QFrame, QSizePolicy, QSizeGrip,
    QStyledItemDelegate
)
from PySide6.QtCore import Qt, Signal, Property, QRect, QPoint, QSize, QRectF, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QLinearGradient

try:
    from rtt.theme import get_theme, apply_theme, ThemeColors, DARK, font_ui as _font_ui_str, font_mono as _font_mono_str
    from rtt.settings import AppSettings
    from rtt.motion import ElasticButton, HoverLiftFrame, PhysicsSlider

    def font_ui(point_size: float = 9.5, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        f = QFont(_font_ui_str())
        if isinstance(point_size, (int, float)):
            if point_size >= 100:
                weight = QFont.Weight(min(900, max(100, int(point_size))))
                point_size = 9.5
            f.setPointSizeF(float(point_size))
        if isinstance(weight, QFont.Weight):
            f.setWeight(weight)
        elif isinstance(weight, int):
            f.setWeight(QFont.Weight(min(900, max(100, weight if weight >= 100 else weight * 100))))
        return f

    def font_mono(point_size: float = 9.5, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        f = QFont(_font_mono_str())
        if isinstance(point_size, (int, float)):
            if point_size >= 100:
                weight = QFont.Weight(min(900, max(100, int(point_size))))
                point_size = 9.5
            f.setPointSizeF(float(point_size))
        if isinstance(weight, QFont.Weight):
            f.setWeight(weight)
        elif isinstance(weight, int):
            f.setWeight(QFont.Weight(min(900, max(100, weight if weight >= 100 else weight * 100))))
        return f

except ImportError:
    class ThemeColors:
        def __init__(self):
            self.bg = "#14110E"
            self.surface = "#1C1815"
            self.raised = "#232019"
            self.text = "#F0EBE3"
            self.dim = "#A39C92"
            self.accent = "#C4885A"
            self.accent_text = "#14110E"
            self.teal = "#4B9E8E"
            self.border = "rgba(255,255,255,0.09)"
            self.border_strong = "rgba(255,255,255,0.12)"
    DARK = ThemeColors()
    def get_theme(name): return DARK
    def font_ui(weight=400): return QFont("Be Vietnam Pro", 10)
    def font_mono(weight=400): return QFont("IBM Plex Mono", 10)
    
    class AppSettings(QWidget):
        changed = Signal(str, str, object)
        class Data:
            class Display:
                font_size = 25
                bg_opacity = 0.78
                position = "Đáy"
                screen = "1"
                show_original = False
            class Model:
                stt_model = "faster-whisper large-v3"
                mt_engine = "NLLB-200"
                device = "cuda"
            class Dub:
                enabled = False
                voice = ""
                ducking = 0.18
                max_speed = 1.45
            class Glossary:
                entries = []
                strip_fillers = False
            class Ui:
                theme = "dark"
                use_custom_fonts = True
                src_lang = "en"
                tgt_lang = "vi"
            def __init__(self):
                self.display = self.Display()
                self.model = self.Model()
                self.dub = self.Dub()
                self.glossary = self.Glossary()
                self.ui = self.Ui()
        def __init__(self):
            super().__init__()
            self.data = self.Data()
        def update(self, **kwargs):
            for k, v in kwargs.items():
                for sub_k, sub_v in v.items():
                    setattr(getattr(self.data, k), sub_k, sub_v)
            self.changed.emit("", "", None)


class ToggleSwitch(QCheckBox):
    def __init__(self, theme: ThemeColors, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._thumb_pos = 1.0 if self.isChecked() else 0.0

        self._anim = QPropertyAnimation(self, b"thumbPos", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutBack)
        self.toggled.connect(self._start_anim)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt API
        # Programmatic changes (loading settings) snap without animating, and
        # also when signals are blocked (the thumb used to stay stale then).
        super().setChecked(checked)
        if self.signalsBlocked() or not self.isVisible():
            self._anim.stop()
            self._thumb_pos = 1.0 if checked else 0.0
            self.update()

    def _get_thumb_pos(self) -> float:
        return self._thumb_pos

    def _set_thumb_pos(self, pos: float) -> None:
        self._thumb_pos = pos
        self.update()

    thumbPos = Property(float, _get_thumb_pos, _set_thumb_pos)

    def _start_anim(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._thumb_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def hitButton(self, pos) -> bool:  # whole switch is clickable
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Geometry derived from the widget size (it was hard-coded for 40×22).
        w, h = float(self.width()), float(self.height())
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        radius = rect.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        is_light = getattr(self.theme, "name", "dark") == "light"
        off_col = QColor("#D9D3C9" if is_light else "#3A3F4E")
        on_col = QColor(self.theme.accent)
        t = max(0.0, min(1.0, self._thumb_pos))
        bg_col = QColor(
            int(off_col.red() + (on_col.red() - off_col.red()) * t),
            int(off_col.green() + (on_col.green() - off_col.green()) * t),
            int(off_col.blue() + (on_col.blue() - off_col.blue()) * t),
        )
        if not self.isEnabled():
            bg_col.setAlpha(110)
        painter.fillPath(path, bg_col)

        pad = 3.0
        d = h - 2 * pad
        min_x = pad
        max_x = w - pad - d
        thumb_x = min_x + (max_x - min_x) * self._thumb_pos
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawEllipse(QRectF(thumb_x, pad + 0.8, d, d))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(thumb_x, pad, d, d))
        painter.end()


class SegmentControl(QWidget):
    valueChanged = Signal(str)
    
    def __init__(self, options, theme: ThemeColors, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.options = options
        self.setFixedHeight(34)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        
        self.buttons = []
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)
        
        self.setStyleSheet(f"""
            SegmentControl {{
                background-color: {theme.raised};
                border: 1.5px solid {theme.border_strong};
                border-radius: 10px;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 7px;
                color: {theme.dim};
                padding: 4px 12px;
                font-weight: 600;
            }}
            QPushButton:checked {{
                background-color: {theme.accent};
                color: {theme.accent_text};
                border: none;
                font-weight: 700;
            }}
        """)
        
        for i, opt in enumerate(options):
            btn = QPushButton(opt)
            btn.setCheckable(True)
            font = font_ui(500)
            font.setPixelSize(12)
            btn.setFont(font)
            btn.setCursor(Qt.PointingHandCursor)
            self.btn_group.addButton(btn, i)
            layout.addWidget(btn)
            self.buttons.append(btn)
            
        self.btn_group.buttonClicked.connect(self._on_click)
        
    def _on_click(self, btn):
        self.valueChanged.emit(btn.text())
        
    def setValue(self, value):
        for btn in self.buttons:
            if btn.text() == value:
                btn.setChecked(True)
                break
                
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.theme.raised))
        painter.drawRoundedRect(self.rect(), 8, 8)


class SliderWidget(QWidget):
    valueChanged = Signal(int)
    
    def __init__(self, label, min_v, max_v, theme: ThemeColors, unit="", is_float=False):
        super().__init__()
        self.theme = theme
        self.unit = unit
        self.is_float = is_float
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl = QLabel(label)
        font = font_ui(400)
        font.setPixelSize(13)
        self.lbl.setFont(font)
        self.lbl.setStyleSheet(f"color: {theme.text};")
        # Fixed columns so stacked sliders line up (their tracks used to start
        # at different x positions depending on the label length).
        self.lbl.setFixedWidth(160)

        self.val_lbl = QLabel("0")
        val_font = font_mono(500)
        val_font.setPixelSize(12)
        self.val_lbl.setFont(val_font)
        self.val_lbl.setStyleSheet(f"color: {theme.dim};")
        self.val_lbl.setFixedWidth(58)
        self.val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.setSpacing(12)
        
        self.slider = PhysicsSlider(Qt.Horizontal)
        self.slider.setRange(min_v, max_v)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border-radius: 2px;
                height: 4px;
                background: {theme.raised};
            }}
            QSlider::handle:horizontal {{
                background: {theme.text};
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }}
            QSlider::sub-page:horizontal {{
                background: {theme.teal};
                border-radius: 2px;
            }}
        """)
        
        self.slider.valueChanged.connect(self._on_change)
        
        layout.addWidget(self.lbl)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.val_lbl)
        
    def _on_change(self, v):
        display_val = str(v)
        if self.is_float:
            display_val = f"{v/100:.2f}"
        self.val_lbl.setText(f"{display_val}{self.unit}")
        self.valueChanged.emit(v)
        
    def setValue(self, v):
        self.slider.setValue(v)


def make_scrollable_tab(widget: QWidget, theme: ThemeColors) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet(f"""
        QScrollArea {{
            background: transparent;
            border: none;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {theme.border_strong};
            border-radius: 4px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {theme.accent};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
    """)
    scroll.setWidget(widget)
    return scroll


class DisplayTab(QWidget):
    def __init__(self, theme: ThemeColors, settings: AppSettings, bridge: Optional[object] = None):
        super().__init__()
        self.theme = theme
        self.settings = settings
        self.bridge = bridge
        self.setMinimumHeight(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        page_title = QLabel("Hiển thị & ngôn ngữ")
        page_title.setStyleSheet(f"color: {theme.text}; font-size: 16px; font-weight: 600;")
        layout.addWidget(page_title)

        # App theme (there was no way to switch dark/light from the UI)
        theme_row = QHBoxLayout()
        theme_lbl = QLabel("Giao diện ứng dụng")
        theme_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px;")
        self.theme_seg = SegmentControl(["Tối", "Sáng", "Theo hệ thống"], theme)
        self.theme_seg.valueChanged.connect(self._on_theme_change)
        theme_row.addWidget(theme_lbl)
        theme_row.addStretch()
        theme_row.addWidget(self.theme_seg)
        layout.addLayout(theme_row)

        # Preview Box (paints its own "video" backdrop)
        self.preview_box = _PreviewBackdrop(theme)
        self.preview_box.setFixedHeight(96)
        preview_layout = QVBoxLayout(self.preview_box)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setAlignment(Qt.AlignCenter)
        
        self.preview_card = QFrame()
        self.preview_card.setObjectName("PreviewCard")
        card_layout = QVBoxLayout(self.preview_card)
        card_layout.setContentsMargins(14, 8, 14, 8)
        card_layout.setSpacing(4)
        
        # The real overlay is always light text on a dark card — preview that.
        self.src_lbl = QLabel("We call that gap the ear-voice span.")
        self.src_lbl.setFont(font_ui(8.5))
        self.src_lbl.setStyleSheet("color: rgba(220,220,220,0.75); background: transparent;")

        self.tgt_lbl = QLabel("Khoảng cách đó gọi là ear-voice span.")
        self.f_tgt = font_ui(9.5, QFont.Weight.DemiBold)
        self.tgt_lbl.setFont(self.f_tgt)
        self.tgt_lbl.setStyleSheet("color: #FFFFFF; background: transparent;")
        
        card_layout.addWidget(self.src_lbl)
        card_layout.addWidget(self.tgt_lbl)
        preview_layout.addWidget(self.preview_card)
        
        layout.addWidget(self.preview_box)
        
        # Sliders
        self.font_slider = SliderWidget("Cỡ chữ bản dịch", 12, 40, theme, unit="px")
        self.font_slider.valueChanged.connect(self._on_font_size)
        layout.addWidget(self.font_slider)
        
        self.width_slider = SliderWidget("Độ dài thanh phụ đề", 400, 1000, theme, unit="px")
        self.width_slider.valueChanged.connect(lambda v: self.settings.update(display={'overlay_width': v}))
        layout.addWidget(self.width_slider)

        self.opacity_slider = SliderWidget("Độ mờ nền", 0, 100, theme, unit="%")
        self.opacity_slider.valueChanged.connect(self._on_opacity_change)
        layout.addWidget(self.opacity_slider)
        
        # Segments
        align_layout = QHBoxLayout()
        align_lbl = QLabel("Căn lề phụ đề")
        align_lbl.setStyleSheet(f"color: {theme.dim}; font-size: 12.5px;")
        self.align_seg = SegmentControl(["Căn trái", "Căn giữa", "Căn phải"], theme)
        self.align_seg.valueChanged.connect(self._on_align_change)
        align_layout.addWidget(align_lbl)
        align_layout.addStretch()
        align_layout.addWidget(self.align_seg)
        layout.addLayout(align_layout)

        # ── Language Selection Controls ──────────────────────────────
        lang_box = QFrame()
        lang_box.setObjectName("LangBox")
        lang_box.setStyleSheet(f"""
            QFrame#LangBox {{
                background-color: {theme.raised};
                border: 1px solid {theme.border};
                border-radius: 12px;
            }}
            QLabel {{
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                color: {theme.text};
                font-size: 13px;
                font-weight: 600;
            }}
        """)
        lang_layout = QVBoxLayout(lang_box)
        lang_layout.setContentsMargins(14, 10, 14, 10)
        lang_layout.setSpacing(10)

        # Input Language (Source)
        src_lang_layout = QHBoxLayout()
        src_lang_lbl = QLabel("Ngôn ngữ đầu vào (Nói)")
        src_lang_lbl.setFont(font_ui(9.5, QFont.Weight.DemiBold))
        src_lang_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px; background: transparent; border: none; padding: 0; margin: 0;")
        
        self.src_lang_cb = QComboBox()
        self.src_lang_cb.setItemDelegate(QStyledItemDelegate(self.src_lang_cb))
        self.src_lang_cb.setFixedHeight(30)
        self.src_lang_cb.setCursor(Qt.PointingHandCursor)
        self.src_lang_cb.setStyleSheet(f"""
            QComboBox {{
                background-color: {theme.surface};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: 6px;
                padding: 2px 10px;
                font-size: 12.5px;
                min-width: 180px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme.raised};
                color: {theme.text};
                border: 1px solid {theme.border_strong};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 28px;
                padding: 4px 10px;
                border-radius: 5px;
                color: {theme.text};
            }}
            QComboBox QAbstractItemView::item:hover,
            QComboBox QAbstractItemView::item:selected {{
                background-color: rgba(140, 130, 120, 0.28);
                color: {theme.text};
            }}
        """)
        
        self.LANGUAGES_SRC = [
            ("Tự động (Auto detect)", "auto"),
            ("Tiếng Việt (vi)", "vi"),
            ("Tiếng Anh (en)", "en"),
            ("Tiếng Nhật (ja)", "ja"),
            ("Tiếng Trung (zh)", "zh"),
            ("Tiếng Pháp (fr)", "fr"),
            ("Tiếng Đức (de)", "de"),
            ("Tiếng Hàn (ko)", "ko"),
            ("Tiếng Tây Ban Nha (es)", "es"),
        ]
        for name, code in self.LANGUAGES_SRC:
            self.src_lang_cb.addItem(name, code)
        self.src_lang_cb.currentIndexChanged.connect(self._on_src_lang_changed)
        
        src_lang_layout.addWidget(src_lang_lbl)
        src_lang_layout.addStretch()
        src_lang_layout.addWidget(self.src_lang_cb)
        lang_layout.addLayout(src_lang_layout)

        # Output Language (Target)
        tgt_lang_layout = QHBoxLayout()
        tgt_lang_lbl = QLabel("Ngôn ngữ đầu ra (Dịch)")
        tgt_lang_lbl.setFont(font_ui(9.5, QFont.Weight.DemiBold))
        tgt_lang_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px; background: transparent; border: none; padding: 0; margin: 0;")
        
        self.tgt_lang_cb = QComboBox()
        self.tgt_lang_cb.setItemDelegate(QStyledItemDelegate(self.tgt_lang_cb))
        self.tgt_lang_cb.setFixedHeight(30)
        self.tgt_lang_cb.setCursor(Qt.PointingHandCursor)
        self.tgt_lang_cb.setStyleSheet(f"""
            QComboBox {{
                background-color: {theme.surface};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: 6px;
                padding: 2px 10px;
                font-size: 12.5px;
                min-width: 180px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme.raised};
                color: {theme.text};
                border: 1px solid {theme.border_strong};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 28px;
                padding: 4px 10px;
                border-radius: 5px;
                color: {theme.text};
            }}
            QComboBox QAbstractItemView::item:hover,
            QComboBox QAbstractItemView::item:selected {{
                background-color: rgba(140, 130, 120, 0.28);
                color: {theme.text};
            }}
        """)
        
        self.LANGUAGES_TGT = [
            ("Tiếng Việt (vi)", "vi"),
            ("Tiếng Anh (en)", "en"),
            ("Tiếng Nhật (ja)", "ja"),
            ("Tiếng Trung (zh)", "zh"),
            ("Tiếng Pháp (fr)", "fr"),
            ("Tiếng Đức (de)", "de"),
            ("Tiếng Hàn (ko)", "ko"),
            ("Tiếng Tây Ban Nha (es)", "es"),
        ]
        for name, code in self.LANGUAGES_TGT:
            self.tgt_lang_cb.addItem(name, code)
        self.tgt_lang_cb.currentIndexChanged.connect(self._on_tgt_lang_changed)

        tgt_lang_layout.addWidget(tgt_lang_lbl)
        tgt_lang_layout.addStretch()
        tgt_lang_layout.addWidget(self.tgt_lang_cb)
        lang_layout.addLayout(tgt_lang_layout)

        layout.addWidget(lang_box)

        # Toggles
        orig_layout = QHBoxLayout()
        orig_lbl = QLabel("Hiện bản gốc phía trên")
        orig_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px;")
        self.orig_tog = ToggleSwitch(theme)
        self.orig_tog.toggled.connect(lambda v: self.settings.update(display={'show_original': v}))
        orig_layout.addWidget(orig_lbl)
        orig_layout.addStretch()
        orig_layout.addWidget(self.orig_tog)
        layout.addLayout(orig_layout)
        
        font_layout = QHBoxLayout()
        font_lbl = QLabel("Dùng font Be Vietnam Pro")
        font_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px;")
        self.font_tog = ToggleSwitch(theme)
        self.font_tog.toggled.connect(lambda v: self.settings.update(ui={'use_custom_fonts': v}))
        font_layout.addWidget(font_lbl)
        font_layout.addStretch()
        font_layout.addWidget(self.font_tog)
        layout.addLayout(font_layout)
        
        # Action Buttons: Test Subtitle & Reset Position
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)

        self.test_btn = QPushButton("Hiện thử phụ đề (5s)")
        self.test_btn.setCursor(Qt.PointingHandCursor)
        self.test_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.raised};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {theme.surface};
                border-color: {theme.teal};
            }}
        """)
        self.test_btn.clicked.connect(self._on_test_subtitle)
        btn_box.addWidget(self.test_btn)

        self.reset_pos_btn = QPushButton("Đặt lại vị trí phụ đề")
        self.reset_pos_btn.setCursor(Qt.PointingHandCursor)
        self.reset_pos_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.raised};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {theme.surface};
                border-color: {theme.teal};
            }}
        """)
        self.reset_pos_btn.clicked.connect(self._on_reset_position)
        btn_box.addWidget(self.reset_pos_btn)

        layout.addLayout(btn_box)
        layout.addStretch()
        self._load_settings()

    def _on_test_subtitle(self):
        if self.bridge:
            self.bridge.committed_changed.emit("Đây là phụ đề mẫu đang hiển thị trên màn hình.")
            self.bridge.partial_changed.emit("… Thử nghiệm phụ đề")
            QTimer.singleShot(5000, lambda: (
                self.bridge.committed_changed.emit(""),
                self.bridge.partial_changed.emit("")
            ))

    def _on_reset_position(self):
        # Also forget a position the user dragged the overlay to.
        self.settings.update(display={'position': 'bottom', 'custom_pos': []})

    def _on_theme_change(self, text):
        mapping = {"Tối": "dark", "Sáng": "light", "Theo hệ thống": "auto"}
        self.settings.update(ui={'theme': mapping.get(text, "dark")})

    def _on_font_size(self, v):
        # The overlay uses point sizes; preview at a capped size so the
        # sample still fits the preview box.
        self.f_tgt.setPointSizeF(min(float(v), 20.0) * 0.6 + 4)
        self.tgt_lbl.setFont(self.f_tgt)
        self.settings.update(display={'font_size': v})

    def _on_opacity_change(self, v):
        self._apply_preview_opacity(v / 100.0)
        self.settings.update(display={'bg_opacity': v / 100.0})

    def _apply_preview_opacity(self, opacity: float) -> None:
        self.preview_card.setStyleSheet(
            f"QFrame#PreviewCard {{ background-color: rgba(18, 20, 26, {opacity:.2f}); "
            f"border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; }}"
        )

    def _on_align_change(self, text):
        mapping = {"Căn trái": "left", "Căn giữa": "center", "Căn phải": "right"}
        align = mapping.get(text, "center")
        qt_align = Qt.AlignLeft if align == "left" else (Qt.AlignRight if align == "right" else Qt.AlignCenter)
        self.tgt_lbl.setAlignment(qt_align)
        self.src_lbl.setAlignment(qt_align)
        self.settings.update(display={'alignment': align})

    def _on_src_lang_changed(self, idx: int):
        code = self.src_lang_cb.itemData(idx)
        if code:
            self.settings.update(ui={'src_lang': code})

    def _on_tgt_lang_changed(self, idx: int):
        code = self.tgt_lang_cb.itemData(idx)
        if code:
            self.settings.update(ui={'tgt_lang': code})
        
    def _load_settings(self):
        d = self.settings.data
        self.font_slider.setValue(d.display.font_size)
        self.width_slider.setValue(getattr(d.display, 'overlay_width', 680))
        self.opacity_slider.setValue(int(d.display.bg_opacity * 100))
        align_map = {"left": "Căn trái", "center": "Căn giữa", "right": "Căn phải"}
        self.align_seg.setValue(align_map.get(getattr(d.display, 'alignment', 'center'), "Căn giữa"))
        self.orig_tog.setChecked(d.display.show_original)
        self.font_tog.setChecked(d.ui.use_custom_fonts)
        theme_map = {"dark": "Tối", "light": "Sáng", "auto": "Theo hệ thống"}
        self.theme_seg.setValue(theme_map.get(d.ui.theme, "Tối"))
        self._apply_preview_opacity(d.display.bg_opacity)

        # Set combobox current indexes
        src_code = getattr(d.ui, 'src_lang', 'auto')
        for i, (_, code) in enumerate(self.LANGUAGES_SRC):
            if code == src_code:
                self.src_lang_cb.blockSignals(True)
                self.src_lang_cb.setCurrentIndex(i)
                self.src_lang_cb.blockSignals(False)
                break

        tgt_code = getattr(d.ui, 'tgt_lang', 'vi')
        for i, (_, code) in enumerate(self.LANGUAGES_TGT):
            if code == tgt_code:
                self.tgt_lang_cb.blockSignals(True)
                self.tgt_lang_cb.setCurrentIndex(i)
                self.tgt_lang_cb.blockSignals(False)
                break



class _PreviewBackdrop(QWidget):
    """Striped stand-in for a video frame behind the subtitle preview.

    (Previously painted by the parent tab, underneath this child — which then
    covered it with its own background, so the stripes never showed.)
    """

    def __init__(self, theme: ThemeColors, parent=None):
        super().__init__(parent)
        self.theme = theme

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box_rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(QRectF(box_rect), 12, 12)
        painter.setClipPath(path)

        is_light = getattr(self.theme, "name", "dark") == "light"
        painter.fillRect(box_rect, QColor("#5B6475" if is_light else "#0E1015"))
        pen = QPen(QColor(255, 255, 255, 26 if is_light else 16))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        spacing = 15
        for i in range(-box_rect.height(), box_rect.width(), spacing):
            painter.drawLine(i, 0, i + box_rect.height(), box_rect.height())
        painter.end()


class ModelCard(HoverLiftFrame):
    clicked = Signal(str)
    def __init__(self, title, vram, wer, lat, prog, rec, theme: ThemeColors):
        super().__init__()
        self.title_str = title
        self.theme = theme
        self.is_active = False
        self._scale = 1.0
        self.setFixedHeight(64)
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 12, 13, 12)
        
        left_layout = QVBoxLayout()
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px; font-weight: 500;")
        
        sub_lbl = QLabel(f"WER {wer} · VRAM {vram}")
        f_sub = font_mono(400)
        f_sub.setPixelSize(11)
        sub_lbl.setFont(f_sub)
        sub_lbl.setStyleSheet(f"color: {theme.dim};")
        
        left_layout.addWidget(title_lbl)
        left_layout.addWidget(sub_lbl)
        
        right_layout = QVBoxLayout()
        right_layout.setAlignment(Qt.AlignRight)
        
        lat_lbl = QLabel(f"{lat}s")
        lat_lbl.setFont(f_sub)
        lat_lbl.setStyleSheet(f"color: {theme.text};")
        
        prog_bar = QWidget()
        prog_bar.setFixedSize(60, 4)
        prog_bar.setStyleSheet(f"background-color: {theme.border}; border-radius: 2px;")
        
        # custom paint for progress? simplified for now
        
        if rec:
            rec_lbl = QLabel(rec)
            rec_lbl.setFont(f_sub)
            rec_lbl.setStyleSheet(f"color: {theme.teal if rec=='ĐỀ XUẤT' else theme.dim};")
            right_layout.addWidget(rec_lbl)
            
        right_layout.addWidget(lat_lbl)
        
        layout.addLayout(left_layout)
        layout.addStretch()
        layout.addLayout(right_layout)
        
    def set_active(self, active):
        self.is_active = active
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        
        painter.fillPath(path, QColor(self.theme.raised))
        
        if self.is_active:
            pen = QPen(QColor(self.theme.teal))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawPath(path)
            
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.title_str)


class ModelTab(QWidget):
    def __init__(self, theme: ThemeColors, settings: AppSettings):
        super().__init__()
        self.theme = theme
        self.settings = settings
        self.setMinimumHeight(540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Chọn mô hình AI trên máy bạn")
        title.setStyleSheet(f"color: {theme.text}; font-size: 16px; font-weight: 600;")
        sub = QLabel("Tự động sử dụng GPU CUDA để tối ưu tốc độ nhận dạng & dịch thuật.")
        sub.setStyleSheet(f"color: {theme.dim}; font-size: 12.5px;")
        layout.addWidget(title)
        layout.addWidget(sub)

        # STT Cards Section
        stt_hdr = QLabel("KHÂU NHẬN DẠNG GIỌNG NÓI (STT)")
        stt_hdr.setFont(font_mono(600))
        stt_hdr.setStyleSheet(f"color: {theme.dim}; font-size: 9.5px;")
        layout.addWidget(stt_hdr)

        self.stt_cards = {}
        stt_models_data = [
            ("moonshine-medium", "moonshine medium (streaming)", "0.5 GB", "3.2%", "0.08", 95, "ĐỀ XUẤT • SIÊU NHANH"),
            ("large-v3-turbo", "faster-whisper large-v3-turbo", "1.5 GB", "4.0%", "0.40", 75, "Whisper Turbo"),
            ("moonshine-tiny", "moonshine tiny (streaming)", "0.1 GB", "8.5%", "0.03", 25, "cực nhẹ"),
            ("small", "faster-whisper small", "0.5 GB", "9.8%", "0.20", 30, "máy yếu"),
            ("large-v3", "faster-whisper large-v3", "3.0 GB", "3.5%", "1.20", 90, "chính xác nhất"),
        ]

        for key, title_str, vram, wer, lat, prog, rec in stt_models_data:
            c = ModelCard(title_str, vram, wer, lat, prog, rec, theme)
            c.clicked.connect(lambda _, k=key: self._on_stt_select(k))
            layout.addWidget(c)
            self.stt_cards[key] = c

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {theme.border};")
        layout.addWidget(sep)

        # MT Cards Section
        mt_lbl = QLabel("KHÂU DỊCH THUẬT (MT)")
        mt_lbl.setFont(font_mono(600))
        mt_lbl.setStyleSheet(f"color: {theme.dim}; font-size: 9.5px;")
        layout.addWidget(mt_lbl)

        # 3 columns grid: six cards squeezed into one row truncated their text
        # at the default window width.
        from PySide6.QtWidgets import QGridLayout

        mt_layout = QGridLayout()
        mt_layout.setHorizontalSpacing(10)
        mt_layout.setVerticalSpacing(10)

        self.mt_frames = {}

        mt_options = [
            ("gemini-flash", "Gemini 2.0 Flash", "ĐỀ XUẤT (Cloud AI)", "Dịch siêu mượt, hiểu ngữ cảnh video"),
            ("llama-3b", "Llama 3.2 3B", "Offline Nhanh (+0.3s)", "Thuần Việt 100%, không lẫn chữ Hán"),
            ("qwen-3b", "Qwen 2.5 3B", "Offline Nhanh (+0.3s)", "Ngữ cảnh AI mượt, nhẹ GPU"),
            ("qwen-7b", "Qwen 2.5 7B", "Offline Chuẩn (+0.6s)", "Ngữ cảnh AI sâu, chuẩn xác cao"),
            ("nllb-1.3b", "NLLB-200 1.3B", "Offline (+1.5s)", "Chất lượng cao, không cần mạng"),
            ("nllb", "NLLB-200 600M", "Offline Nhanh (+0.8s)", "Nhẹ, tiết kiệm VRAM"),
        ]

        for key, name, sub_text, desc in mt_options:
            frame = QFrame()
            frame.setObjectName("MtCard")
            frame.setAttribute(Qt.WA_Hover, True)
            frame.setMinimumHeight(74)
            frame.setMinimumWidth(110)
            frame.setCursor(Qt.PointingHandCursor)
            frame_layout = QVBoxLayout(frame)
            frame_layout.setContentsMargins(12, 10, 12, 10)

            t_lbl = QLabel(name)
            t_lbl.setStyleSheet(f"color: {theme.text}; font-size: 12.5px; font-weight: 600;")

            s_lbl = QLabel(sub_text)
            s_lbl.setFont(font_mono())
            s_lbl.setStyleSheet(f"color: {theme.teal if 'ĐỀ XUẤT' in sub_text else theme.dim}; font-size: 10.5px;")

            d_lbl = QLabel(desc)
            d_lbl.setStyleSheet(f"color: {theme.dim}; font-size: 10.5px;")
            d_lbl.setWordWrap(True)

            frame_layout.addWidget(t_lbl)
            frame_layout.addWidget(s_lbl)
            frame_layout.addWidget(d_lbl)

            # Make frame clickable via mousePressEvent override
            def make_click_handler(k):
                def handler(event):
                    if event.button() == Qt.LeftButton:
                        self._on_mt_select(k)
                return handler

            frame.mousePressEvent = make_click_handler(key)
            idx = len(self.mt_frames)
            mt_layout.addWidget(frame, idx // 3, idx % 3)
            self.mt_frames[key] = frame

        layout.addLayout(mt_layout)

        # Speed Mode Toggle
        speed_frame = QFrame()
        speed_frame.setObjectName("SpeedCard")
        speed_frame.setStyleSheet(
            f"QFrame#SpeedCard {{ background-color: {theme.raised}; border-radius: 12px; "
            f"border: 1px solid {theme.border}; }}"
        )
        speed_layout = QHBoxLayout(speed_frame)
        speed_layout.setContentsMargins(14, 10, 14, 10)

        speed_text_layout = QVBoxLayout()
        speed_text_layout.setSpacing(2)
        speed_title = QLabel("Chế độ tốc độ cao (Speed Mode)")
        speed_title.setStyleSheet(
            f"color: {theme.text}; font-size: 14px; font-weight: bold; border: none;"
        )
        speed_desc = QLabel("Whisper tiny + NLLB 600M + greedy — độ trễ ~0.5s, chất lượng cơ bản")
        speed_desc.setStyleSheet(f"color: {theme.dim}; font-size: 11px; border: none;")
        speed_text_layout.addWidget(speed_title)
        speed_text_layout.addWidget(speed_desc)
        speed_layout.addLayout(speed_text_layout, 1)

        self.speed_tog = ToggleSwitch(theme)
        self.speed_tog.setChecked(self.settings.data.model.speed_mode)
        self.speed_tog.toggled.connect(self._on_speed_toggle)
        speed_layout.addWidget(self.speed_tog)
        layout.addWidget(speed_frame)

        # Summary & Restart Notice
        self.summary = QLabel("Tổng ước tính: ~1.9s — chuẩn xác & mượt mà cho phụ đề.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(
            f"background-color: {theme.raised}; color: {theme.text}; "
            f"padding: 10px 12px; border-radius: 10px; font-size: 12.5px;"
        )
        layout.addWidget(self.summary)

        notice = QLabel("Lưu ý: Thay đổi mô hình sẽ áp dụng hoàn toàn ở lần khởi động lại ứng dụng.")
        notice.setStyleSheet(f"color: {theme.dim}; font-size: 11px; font-style: italic;")
        layout.addWidget(notice)

        layout.addStretch()
        self._load_settings()

    def _on_stt_select(self, key: str):
        self.settings.update(model={'stt_model': key})
        self._load_settings()

    def _on_mt_select(self, key: str):
        self.settings.update(model={'mt_engine': key})
        self._load_settings()

    def _on_speed_toggle(self, checked: bool):
        self.settings.update(model={'speed_mode': checked})
        self._load_settings()

    def _load_settings(self):
        m_cfg = self.settings.data.model
        curr_stt = m_cfg.stt_model
        curr_mt = m_cfg.mt_engine
        speed = m_cfg.speed_mode

        # Update STT cards UI
        for key, card in self.stt_cards.items():
            is_active = (
                (key == curr_stt)
                or (key == "moonshine-medium" and curr_stt in ("auto", "moonshine", "moonshine-medium"))
                or (key == "large-v3-turbo" and curr_stt in ("whisper", "turbo", "faster-whisper large-v3-turbo"))
            )
            card.set_active(is_active)

        # Update MT frames UI — selectors scoped to the card itself: the old
        # bare "border: 2px solid" cascaded onto every label inside the card
        # (that drew a box around each text line of the selected engine).
        for key, frame in self.mt_frames.items():
            is_active = (
                (key == curr_mt)
                or (key == "gemini-flash" and curr_mt in ("auto", "llm-hybrid"))
                or (key == "llama-3b" and curr_mt in ("llama", "llama3.2", "llama-3.2", "llama3.2:3b"))
                or (key == "qwen-3b" and curr_mt == "qwen")
            )
            border = f"2px solid {self.theme.teal}" if is_active else "1px solid transparent"
            frame.setStyleSheet(f"""
                QFrame#MtCard {{
                    background-color: {self.theme.raised};
                    border-radius: 12px;
                    border: {border};
                }}
                QFrame#MtCard:hover {{
                    border: {border if is_active else f"1px solid {self.theme.border_strong}"};
                }}
                QFrame#MtCard QLabel {{ background: transparent; border: none; }}
            """)
            # Speed mode forces NLLB 600M: show the choice as inactive then.
            frame.setEnabled(not speed)

        # Update speed toggle
        self.speed_tog.blockSignals(True)
        self.speed_tog.setChecked(speed)
        self.speed_tog.blockSignals(False)

        # Update summary text
        if speed:
            self.summary.setText(
                "Chế độ tốc độ cao: ~0.5s (Whisper tiny + NLLB 600M + greedy) — nhanh nhất có thể!"
            )
        else:
            if curr_stt in ("moonshine-tiny", "tiny-streaming"):
                stt_time = 0.03
            elif curr_stt in ("moonshine", "moonshine-medium", "medium-streaming", "auto"):
                stt_time = 0.08
            elif curr_stt in ("large-v3-turbo", "turbo"):
                stt_time = 0.40
            elif curr_stt == "small":
                stt_time = 0.20
            else:
                stt_time = 1.20
            if curr_mt in ("gemini-flash", "llm-hybrid", "auto"):
                mt_time = 0.35
                engine_desc = "Gemini Flash AI"
            elif curr_mt in ("llama", "llama-3b", "llama3.2", "llama-3.2", "llama3.2:3b"):
                mt_time = 0.30
                engine_desc = "Llama 3.2 3B Local"
            elif curr_mt in ("qwen", "qwen-3b"):
                mt_time = 0.30
                engine_desc = "Qwen 2.5 3B Local"
            elif curr_mt == "qwen-7b":
                mt_time = 0.60
                engine_desc = "Qwen 2.5 7B Local"
            elif curr_mt == "nllb-1.3b":
                mt_time = 1.50
                engine_desc = "NLLB 1.3B Offline"
            else:
                mt_time = 0.80
                engine_desc = "NLLB 600M Offline"
            tot = stt_time + mt_time
            self.summary.setText(
                f"Ước tính độ trễ: ~{tot:.2f}s  (STT: {stt_time:.2f}s + MT {engine_desc}: {mt_time:.2f}s) — Chuẩn xác & mượt mà."
            )


class GlossaryRow(QFrame):
    """One editable 'source → target' glossary pair."""

    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, source: str, target: str, theme: ThemeColors):
        super().__init__()
        self.setObjectName("GlossaryRow")
        self.setStyleSheet(f"""
            QFrame#GlossaryRow {{
                background-color: {theme.raised};
                border: 1px solid {theme.border};
                border-radius: 10px;
            }}
            QLineEdit {{
                background: {theme.surface};
                border: 1px solid {theme.border};
                border-radius: 7px;
                padding: 5px 9px;
                font-size: 12.5px;
            }}
            QLineEdit:focus {{ border-color: {theme.accent}; }}
            QLabel {{ background: transparent; color: {theme.dim}; }}
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 6, 6)
        lay.setSpacing(8)
        self.src = QLineEdit(source)
        self.src.setPlaceholderText("Thuật ngữ gốc (vd: GPU, Kubernetes)")
        self.tgt = QLineEdit(target)
        self.tgt.setPlaceholderText("Bản dịch (hoặc: giữ nguyên)")
        arrow = QLabel("→")
        for edit in (self.src, self.tgt):
            edit.editingFinished.connect(self.changed.emit)
        del_btn = QPushButton("Xoá")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setToolTip("Xoá thuật ngữ này")
        del_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {theme.dim}; border: none;
                          padding: 4px 8px; font-size: 12px; }}
            QPushButton:hover {{ color: {theme.error}; }}
        """)
        del_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        lay.addWidget(self.src, 1)
        lay.addWidget(arrow)
        lay.addWidget(self.tgt, 1)
        lay.addWidget(del_btn)

    def entry(self) -> dict:
        return {"source": self.src.text().strip(), "target": self.tgt.text().strip()}


class GlossaryTab(QWidget):
    """User glossary: terms the translator must render a fixed way.

    The tab existed but was never shown and its buttons did nothing, so the
    glossary (used by the term locker and the LLM prompts) was uneditable.
    """

    def __init__(self, theme: ThemeColors, settings: AppSettings):
        super().__init__()
        self.theme = theme
        self.settings = settings
        self.rows: list[GlossaryRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Thuật ngữ & tên riêng")
        title.setStyleSheet(f"color: {theme.text}; font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        desc = QLabel(
            "Ép bộ dịch giữ đúng tên riêng, thuật ngữ, tên sản phẩm. "
            "Ghi “giữ nguyên” ở cột bản dịch để giữ nguyên từ gốc."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.dim}; font-size: 12.5px;")
        layout.addWidget(desc)

        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(6)
        layout.addLayout(self.list_layout)

        self.empty_lbl = QLabel("Chưa có thuật ngữ nào.")
        self.empty_lbl.setStyleSheet(f"color: {theme.dim}; font-size: 12px; padding: 6px 2px;")
        layout.addWidget(self.empty_lbl)

        btn_layout = QHBoxLayout()
        add_btn = ElasticButton("+ Thêm thuật ngữ")
        add_btn.setStyleSheet(f"""
            QPushButton {{
                border: 1px dashed {theme.border_strong};
                border-radius: 9px;
                color: {theme.text};
                padding: 9px 14px;
                background: transparent;
            }}
            QPushButton:hover {{ background: {theme.raised}; border-color: {theme.accent}; }}
        """)
        add_btn.clicked.connect(self._add_empty_row)

        imp_btn = ElasticButton("Nhập từ file .csv")
        imp_btn.setToolTip("Mỗi dòng: thuật ngữ gốc, bản dịch")
        imp_btn.setStyleSheet(f"""
            QPushButton {{ border: none; color: {theme.teal}; background: transparent; padding: 9px 6px; }}
            QPushButton:hover {{ color: {theme.accent}; }}
        """)
        imp_btn.clicked.connect(self._import_csv)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(imp_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addSpacing(8)
        self.caps_tog = self._toggle_row(
            layout, "Tự giữ từ viết HOA (GPU, API, NASA…)", "auto_lock_caps"
        )
        self.camel_tog = self._toggle_row(
            layout, "Tự giữ tên dạng CamelCase (OpenAI, GitHub…)", "auto_lock_camel"
        )
        self.filler_tog = self._toggle_row(
            layout, "Bỏ từ đệm tiếng Anh (uh, um, erm…) trước khi dịch", "strip_fillers"
        )
        layout.addStretch()
        self._load_settings()

    def _toggle_row(self, parent_layout, text: str, key: str) -> ToggleSwitch:
        row = QHBoxLayout()
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {self.theme.text}; font-size: 13px;")
        tog = ToggleSwitch(self.theme)
        tog.toggled.connect(lambda v, k=key: self.settings.update(glossary={k: v}))
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(tog)
        parent_layout.addLayout(row)
        return tog

    # ── rows ───────────────────────────────────────────────────────
    def _add_row(self, source: str = "", target: str = "") -> GlossaryRow:
        row = GlossaryRow(source, target, self.theme)
        row.changed.connect(self._save)
        row.remove_requested.connect(self._remove_row)
        self.list_layout.addWidget(row)
        self.rows.append(row)
        self.empty_lbl.setVisible(False)
        return row

    def _add_empty_row(self) -> None:
        row = self._add_row()
        row.src.setFocus()

    def _remove_row(self, row: GlossaryRow) -> None:
        if row in self.rows:
            self.rows.remove(row)
            self.list_layout.removeWidget(row)
            row.deleteLater()
        self.empty_lbl.setVisible(not self.rows)
        self._save()

    def _save(self) -> None:
        entries = [r.entry() for r in self.rows if r.entry()["source"]]
        if entries != list(self.settings.data.glossary.entries):
            self.settings.set_glossary_entries(entries)

    def _import_csv(self) -> None:
        import csv

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        path, _ = QFileDialog.getOpenFileName(
            self, "Nhập thuật ngữ", "", "CSV / TXT (*.csv *.txt);;Tất cả (*.*)"
        )
        if not path:
            return
        added = 0
        existing = {r.entry()["source"].lower() for r in self.rows}
        try:
            with open(path, newline="", encoding="utf-8-sig") as fh:
                sample = fh.read(2048)
                fh.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel
                for cols in csv.reader(fh, dialect):
                    if len(cols) < 2 or not cols[0].strip():
                        continue
                    src, tgt = cols[0].strip(), cols[1].strip()
                    if src.lower() in ("source", "thuật ngữ", "term") or src.lower() in existing:
                        continue
                    self._add_row(src, tgt)
                    existing.add(src.lower())
                    added += 1
        except Exception as exc:
            QMessageBox.warning(self, "Không đọc được file", str(exc))
            return
        self._save()
        QMessageBox.information(self, "Đã nhập thuật ngữ", f"Đã thêm {added} thuật ngữ.")

    def _load_settings(self):
        g = self.settings.data.glossary
        for e in g.entries:
            if isinstance(e, dict) and e.get("source"):
                self._add_row(e.get("source", ""), e.get("target", ""))
        self.empty_lbl.setVisible(not self.rows)
        self.caps_tog.setChecked(g.auto_lock_caps)
        self.camel_tog.setChecked(g.auto_lock_camel)
        self.filler_tog.setChecked(g.strip_fillers)


class DubTab(QWidget):
    def __init__(self, theme: ThemeColors, settings: AppSettings):
        super().__init__()
        self.theme = theme
        self.settings = settings
        self.setMinimumHeight(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(24)
        
        header = QHBoxLayout()
        title = QLabel("Chế độ thuyết minh")
        title.setStyleSheet(f"color: {theme.text}; font-size: 16px; font-weight: 600;")
        self.dub_tog = ToggleSwitch(theme)
        self.dub_tog.toggled.connect(lambda v: self.settings.update(dub={'enabled': v}))
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.dub_tog)
        layout.addLayout(header)
        
        voice_layout = QHBoxLayout()
        voice_lbl = QLabel("Giọng đọc")
        voice_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px;")
        self.voice_cb = QComboBox()
        self.voice_cb.setItemDelegate(QStyledItemDelegate(self.voice_cb))
        self.voice_cb.setStyleSheet(f"""
            QComboBox {{
                background-color: {theme.raised};
                border-radius: 6px;
                color: {theme.text};
                padding: 6px 12px;
                border: 1px solid {theme.border};
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme.raised};
                color: {theme.text};
                border: 1px solid {theme.border_strong};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 28px;
                padding: 4px 10px;
                border-radius: 5px;
                color: {theme.text};
            }}
            QComboBox QAbstractItemView::item:hover,
            QComboBox QAbstractItemView::item:selected {{
                background-color: rgba(140, 130, 120, 0.28);
                color: {theme.text};
            }}
        """)
        
        # Real installed Piper voices (project models/ dir, not the CWD). The
        # old code listed two fake voices and its addItems() immediately
        # overwrote the saved voice with the first fake one.
        try:
            from rtt.dub import DEFAULT_VOICE, DEFAULT_VOICE_DIR
        except Exception:
            DEFAULT_VOICE, DEFAULT_VOICE_DIR = "vi_VN-vais1000-medium", Path("models/piper")
        voices = sorted(p.stem for p in Path(DEFAULT_VOICE_DIR).glob("*.onnx")) if Path(DEFAULT_VOICE_DIR).exists() else []
        current = settings.data.dub.voice or DEFAULT_VOICE
        if current not in voices:
            voices.insert(0, current)
        self.voice_cb.blockSignals(True)
        for v in voices:
            installed = (Path(DEFAULT_VOICE_DIR) / f"{v}.onnx").exists()
            self.voice_cb.addItem(v if installed else f"{v} (chưa tải)", v)
        self.voice_cb.blockSignals(False)
        self.voice_cb.currentIndexChanged.connect(
            lambda i: self.settings.update(dub={'voice': self.voice_cb.itemData(i)})
        )
        voice_layout.addWidget(voice_lbl)
        voice_layout.addStretch()
        voice_layout.addWidget(self.voice_cb)
        layout.addLayout(voice_layout)

        if not any((Path(DEFAULT_VOICE_DIR) / f"{v}.onnx").exists() for v in voices):
            missing = QLabel(
                "Chưa có giọng đọc nào. Tải giọng tiếng Việt bằng lệnh:\n"
                f"uv run python -m piper.download_voices --data-dir models/piper {DEFAULT_VOICE}"
            )
            missing.setWordWrap(True)
            missing.setTextInteractionFlags(Qt.TextSelectableByMouse)
            missing.setStyleSheet(
                f"background-color: {theme.raised}; color: {theme.warning}; padding: 10px 12px;"
                f" border-radius: 10px; font-size: 12px;"
            )
            layout.addWidget(missing)
        
        self.duck_slider = SliderWidget("Hạ tiếng gốc", 0, 100, theme, unit="%")
        self.duck_slider.valueChanged.connect(lambda v: self.settings.update(dub={'ducking': v/100.0}))
        layout.addWidget(self.duck_slider)
        
        self.speed_slider = SliderWidget("Tốc độ đọc tối đa", 100, 200, theme, unit="×", is_float=True)
        self.speed_slider.valueChanged.connect(lambda v: self.settings.update(dub={'max_speed': v/100.0}))
        layout.addWidget(self.speed_slider)

        echo_row = QHBoxLayout()
        echo_txt = QVBoxLayout()
        echo_txt.setSpacing(2)
        echo_lbl = QLabel("Chống vọng giọng thuyết minh")
        echo_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px;")
        echo_desc = QLabel("Không thu lại chính giọng đọc → tránh dịch lặp vô hạn (khuyên dùng)")
        echo_desc.setStyleSheet(f"color: {theme.dim}; font-size: 11.5px;")
        echo_txt.addWidget(echo_lbl)
        echo_txt.addWidget(echo_desc)
        self.echo_tog = ToggleSwitch(theme)
        self.echo_tog.toggled.connect(lambda v: self.settings.update(dub={'block_self_echo': v}))
        echo_row.addLayout(echo_txt)
        echo_row.addStretch()
        echo_row.addWidget(self.echo_tog)
        layout.addLayout(echo_row)

        info = QLabel("Khi bật thuyết minh, giọng đọc trễ ~3s so với hình và âm lượng các ứng dụng khác tự động giảm.")
        info.setWordWrap(True)
        info.setStyleSheet(f"background-color: {theme.raised}; color: {theme.dim}; padding: 12px; border-radius: 10px; font-size: 12.5px;")
        layout.addWidget(info)

        layout.addStretch()
        self._load_settings()

    def _load_settings(self):
        d = self.settings.data.dub
        self.dub_tog.setChecked(d.enabled)
        self.duck_slider.setValue(int(d.ducking * 100))
        self.speed_slider.setValue(int(d.max_speed * 100))
        self.echo_tog.setChecked(getattr(d, "block_self_echo", True))
        idx = self.voice_cb.findData(d.voice)
        if idx >= 0:
            self.voice_cb.blockSignals(True)
            self.voice_cb.setCurrentIndex(idx)
            self.voice_cb.blockSignals(False)


class SummaryTab(QWidget):
    """Tab 5: AI Summarization & Session Management settings."""

    def __init__(self, theme: ThemeColors, settings: AppSettings):
        super().__init__()
        self.theme = theme
        self.settings = settings
        self.setMinimumHeight(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # Title & Subtitle
        title = QLabel("Tóm tắt AI & Quản lý phiên")
        title.setStyleSheet(f"color: {theme.text}; font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        sub = QLabel("Sử dụng Google Gemini AI để tóm tắt các cuộc họp, bài giảng hoặc video dài.")
        sub.setStyleSheet(f"color: {theme.dim}; font-size: 12.5px;")
        layout.addWidget(sub)

        # 1. API Key Input
        api_box = QVBoxLayout()
        api_box.setSpacing(6)

        api_header = QHBoxLayout()
        api_lbl = QLabel("Google Gemini API Key")
        api_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px; font-weight: 500;")
        api_header.addWidget(api_lbl)

        link_lbl = QLabel(f"<a href='https://aistudio.google.com/apikey' style='color:{theme.teal}; text-decoration:none;'>Lấy API key miễn phí ↗</a>")
        link_lbl.setOpenExternalLinks(True)
        link_lbl.setStyleSheet("font-size: 11.5px;")
        api_header.addStretch()
        api_header.addWidget(link_lbl)
        api_box.addLayout(api_header)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)

        self.api_input = QLineEdit()
        self.api_input.setEchoMode(QLineEdit.Password)
        self.api_input.setPlaceholderText("Dán Gemini API Key (AIzaSy...) tại đây")
        self.api_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {theme.raised};
                color: {theme.text};
                border: 1px solid {theme.border};
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 12px;
            }}
        """)
        # Commit when editing finishes (not on every keystroke).
        self.api_input.editingFinished.connect(
            lambda: self.settings.update(summary={'api_key': self.api_input.text().strip()})
        )
        key_row.addWidget(self.api_input, 1)

        self.show_key_btn = ElasticButton("Hiện")
        self.show_key_btn.setFixedSize(56, 34)
        self.show_key_btn.setCursor(Qt.PointingHandCursor)
        self.show_key_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.raised};
                color: {theme.dim};
                border: 1px solid {theme.border};
                border-radius: 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                color: {theme.text};
            }}
        """)
        self.show_key_btn.clicked.connect(self._toggle_show_key)
        key_row.addWidget(self.show_key_btn)
        api_box.addLayout(key_row)

        layout.addLayout(api_box)

        # 2. Summary Style
        style_box = QHBoxLayout()
        style_lbl = QLabel("Định dạng tóm tắt mặc định")
        style_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px;")
        style_box.addWidget(style_lbl)

        self.style_cb = QComboBox()
        self.style_cb.setItemDelegate(QStyledItemDelegate(self.style_cb))
        self.style_cb.addItems(["Gạch đầu dòng (Súc tích)", "Đoạn văn ngắn (Liền mạch)", "Báo cáo chi tiết (Đầy đủ)"])
        self.style_cb.setStyleSheet(f"""
            QComboBox {{
                background-color: {theme.raised};
                border-radius: 6px;
                color: {theme.text};
                padding: 6px 12px;
                border: 1px solid {theme.border};
                min-width: 180px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {theme.raised};
                color: {theme.text};
                border: 1px solid {theme.border_strong};
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: rgba(255, 255, 255, 0.08);
                color: {theme.text};
            }}
        """)
        self.style_cb.currentIndexChanged.connect(self._on_style_changed)
        style_box.addStretch()
        style_box.addWidget(self.style_cb)
        layout.addLayout(style_box)

        # 3. Auto New Session Timeout
        auto_box = QHBoxLayout()
        auto_lbl = QLabel("Tự tạo phiên mới khi im lặng")
        auto_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px;")
        auto_box.addWidget(auto_lbl)

        self.auto_cb = QComboBox()
        self.auto_cb.setItemDelegate(QStyledItemDelegate(self.auto_cb))
        self.auto_cb.addItems(["Sau 5 phút", "Sau 10 phút (Khuyên dùng)", "Sau 15 phút", "Sau 30 phút", "Tắt (Không tự tạo)"])
        self.auto_cb.setStyleSheet(self.style_cb.styleSheet())
        self.auto_cb.currentIndexChanged.connect(self._on_auto_timeout_changed)
        auto_box.addStretch()
        auto_box.addWidget(self.auto_cb)
        layout.addLayout(auto_box)

        # 4. Auto Cleanup Days
        cleanup_box = QHBoxLayout()
        cleanup_lbl = QLabel("Thời gian lưu trữ phiên")
        cleanup_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px;")
        cleanup_box.addWidget(cleanup_lbl)

        self.cleanup_cb = QComboBox()
        self.cleanup_cb.setItemDelegate(QStyledItemDelegate(self.cleanup_cb))
        self.cleanup_cb.addItems(["Tự xoá sau 7 ngày", "Tự xoá sau 14 ngày", "Tự xoá sau 30 ngày (Khuyên dùng)", "Lưu vĩnh viễn (Không tự xoá)"])
        self.cleanup_cb.setStyleSheet(self.style_cb.styleSheet())
        self.cleanup_cb.currentIndexChanged.connect(self._on_cleanup_changed)
        cleanup_box.addStretch()
        cleanup_box.addWidget(self.cleanup_cb)
        layout.addLayout(cleanup_box)

        # Info Box
        info = QLabel("Mẹo: Bạn có thể chọn cùng lúc nhiều phiên trong tab Lịch sử hội thoại rồi nhấn \"Tóm tắt AI\" để tạo một bản báo cáo tổng hợp nhanh chóng.")
        info.setWordWrap(True)
        info.setStyleSheet(f"background-color: {theme.raised}; color: {theme.dim}; padding: 12px; border-radius: 8px; font-size: 12px;")
        layout.addWidget(info)

        layout.addStretch()
        self._load_settings()

    def _toggle_show_key(self) -> None:
        if self.api_input.echoMode() == QLineEdit.Password:
            self.api_input.setEchoMode(QLineEdit.Normal)
            self.show_key_btn.setText("Ẩn")
        else:
            self.api_input.setEchoMode(QLineEdit.Password)
            self.show_key_btn.setText("Hiện")

    def _on_style_changed(self, idx: int) -> None:
        style_map = {0: "bullet", 1: "paragraph", 2: "detailed"}
        self.settings.update(summary={'style': style_map.get(idx, "bullet")})

    def _on_auto_timeout_changed(self, idx: int) -> None:
        timeout_map = {0: 5, 1: 10, 2: 15, 3: 30, 4: 0}
        self.settings.update(summary={'auto_new_session_minutes': timeout_map.get(idx, 10)})

    def _on_cleanup_changed(self, idx: int) -> None:
        cleanup_map = {0: 7, 1: 14, 2: 30, 3: 0}
        self.settings.update(summary={'auto_cleanup_days': cleanup_map.get(idx, 30)})

    def _load_settings(self) -> None:
        s = self.settings.data.summary
        self.api_input.setText(s.api_key)

        style_inv = {"bullet": 0, "paragraph": 1, "detailed": 2}
        self.style_cb.setCurrentIndex(style_inv.get(s.style, 0))

        timeout_inv = {5: 0, 10: 1, 15: 2, 30: 3, 0: 4}
        self.auto_cb.setCurrentIndex(timeout_inv.get(s.auto_new_session_minutes, 1))

        cleanup_inv = {7: 0, 14: 1, 30: 2, 0: 3}
        self.cleanup_cb.setCurrentIndex(cleanup_inv.get(s.auto_cleanup_days, 2))


class Sidebar(QWidget):
    tabChanged = Signal(int)

    TABS = [
        ("Hiển thị", 0),
        ("Mô hình AI", 1),
        ("Thuật ngữ", 2),
        ("Thuyết minh", 3),
        ("Tóm tắt AI", 4),
    ]

    def __init__(self, theme: ThemeColors):
        super().__init__()
        self.theme = theme
        self.setObjectName("SettingsSidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(184)
        # Scoped: the bare "background-color: …" used to paint a box behind
        # every label in the sidebar (e.g. the "Cài đặt hệ thống" title).
        self.setStyleSheet(f"""
            QWidget#SettingsSidebar {{
                background-color: {theme.bg};
                border-right: 1px solid {theme.border};
                border-bottom-left-radius: 16px;
            }}
            QWidget#SettingsSidebar QLabel {{ background: transparent; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 22, 14, 22)
        layout.setSpacing(4)

        title = QLabel("Cài đặt")
        title.setStyleSheet(f"color: {theme.text}; font-size: 15px; font-weight: 700; padding: 0 6px 10px 6px;")
        layout.addWidget(title)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        for label, idx in self.TABS:
            btn = ElasticButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFont(font_ui(600))
            btn.setStyleSheet(f"""
                QPushButton {{
                    text-align: left;
                    padding: 8px 12px;
                    border-radius: 9px;
                    color: {theme.dim};
                    background: transparent;
                    font-size: 12.5px;
                    border: 1.5px solid transparent;
                }}
                QPushButton:hover {{
                    background: {theme.raised};
                    color: {theme.text};
                }}
                QPushButton:checked {{
                    background: {theme.pill_bg};
                    color: {theme.pill_text};
                    border: 1.5px solid transparent;
                    font-weight: 700;
                }}
            """)
            self.btn_group.addButton(btn, idx)
            layout.addWidget(btn)
            if idx == 0:
                btn.setChecked(True)
            
        self.btn_group.buttonClicked.connect(self._on_tab_click)
        
        layout.addStretch()
        
        self.close_btn = ElasticButton("Đóng")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                border: none;
                background: transparent;
                color: {theme.dim};
                font-size: 13px;
            }}
            QPushButton:hover {{ color: {theme.text}; }}
        """)
        layout.addWidget(self.close_btn)
        
    def _on_tab_click(self, btn):
        self.tabChanged.emit(self.btn_group.id(btn))

    def set_checked(self, idx: int) -> None:
        btn = self.btn_group.button(idx)
        if btn is not None:
            btn.setChecked(True)


class SettingsPanel(QWidget):
    def __init__(self, settings: AppSettings, parent=None, bridge=None):
        super().__init__(parent)
        self.settings = settings
        self.bridge = bridge
        self.theme = get_theme(settings.data.ui.theme if settings else "dark")

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = Sidebar(self.theme)
        self.sidebar.close_btn.hide()
        self.sidebar.tabChanged.connect(self._set_tab)

        self.content_area = QWidget()
        self.content_area.setObjectName("SettingsContent")
        self.content_area.setAttribute(Qt.WA_StyledBackground, True)
        # Scoped: unscoped, this background was inherited by every label and
        # drew dark boxes behind texts inside the (lighter) model cards.
        self.content_area.setStyleSheet(
            f"QWidget#SettingsContent {{ background-color: {self.theme.surface}; "
            f"border-bottom-right-radius: 16px; }}"
        )
        content_layout = QVBoxLayout(self.content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.stack.addWidget(make_scrollable_tab(DisplayTab(self.theme, self.settings, bridge=self.bridge), self.theme))
        self.stack.addWidget(make_scrollable_tab(ModelTab(self.theme, self.settings), self.theme))
        self.stack.addWidget(make_scrollable_tab(GlossaryTab(self.theme, self.settings), self.theme))
        self.stack.addWidget(make_scrollable_tab(DubTab(self.theme, self.settings), self.theme))
        self.stack.addWidget(make_scrollable_tab(SummaryTab(self.theme, self.settings), self.theme))

        content_layout.addWidget(self.stack, 1)

        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.content_area, 1)
        # Theme switches are handled by MainWindow rebuilding this panel.

    def _set_tab(self, idx):
        self.stack.setCurrentIndex(idx)

    def set_tab(self, idx: int) -> None:
        """Switch page and keep the sidebar highlight in sync."""
        if 0 <= idx < self.stack.count():
            self.stack.setCurrentIndex(idx)
            self.sidebar.set_checked(idx)

    def current_tab(self) -> int:
        return self.stack.currentIndex()


class SettingsWindow(QWidget):
    def __init__(self, settings: AppSettings):
        super().__init__()
        from pathlib import Path
        icon_path = Path(__file__).parent.parent / "rtt_icon.ico"
        if icon_path.exists():
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(560, 420)
        self.resize(680, 560)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        self.panel = SettingsPanel(settings, self)
        main_layout.addWidget(self.panel)
        
        self._drag_pos = None

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _set_tab(self, idx):
        self.stack.setCurrentIndex(idx)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 14, 14)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor(self.theme.surface))


def main():
    app = QApplication(sys.argv)
    settings = AppSettings()
    
    # Use Segoe UI as fallback if Be Vietnam Pro is not installed for this test script
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    win = SettingsWindow(settings)
    
    # Center on screen
    screen = app.primaryScreen().geometry()
    win.move(screen.center() - win.rect().center())
    
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
