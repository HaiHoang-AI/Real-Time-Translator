import sys
import os
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QStackedWidget, QSlider, QCheckBox, 
    QComboBox, QScrollArea, QLineEdit, QButtonGroup, 
    QGraphicsDropShadowEffect, QFrame, QSizePolicy, QSizeGrip,
    QStyledItemDelegate
)
from PySide6.QtCore import Qt, Signal, Property, QRect, QPoint, QSize, QRectF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QLinearGradient

try:
    from rtt.theme import get_theme, ThemeColors, DARK, font_ui as _font_ui_str, font_mono as _font_mono_str
    from rtt.settings import AppSettings
    from rtt.motion import ElasticButton, HoverLiftFrame, PhysicsSlider

    def font_ui(weight=400):
        f = QFont(_font_ui_str())
        if isinstance(weight, QFont.Weight):
            f.setWeight(weight)
        elif isinstance(weight, int):
            f.setWeight(QFont.Weight(min(99, max(1, weight * 10 if weight <= 9 else weight))))
        return f

    def font_mono(weight=400):
        f = QFont(_font_mono_str())
        if isinstance(weight, QFont.Weight):
            f.setWeight(weight)
        elif isinstance(weight, int):
            f.setWeight(QFont.Weight(min(99, max(1, weight * 10 if weight <= 9 else weight))))
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 11, 11)

        off_col = QColor(self.theme.raised)
        on_col = QColor(self.theme.teal)
        bg_r = off_col.red() + (on_col.red() - off_col.red()) * self._thumb_pos
        bg_g = off_col.green() + (on_col.green() - off_col.green()) * self._thumb_pos
        bg_b = off_col.blue() + (on_col.blue() - off_col.blue()) * self._thumb_pos
        bg_col = QColor(int(bg_r), int(bg_g), int(bg_b))

        painter.fillPath(path, bg_col)

        pen = QPen(QColor(self.theme.border))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)

        min_x = 3.0
        max_x = self.width() - 19.0
        thumb_x = min_x + (max_x - min_x) * self._thumb_pos
        thumb_rect = QRectF(thumb_x, 3.0, 16.0, 16.0)

        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(thumb_rect, 8, 8)
        painter.setPen(Qt.NoPen)
        painter.fillPath(thumb_path, QColor(self.theme.text))
        painter.end()


class SegmentControl(QWidget):
    valueChanged = Signal(str)
    
    def __init__(self, options, theme: ThemeColors, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.options = options
        self.setFixedHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        self.buttons = []
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)
        
        self.setStyleSheet(f"""
            SegmentControl {{
                background-color: {theme.raised};
                border-radius: 8px;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                color: {theme.dim};
                padding: 4px 12px;
            }}
            QPushButton:checked {{
                background-color: {theme.surface};
                color: {theme.text};
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
        font.setPixelSize(12)
        self.lbl.setFont(font)
        self.lbl.setStyleSheet(f"color: {theme.dim};")
        
        self.val_lbl = QLabel("0")
        val_font = font_mono(500)
        val_font.setPixelSize(12)
        self.val_lbl.setFont(val_font)
        self.val_lbl.setStyleSheet(f"color: {theme.text};")
        
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
        layout.addWidget(self.val_lbl)
        layout.addWidget(self.slider)
        
    def _on_change(self, v):
        display_val = str(v)
        if self.is_float:
            display_val = f"{v/100:.2f}"
        self.val_lbl.setText(f"{display_val}{self.unit}")
        self.valueChanged.emit(v)
        
    def setValue(self, v):
        self.slider.setValue(v)


class DisplayTab(QWidget):
    def __init__(self, theme: ThemeColors, settings: AppSettings):
        super().__init__()
        self.theme = theme
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)
        
        # Preview Box
        self.preview_box = QWidget()
        self.preview_box.setFixedHeight(120)
        preview_layout = QVBoxLayout(self.preview_box)
        preview_layout.setAlignment(Qt.AlignCenter)
        
        self.preview_card = QFrame()
        self.preview_card.setStyleSheet(f"background-color: {theme.surface}; border-radius: 8px;")
        card_layout = QVBoxLayout(self.preview_card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        
        self.src_lbl = QLabel("We call that gap the ear-voice span.")
        f_src = font_ui(400)
        f_src.setPixelSize(11)
        self.src_lbl.setFont(f_src)
        self.src_lbl.setStyleSheet(f"color: {theme.teal};")
        
        self.tgt_lbl = QLabel("Khoảng cách đó gọi là ear-voice span.")
        self.f_tgt = font_ui(500)
        self.tgt_lbl.setFont(self.f_tgt)
        self.tgt_lbl.setStyleSheet(f"color: {theme.text};")
        
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
        lang_box.setStyleSheet(f"background-color: {theme.raised}; border-radius: 10px; padding: 10px 14px;")
        lang_layout = QVBoxLayout(lang_box)
        lang_layout.setSpacing(10)

        # Input Language (Source)
        src_lang_layout = QHBoxLayout()
        src_lang_lbl = QLabel("Ngôn ngữ đầu vào (Nói)")
        src_lang_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px; font-weight: 500;")
        
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
        tgt_lang_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px; font-weight: 500;")
        
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
        
        layout.addStretch()
        self._load_settings()
        
    def _on_font_size(self, v):
        self.f_tgt.setPixelSize(v)
        self.tgt_lbl.setFont(self.f_tgt)
        self.settings.update(display={'font_size': v})

    def _on_opacity_change(self, v):
        alpha = int(255 * v / 100.0)
        self.preview_card.setStyleSheet(f"background-color: rgba(0, 0, 0, {alpha/255.0:.2f}); border-radius: 8px;")
        self.settings.update(display={'bg_opacity': v / 100.0})

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

    def paintEvent(self, event):
        super().paintEvent(event)
        # Paint diagonal stripe pattern for preview box background
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box_rect = self.preview_box.geometry()
        
        path = QPainterPath()
        path.addRoundedRect(box_rect, 11, 11)
        painter.setClipPath(path)
        
        painter.fillRect(box_rect, QColor("#11100D"))
        
        pen = QPen(QColor(self.theme.border))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        
        spacing = 15
        for i in range(-box_rect.height(), box_rect.width(), spacing):
            painter.drawLine(box_rect.x() + i, box_rect.y(), box_rect.x() + i + box_rect.height(), box_rect.bottom())
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
            ("large-v3-turbo", "faster-whisper large-v3-turbo", "1.5 GB", "4.0%", "0.40", 75, "ĐỀ XUẤT"),
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

        mt_layout = QHBoxLayout()
        mt_layout.setSpacing(10)

        self.mt_frames = {}

        mt_options = [
            ("nllb-1.3b", "NLLB-200 1.3B", "ĐỀ XUẤT (+1.5s)", "Chất lượng cao, từ chuyên ngành tốt"),
            ("nllb", "NLLB-200 600M", "Nhanh (+0.8s)", "Nhẹ, tiết kiệm VRAM"),
            ("llm-hybrid", "LLM Hybrid", "Ollama (+3.5s)", "Qwen2.5 / Gemma (Phase 2)"),
        ]

        for key, name, sub_text, desc in mt_options:
            frame = QFrame()
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
            mt_layout.addWidget(frame)
            self.mt_frames[key] = frame

        layout.addLayout(mt_layout)

        # Summary & Restart Notice
        self.summary = QLabel("Tổng ước tính: ~1.9s — chuẩn xác & mượt mà cho phụ đề.")
        self.summary.setStyleSheet(
            f"background-color: {theme.raised}; color: {theme.text}; "
            f"padding: 10px 12px; border-radius: 8px; font-size: 12.5px;"
        )
        layout.addWidget(self.summary)

        notice = QLabel("⟳ Lưu ý: Thay đổi mô hình sẽ áp dụng hoàn toàn ở lần khởi động lại ứng dụng.")
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

    def _load_settings(self):
        m_cfg = self.settings.data.model
        curr_stt = m_cfg.stt_model
        curr_mt = m_cfg.mt_engine

        # Update STT cards UI
        for key, card in self.stt_cards.items():
            is_active = (key == curr_stt) or (key == "large-v3-turbo" and curr_stt == "auto")
            card.set_active(is_active)

        # Update MT frames UI
        for key, frame in self.mt_frames.items():
            is_active = (key == curr_mt) or (key == "nllb-1.3b" and curr_mt == "auto")
            if is_active:
                frame.setStyleSheet(
                    f"background-color: {self.theme.raised}; border-radius: 10px; "
                    f"border: 2px solid {self.theme.teal};"
                )
            else:
                frame.setStyleSheet(
                    f"background-color: {self.theme.raised}; border-radius: 10px; "
                    f"border: 1px solid transparent;"
                )

        # Update summary text
        stt_time = 0.40 if curr_stt in ("large-v3-turbo", "auto") else (0.20 if curr_stt == "small" else 1.20)
        mt_time = 1.50 if curr_mt in ("nllb-1.3b", "auto") else (0.80 if curr_mt == "nllb" else 3.50)
        tot = stt_time + mt_time
        self.summary.setText(
            f"Ước tính độ trễ: ~{tot:.2f}s  (STT: {stt_time:.2f}s + MT: {mt_time:.2f}s) — Đủ mượt cho phiên dịch."
        )


class GlossaryTab(QWidget):
    def __init__(self, theme: ThemeColors, settings: AppSettings):
        super().__init__()
        self.theme = theme
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        
        desc = QLabel("Tên riêng, jargon, tên sản phẩm — ép model dịch đúng.")
        desc.setStyleSheet(f"color: {theme.dim}; font-size: 13px;")
        layout.addWidget(desc)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.list_widget)
        layout.addWidget(self.scroll)
        
        # Add buttons
        btn_layout = QHBoxLayout()
        add_btn = ElasticButton("+ Thêm từ")
        add_btn.setStyleSheet(f"""
            QPushButton {{
                border: 1px dashed {theme.dim};
                border-radius: 9px;
                color: {theme.text};
                padding: 10px;
                background: transparent;
            }}
            QPushButton:hover {{ background: {theme.raised}; }}
        """)
        
        imp_btn = ElasticButton("Nhập từ .csv")
        imp_btn.setStyleSheet(f"""
            QPushButton {{
                border: none;
                color: {theme.teal};
                background: transparent;
            }}
            QPushButton:hover {{ text-decoration: underline; }}
        """)
        
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(imp_btn)
        layout.addLayout(btn_layout)
        
        layout.addSpacing(16)
        tog_layout = QHBoxLayout()
        tog_lbl = QLabel("Bỏ từ đệm khi DUB\n\"uhm\", \"you know\"")
        tog_lbl.setStyleSheet(f"color: {theme.text}; font-size: 13px;")
        self.tog = ToggleSwitch(theme)
        self.tog.toggled.connect(lambda v: self.settings.update(glossary={'strip_fillers': v}))
        tog_layout.addWidget(tog_lbl)
        tog_layout.addStretch()
        tog_layout.addWidget(self.tog)
        layout.addLayout(tog_layout)
        
        self._load_settings()
        
    def _load_settings(self):
        self.tog.setChecked(self.settings.data.glossary.strip_fillers)


class DubTab(QWidget):
    def __init__(self, theme: ThemeColors, settings: AppSettings):
        super().__init__()
        self.theme = theme
        self.settings = settings
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
        
        # Mock load voices
        voices = [p.stem for p in Path("models/piper").glob("*.onnx")] if Path("models/piper").exists() else ["vi-VN-hoài-bảo-medium", "en-US-amy-low"]
        self.voice_cb.addItems(voices)
        self.voice_cb.currentTextChanged.connect(lambda v: self.settings.update(dub={'voice': v}))
        voice_layout.addWidget(voice_lbl)
        voice_layout.addStretch()
        voice_layout.addWidget(self.voice_cb)
        layout.addLayout(voice_layout)
        
        self.duck_slider = SliderWidget("Hạ tiếng gốc", 0, 100, theme, unit="%")
        self.duck_slider.valueChanged.connect(lambda v: self.settings.update(dub={'ducking': v/100.0}))
        layout.addWidget(self.duck_slider)
        
        self.speed_slider = SliderWidget("Tốc độ đọc tối đa", 100, 200, theme, unit="×", is_float=True)
        self.speed_slider.valueChanged.connect(lambda v: self.settings.update(dub={'max_speed': v/100.0}))
        layout.addWidget(self.speed_slider)
        
        info = QLabel("Khi bật DUB, giọng đọc sẽ trễ ~3s so với hình. Âm lượng ứng dụng khác tự động giảm.")
        info.setWordWrap(True)
        info.setStyleSheet(f"background-color: {theme.raised}; color: {theme.dim}; padding: 12px; border-radius: 8px; font-size: 12.5px;")
        layout.addWidget(info)
        
        layout.addStretch()
        self._load_settings()
        
    def _load_settings(self):
        d = self.settings.data.dub
        self.dub_tog.setChecked(d.enabled)
        self.duck_slider.setValue(int(d.ducking * 100))
        self.speed_slider.setValue(int(d.max_speed * 100))
        idx = self.voice_cb.findText(d.voice)
        if idx >= 0: self.voice_cb.setCurrentIndex(idx)


class SummaryTab(QWidget):
    """Tab 5: AI Summarization & Session Management settings."""

    def __init__(self, theme: ThemeColors, settings: AppSettings):
        super().__init__()
        self.theme = theme
        self.settings = settings
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

        link_lbl = QLabel("<a href='https://aistudio.google.com/apikey' style='color:#4B9E8E; text-decoration:none;'>Lấy API key miễn phí ↗</a>")
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
        self.api_input.textChanged.connect(lambda t: self.settings.update(summary={'api_key': t.strip()}))
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
    
    def __init__(self, theme: ThemeColors):
        super().__init__()
        self.theme = theme
        self.setFixedWidth(170)
        self.setStyleSheet(f"background-color: {theme.bg}; border-top-left-radius: 14px; border-bottom-left-radius: 14px;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 24)
        
        title = QLabel("Cài đặt")
        title.setStyleSheet(f"color: {theme.text}; font-size: 16px; font-weight: 600; margin-bottom: 12px;")
        layout.addWidget(title)
        
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)
        
        tabs = ["Hiển thị", "Model", "Thuật ngữ", "DUB / Cabin", "Tóm tắt AI"]
        for i, t in enumerate(tabs):
            btn = ElasticButton(t)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    text-align: left;
                    padding: 8px 12px;
                    border-radius: 8px;
                    color: {theme.dim};
                    background: transparent;
                    font-size: 13px;
                    border: 1px solid transparent;
                }}
                QPushButton:hover {{
                    background: {theme.raised};
                }}
                QPushButton:checked {{
                    background: {theme.raised};
                    color: {theme.text};
                    border: 1px solid {theme.border};
                    font-weight: 500;
                }}
            """)
            self.btn_group.addButton(btn, i)
            layout.addWidget(btn)
            if i == 0: btn.setChecked(True)
            
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


class SettingsPanel(QWidget):
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.theme = get_theme(settings.data.ui.theme if settings else "dark")

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = Sidebar(self.theme)
        self.sidebar.close_btn.hide()
        self.sidebar.tabChanged.connect(self._set_tab)

        self.content_area = QWidget()
        self.content_area.setStyleSheet(f"background-color: {self.theme.surface}; border-top-right-radius: 14px; border-bottom-right-radius: 14px;")
        content_layout = QVBoxLayout(self.content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.stack.addWidget(DisplayTab(self.theme, self.settings))
        self.stack.addWidget(ModelTab(self.theme, self.settings))
        self.stack.addWidget(GlossaryTab(self.theme, self.settings))
        self.stack.addWidget(DubTab(self.theme, self.settings))
        self.stack.addWidget(SummaryTab(self.theme, self.settings))

        content_layout.addWidget(self.stack, 1)

        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.content_area, 1)

        if self.settings:
            self.settings.changed.connect(self._on_settings_changed)

    def _set_tab(self, idx):
        self.stack.setCurrentIndex(idx)

    def _on_settings_changed(self):
        if self.settings:
            self.theme = get_theme(self.settings.data.ui.theme)
            apply_theme(self, self.theme)


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
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.panel = SettingsPanel(settings, self)
        main_layout.addWidget(self.panel)

        # Top Header Bar with Window Control Buttons (Minimize, Maximize, Close)
        win_control_bar = QWidget()
        win_control_bar.setFixedHeight(36)
        ctrl_layout = QHBoxLayout(win_control_bar)
        ctrl_layout.setContentsMargins(0, 4, 12, 0)
        ctrl_layout.setSpacing(6)
        ctrl_layout.addStretch(1)

        btn_min = QPushButton("─")
        btn_min.setFixedSize(28, 24)
        btn_min.setStyleSheet(f"QPushButton {{ background: transparent; color: {self.theme.accent}; border: none; border-radius: 6px; font-weight: bold; }} QPushButton:hover {{ background-color: rgba(196, 136, 90, 0.18); }}")
        btn_min.clicked.connect(self.showMinimized)
        ctrl_layout.addWidget(btn_min)

        btn_max = QPushButton("□")
        btn_max.setFixedSize(28, 24)
        btn_max.setStyleSheet(f"QPushButton {{ background: transparent; color: {self.theme.accent}; border: none; border-radius: 6px; font-weight: bold; }} QPushButton:hover {{ background-color: rgba(196, 136, 90, 0.18); }}")
        btn_max.clicked.connect(self._toggle_maximize)
        ctrl_layout.addWidget(btn_max)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 24)
        btn_close.setStyleSheet(f"QPushButton {{ background: transparent; color: {self.theme.accent}; border: none; border-radius: 6px; font-size: 13px; font-weight: bold; }} QPushButton:hover {{ background-color: rgba(196, 136, 90, 0.25); }}")
        btn_close.clicked.connect(self.close)
        ctrl_layout.addWidget(btn_close)

        content_layout.addWidget(win_control_bar)
        
        self.stack = QStackedWidget()
        self.stack.addWidget(DisplayTab(self.theme, self.settings))
        self.stack.addWidget(ModelTab(self.theme, self.settings))
        self.stack.addWidget(GlossaryTab(self.theme, self.settings))
        self.stack.addWidget(DubTab(self.theme, self.settings))
        
        content_layout.addWidget(self.stack, 1)

        # QSizeGrip at bottom-right corner for smooth resizing
        grip_layout = QHBoxLayout()
        grip_layout.setContentsMargins(0, 0, 4, 4)
        grip_layout.addStretch(1)
        grip = QSizeGrip(self)
        grip.setFixedSize(14, 14)
        grip_layout.addWidget(grip)
        content_layout.addLayout(grip_layout)
        
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.content_area, 1)
        
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
