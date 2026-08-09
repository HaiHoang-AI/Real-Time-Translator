import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame
)
from PySide6.QtCore import (
    Qt, QObject, Signal, QPoint, QTimer
)
from PySide6.QtGui import QPainter, QColor, QFont

from rtt.theme import (
    ThemeColors, DARK, LIGHT, load_custom_fonts, font_ui, font_mono,
    apply_theme, generate_stylesheet, get_theme
)
from rtt.settings import AppSettings

def _qfont_ui(pt_size: int = 10, weight: QFont.Weight = QFont.Weight.Normal, use_custom: bool = True) -> QFont:
    return QFont(font_ui(use_custom), pt_size, weight)

def _qfont_mono(pt_size: int = 10, weight: QFont.Weight = QFont.Weight.Normal, use_custom: bool = True) -> QFont:
    return QFont(font_mono(use_custom), pt_size, weight)

class HudBridge(QObject):
    mode_changed = Signal(str)
    theme_changed = Signal(str)
    open_settings = Signal()
    open_transcript = Signal()

class PulsingDot(QWidget):
    def __init__(self, color_hex="#4B9E8E", parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._color = QColor(color_hex)
        self._radius = 4.0
        self._opacity = 1.0
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(50)
        self._growing = True

    def _animate(self):
        if self._growing:
            self._radius += 0.2
            self._opacity -= 0.05
            if self._radius >= 8.0:
                self._growing = False
        else:
            self._radius = 4.0
            self._opacity = 1.0
            self._growing = True
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw pulsing halo
        halo_color = QColor(self._color)
        halo_color.setAlphaF(max(0.0, self._opacity))
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo_color)
        painter.drawEllipse(QPoint(8, 8), int(self._radius), int(self._radius))
        
        # Draw solid center
        painter.setBrush(self._color)
        painter.drawEllipse(QPoint(8, 8), 4, 4)

class SegmentedControl(QFrame):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.options = options
        self.active_idx = 0
        self.buttons = []
        self._theme = DARK

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(2)

        for i, opt in enumerate(options):
            btn = QPushButton(opt)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=i: self.set_active(idx))
            self.layout.addWidget(btn)
            self.buttons.append(btn)
            
    def update_theme(self, theme: ThemeColors):
        self._theme = theme
        self.setStyleSheet(f"""
            SegmentedControl {{
                background-color: {theme.raised};
                border: 1px solid {theme.border};
                border-radius: 10px;
            }}
            QPushButton {{
                border: none;
                padding: 8px 0px;
                border-radius: 7px;
                font-family: "{font_ui()}";
                font-size: 13px;
                color: {theme.dim};
            }}
        """)
        self._apply_active_style()

    def _apply_active_style(self):
        for i, btn in enumerate(self.buttons):
            if i == self.active_idx:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {self._theme.accent};
                        color: {self._theme.accent_text};
                        font-weight: 600;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        color: {self._theme.dim};
                        font-weight: 400;
                    }}
                """)

    def set_active(self, idx):
        if self.active_idx != idx:
            self.active_idx = idx
            self._apply_active_style()
            self.selection_changed(idx)

    def selection_changed(self, idx):
        pass

class ThemeSwitcher(SegmentedControl):
    def update_theme(self, theme: ThemeColors):
        self._theme = theme
        self.setStyleSheet(f"""
            ThemeSwitcher {{
                background-color: {theme.raised};
                border: 1px solid {theme.border};
                border-radius: 8px;
            }}
            QPushButton {{
                border: none;
                padding: 4px 9px;
                border-radius: 6px;
                font-family: "{font_ui()}";
                font-size: 11px;
                color: {theme.dim};
            }}
        """)
        self._apply_active_style()

    def _apply_active_style(self):
        for i, btn in enumerate(self.buttons):
            if i == self.active_idx:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {self._theme.surface};
                        border: 1px solid {self._theme.border};
                        color: {self._theme.text};
                        font-weight: 500;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        border: none;
                        color: {self._theme.dim};
                        font-weight: 400;
                    }}
                """)

class HudPanel(QWidget):
    def __init__(self, settings: AppSettings, bridge: QObject = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.hud_bridge = HudBridge()
        self.bridge = self.hud_bridge
        self.overlay_bridge = bridge
        self.theme = get_theme(settings.data.ui.theme if settings else "dark")

        self.drag_pos = None

        self._setup_ui()
        self._apply_theme(self.theme)
        if self.settings:
            self.settings.changed.connect(self._on_settings_changed)

    def _on_settings_changed(self):
        if self.settings:
            self.theme = get_theme(self.settings.data.ui.theme)
            self._apply_theme(self.theme)

    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("HudContainer")
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(0)
        self.main_layout.addWidget(self.container)

        # Header (Drag Area)
        self.header = QFrame()
        self.header.setFixedHeight(46)
        self.header.setObjectName("Header")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        
        self.dot = PulsingDot(self.theme.teal)
        header_layout.addWidget(self.dot)
        
        self.status_label = QLabel("Đang nghe hệ thống")
        self.status_label.setFont(_qfont_ui(10, QFont.Weight.Medium))
        header_layout.addWidget(self.status_label)
        header_layout.addStretch()

        self.container_layout.addWidget(self.header)

        # Body
        self.body = QFrame()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(16, 16, 16, 16)
        body_layout.setSpacing(16)
        self.container_layout.addWidget(self.body)

        # Language Selector
        lang_layout = QHBoxLayout()
        lang_layout.setSpacing(8)

        self.src_box = self._create_lang_box("NGUỒN", "English")
        lang_layout.addWidget(self.src_box)

        self.arrow_label = QLabel("→")
        self.arrow_label.setFont(_qfont_ui(12))
        lang_layout.addWidget(self.arrow_label)

        self.tgt_box = self._create_lang_box("ĐÍCH", "Tiếng Việt")
        lang_layout.addWidget(self.tgt_box)

        body_layout.addLayout(lang_layout)

        # Mode Toggle
        self.mode_toggle = SegmentedControl(["Phụ đề", "DUB"])
        self.mode_toggle.selection_changed = lambda idx: self.bridge.mode_changed.emit("DUB" if idx == 1 else "Phụ đề")
        body_layout.addWidget(self.mode_toggle)

        # Stats Row
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(8)

        self.lat_box = self._create_stat_box("LATENCY", "1.2s", True)
        stats_layout.addWidget(self.lat_box)

        self.gpu_box = self._create_stat_box("GPU", "RTX 4060", False)
        stats_layout.addWidget(self.gpu_box)

        body_layout.addLayout(stats_layout)

        # Footer (Theme switcher)
        footer = QFrame()
        footer.setObjectName("Footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 12, 16, 12)
        
        theme_label = QLabel("Theme")
        theme_label.setFont(_qfont_ui(9))
        self.theme_label = theme_label
        footer_layout.addWidget(theme_label)
        footer_layout.addStretch()

        self.theme_switcher = ThemeSwitcher(["Dark", "Light", "Auto"])
        self.theme_switcher.selection_changed = self._on_theme_changed
        footer_layout.addWidget(self.theme_switcher)

        self.container_layout.addWidget(footer)

    def _create_lang_box(self, label_text, lang_text):
        box = QFrame()
        box.setProperty("class", "LangBox")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)

        lbl = QLabel(label_text)
        lbl.setFont(_qfont_mono(8))
        lbl.setProperty("class", "LangLabel")

        lang = QLabel(lang_text)
        lang.setFont(_qfont_ui(11, QFont.Weight.Medium))
        lang.setProperty("class", "LangValue")

        layout.addWidget(lbl)
        layout.addWidget(lang)
        return box

    def _create_stat_box(self, label_text, val_text, is_accent):
        box = QFrame()
        box.setProperty("class", "StatBox")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)
        
        lbl = QLabel(label_text)
        lbl.setFont(_qfont_mono(8))
        lbl.setProperty("class", "StatLabel")
        
        val = QLabel(val_text)
        val.setFont(_qfont_mono(10))
        val.setProperty("class", "StatValueAccent" if is_accent else "StatValue")

        layout.addWidget(lbl)
        layout.addStretch()
        layout.addWidget(val)
        return box

    def _on_theme_changed(self, idx):
        themes = ["dark", "light", "auto"]
        t_name = themes[idx]
        self.bridge.theme_changed.emit(t_name)
        
        if t_name in ["dark", "light"]:
            self.theme = get_theme(t_name)
            self._apply_theme(self.theme)

    def _apply_theme(self, theme: ThemeColors):
        self.setStyleSheet(f"""
            #HudContainer {{
                background-color: {theme.surface};
                border-radius: 14px;
            }}
            #Header {{
                border-bottom: 1px solid {theme.border};
            }}
            QLabel {{
                color: {theme.text};
            }}
            .LangBox {{
                background-color: {theme.raised};
                border: 1px solid {theme.border};
                border-radius: 9px;
            }}
            .LangLabel {{
                color: {theme.dim};
            }}
            .LangValue {{
                color: {theme.text};
            }}
            .StatBox {{
                background-color: {theme.raised};
                border-radius: 8px;
            }}
            .StatLabel {{
                color: {theme.dim};
            }}
            .StatValue {{
                color: {theme.text};
            }}
            .StatValueAccent {{
                color: {theme.accent};
            }}
        """)
        
        self.arrow_label.setStyleSheet(f"color: {theme.accent};")
        self.theme_label.setStyleSheet(f"color: {theme.dim};")
        self.status_label.setStyleSheet(f"color: {theme.text};")

        self.mode_toggle.update_theme(theme)
        self.theme_switcher.update_theme(theme)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.header.geometry().contains(event.pos()):
                self.drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.drag_pos is not None:
            delta = event.globalPosition().toPoint() - self.drag_pos
            self.move(self.pos() + delta)
            self.drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None


class HudWindow(QWidget):
    def __init__(self, settings: AppSettings, bridge: QObject = None):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.panel = HudPanel(settings, bridge, self)
        layout.addWidget(self.panel)
        self.hud_bridge = self.panel.hud_bridge
        self.bridge = self.panel.bridge

def main():
    app = QApplication(sys.argv)
    load_custom_fonts()
    settings = AppSettings()
    
    class FakeBridge(QObject):
        mode_changed = Signal(str)
        theme_changed = Signal(str)
        open_settings = Signal()
        open_transcript = Signal()
        
    bridge = FakeBridge()
    hud = HudWindow(settings, bridge)
    hud.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
