import sys
import os
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QStackedWidget, QSlider, QCheckBox, 
    QComboBox, QScrollArea, QLineEdit, QButtonGroup, 
    QGraphicsDropShadowEffect, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, Property, QRect, QPoint, QSize, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont, QLinearGradient

try:
    from rtt.theme import get_theme, ThemeColors, DARK, font_ui as _font_ui_str, font_mono as _font_mono_str
    from rtt.settings import AppSettings

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
        self.setFixedSize(36, 20)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        
        if self.isChecked():
            painter.fillPath(path, QColor(self.theme.teal))
            thumb_rect = QRectF(self.width() - 18, 2, 16, 16)
        else:
            painter.fillPath(path, QColor(self.theme.raised))
            thumb_rect = QRectF(2, 2, 16, 16)
            
        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(thumb_rect, 8, 8)
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
        
        self.slider = QSlider(Qt.Horizontal)
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
        
        self.opacity_slider = SliderWidget("Độ mờ nền", 0, 100, theme, unit="%")
        self.opacity_slider.valueChanged.connect(lambda v: self.settings.update(display={'bg_opacity': v/100.0}))
        layout.addWidget(self.opacity_slider)
        
        # Segments
        pos_layout = QHBoxLayout()
        pos_lbl = QLabel("Vị trí")
        pos_lbl.setStyleSheet(f"color: {theme.dim}; font-size: 12.5px;")
        self.pos_seg = SegmentControl(["Đáy", "Giữa", "Đỉnh"], theme)
        self.pos_seg.valueChanged.connect(lambda v: self.settings.update(display={'position': v}))
        pos_layout.addWidget(pos_lbl)
        pos_layout.addStretch()
        pos_layout.addWidget(self.pos_seg)
        layout.addLayout(pos_layout)
        
        screen_layout = QHBoxLayout()
        screen_lbl = QLabel("Màn hình")
        screen_lbl.setStyleSheet(f"color: {theme.dim}; font-size: 12.5px;")
        self.screen_seg = SegmentControl(["1", "2", "theo chuột"], theme)
        self.screen_seg.valueChanged.connect(lambda v: self.settings.update(display={'screen': v}))
        screen_layout.addWidget(screen_lbl)
        screen_layout.addStretch()
        screen_layout.addWidget(self.screen_seg)
        layout.addLayout(screen_layout)
        
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
        
    def _load_settings(self):
        d = self.settings.data
        self.font_slider.setValue(d.display.font_size)
        self.opacity_slider.setValue(int(d.display.bg_opacity * 100))
        self.pos_seg.setValue(d.display.position)
        self.screen_seg.setValue(d.display.screen)
        self.orig_tog.setChecked(d.display.show_original)
        self.font_tog.setChecked(d.ui.use_custom_fonts)

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


class ModelCard(QFrame):
    clicked = Signal(str)
    def __init__(self, title, vram, wer, lat, prog, rec, theme: ThemeColors):
        super().__init__()
        self.title_str = title
        self.theme = theme
        self.is_active = False
        
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
        layout.setSpacing(16)
        
        title = QLabel("Chọn model trên máy bạn")
        title.setStyleSheet(f"color: {theme.text}; font-size: 16px; font-weight: 600;")
        sub = QLabel("Chọn model phù hợp với cấu hình máy.")
        sub.setStyleSheet(f"color: {theme.dim}; font-size: 12.5px;")
        layout.addWidget(title)
        layout.addWidget(sub)
        
        self.cards = []
        models_data = [
            ("faster-whisper large-v3", "4.8 GB", "4.1%", "1.24", 62, "ĐỀ XUẤT"),
            ("faster-whisper small", "1.1 GB", "9.8%", "0.58", 29, "máy yếu"),
            ("faster-whisper medium", "2.8 GB", "6.2%", "0.85", 45, "")
        ]
        
        for name, vram, wer, lat, prog, rec in models_data:
            c = ModelCard(name, vram, wer, lat, prog, rec, theme)
            c.clicked.connect(self._on_model_select)
            layout.addWidget(c)
            self.cards.append(c)
            
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {theme.border};")
        layout.addWidget(sep)
        
        mt_lbl = QLabel("KHÂU DỊCH")
        mt_lbl.setFont(font_mono(600))
        mt_lbl.setStyleSheet(f"color: {theme.dim}; font-size: 9.5px;")
        layout.addWidget(mt_lbl)
        
        # MT Cards
        mt_layout = QHBoxLayout()
        c1 = QFrame()
        c1.setStyleSheet(f"background-color: {theme.raised}; border-radius: 10px; border: 2px solid {theme.teal};")
        c1_l = QVBoxLayout(c1)
        c1_title = QLabel("NLLB-200")
        c1_title.setStyleSheet(f"color: {theme.text}; font-size: 13px; font-weight: 500;")
        c1_sub = QLabel("+0.32s")
        c1_sub.setFont(font_mono())
        c1_sub.setStyleSheet(f"color: {theme.teal}; font-size: 11px;")
        c1_l.addWidget(c1_title)
        c1_l.addWidget(c1_sub)
        
        c2 = QFrame()
        c2.setStyleSheet(f"background-color: {theme.raised}; border-radius: 10px;")
        c2_l = QVBoxLayout(c2)
        c2_title = QLabel("LLM (sắp có)")
        c2_title.setStyleSheet(f"color: {theme.dim}; font-size: 13px; font-weight: 500;")
        c2_sub = QLabel("chưa hỗ trợ")
        c2_sub.setFont(font_mono())
        c2_sub.setStyleSheet(f"color: {theme.dim}; font-size: 11px;")
        c2_l.addWidget(c2_title)
        c2_l.addWidget(c2_sub)
        
        mt_layout.addWidget(c1)
        mt_layout.addWidget(c2)
        layout.addLayout(mt_layout)
        
        summary = QLabel("Tổng ước tính: 1.56s — đủ mượt cho phụ đề.")
        summary.setStyleSheet(f"background-color: {theme.raised}; color: {theme.text}; padding: 12px; border-radius: 10px; font-size: 13px;")
        layout.addWidget(summary)
        
        layout.addStretch()
        self._load_settings()
        
    def _on_model_select(self, name):
        self.settings.update(model={'stt_model': name})
        self._load_settings()
        
    def _load_settings(self):
        curr = self.settings.data.model.stt_model
        for c in self.cards:
            c.set_active(c.title_str == curr)


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
        add_btn = QPushButton("+ Thêm từ")
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
        
        imp_btn = QPushButton("Nhập từ .csv")
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
        self.voice_cb.setStyleSheet(f"""
            QComboBox {{
                background-color: {theme.raised};
                border-radius: 6px;
                color: {theme.text};
                padding: 6px 12px;
                border: 1px solid {theme.border};
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
        
        tabs = ["Hiển thị", "Model", "Thuật ngữ", "DUB / Cabin"]
        for i, t in enumerate(tabs):
            btn = QPushButton(t)
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
        
        self.close_btn = QPushButton("Đóng")
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


class SettingsWindow(QWidget):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.settings = settings
        self.theme = get_theme(settings.data.ui.theme)
        
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(680, 560)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.sidebar = Sidebar(self.theme)
        self.sidebar.close_btn.clicked.connect(self.close)
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
        
        content_layout.addWidget(self.stack)
        
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.content_area)
        
        self._drag_pos = None

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
