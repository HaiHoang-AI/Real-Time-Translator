"""Design-token system — Dark / Light themes and font management.

Tokens extracted from the design spec (Turn 6, section 6f):

  Dark:  bg #14110E · surface #1C1815 · raised #232019
         text #F0EBE3 · dim #A39C92
         accent oklch(0.72 0.12 48) ≈ #C4885A
         source-lang teal oklch(0.72 0.12 168) ≈ #4B9E8E

  Light: bg #F5F2EC · surface #FFFDF9 · raised #F5F2EC
         text #201C17 · dim #6B645B
         accent oklch(0.55 0.13 45) ≈ #8E5F35
         source-lang teal oklch(0.5 0.11 168) ≈ #3B7D6F

  Radius: 8 / 9 / 14 / 16
  Glass:  blur 22px, opacity .78 dark / .90 light
  Font:   Be Vietnam Pro (UI) · IBM Plex Mono (numbers / keys)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QFontDatabase

_FONTS_DIR = Path(__file__).resolve().parent / "fonts"
_fonts_loaded = False


# ──────────────────────────────────────────────── font loading ──────

def load_custom_fonts() -> bool:
    """Register bundled TTF fonts with Qt. Returns True if any loaded."""
    global _fonts_loaded
    if _fonts_loaded:
        return True
    from PySide6.QtWidgets import QApplication
    if not QApplication.instance():
        return False
    loaded = 0
    for ttf in _FONTS_DIR.glob("*.ttf"):
        fid = QFontDatabase.addApplicationFont(str(ttf))
        if fid >= 0:
            loaded += 1
    _fonts_loaded = loaded > 0
    return _fonts_loaded


def font_ui(use_custom: bool = True) -> str:
    """Return the primary UI font family name."""
    if use_custom and _fonts_loaded:
        return "Be Vietnam Pro"
    return "Segoe UI"


def font_mono(use_custom: bool = True) -> str:
    """Return the monospace font family name."""
    if use_custom and _fonts_loaded:
        return "IBM Plex Mono"
    return "Consolas"


# ──────────────────────────────────────────── color tokens ──────────

@dataclass(frozen=True)
class ThemeColors:
    """All color tokens for one theme variant."""
    name: str

    bg: str
    surface: str
    raised: str
    text: str
    dim: str
    border: str          # derived: subtle border color
    border_strong: str   # derived: more visible border

    accent: str          # warm amber / orange
    accent_text: str     # text on accent bg
    teal: str            # source-language color

    error: str           # red-ish
    warning: str         # amber / orange (same as accent in dark)

    glass_opacity: float  # 0–1, overlay backdrop
    glass_blur: int       # px


DARK = ThemeColors(
    name="dark",
    bg="#14110E",
    surface="#1C1815",
    raised="#232019",
    text="#F0EBE3",
    dim="#A39C92",
    border="rgba(255,255,255,0.09)",
    border_strong="rgba(255,255,255,0.12)",
    accent="#C4885A",
    accent_text="#14110E",
    teal="#4B9E8E",
    error="#C05A4A",
    warning="#C4885A",
    glass_opacity=0.78,
    glass_blur=22,
)

LIGHT = ThemeColors(
    name="light",
    bg="#F5F2EC",
    surface="#FFFDF9",
    raised="#F5F2EC",
    text="#201C17",
    dim="#6B645B",
    border="rgba(0,0,0,0.09)",
    border_strong="rgba(0,0,0,0.12)",
    accent="#8E5F35",
    accent_text="#FFFDF9",
    teal="#3B7D6F",
    error="#B04030",
    warning="#8E5F35",
    glass_opacity=0.90,
    glass_blur=22,
)

THEMES: dict[str, ThemeColors] = {"dark": DARK, "light": LIGHT}


def get_theme(name: str) -> ThemeColors:
    """Get a theme by name. 'auto' defaults to dark."""
    return THEMES.get(name, DARK)


# ──────────────────────────────────────── QSS generation ───────────

def generate_stylesheet(theme: ThemeColors, use_custom_fonts: bool = True) -> str:
    """Generate a full QSS stylesheet string for the given theme."""
    ui = font_ui(use_custom_fonts)
    mono = font_mono(use_custom_fonts)

    return f"""
/* ── Base ────────────────────────────────────────── */
QWidget {{
    background-color: {theme.surface};
    color: {theme.text};
    font-family: '{ui}', 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
}}

QWidget#centralPanel {{
    background-color: {theme.surface};
    border: 1px solid {theme.border};
    border-radius: 14px;
}}

/* ── Labels ──────────────────────────────────────── */
QLabel {{
    background: transparent;
    border: none;
    padding: 0;
}}

QLabel[class="heading"] {{
    font-size: 16px;
    font-weight: 600;
    color: {theme.text};
}}

QLabel[class="subheading"] {{
    font-size: 14px;
    font-weight: 500;
    color: {theme.text};
}}

QLabel[class="dim"] {{
    font-size: 12px;
    color: {theme.dim};
}}

QLabel[class="mono"] {{
    font-family: '{mono}', 'Consolas', monospace;
    font-size: 11px;
    letter-spacing: 0.08em;
    color: {theme.dim};
}}

QLabel[class="mono-accent"] {{
    font-family: '{mono}', 'Consolas', monospace;
    font-size: 11px;
    color: {theme.accent};
}}

QLabel[class="mono-teal"] {{
    font-family: '{mono}', 'Consolas', monospace;
    font-size: 11px;
    color: {theme.teal};
}}

QLabel[class="section-title"] {{
    font-family: '{mono}', 'Consolas', monospace;
    font-size: 10px;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: {theme.dim};
}}

/* ── Buttons ─────────────────────────────────────── */
QPushButton {{
    background-color: {theme.raised};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 9px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {theme.bg if theme.name == 'light' else '#2C2721'};
    border-color: {theme.border_strong};
}}

QPushButton:pressed {{
    background-color: {theme.accent};
    color: {theme.accent_text};
}}

QPushButton[class="primary"] {{
    background-color: {theme.accent};
    color: {theme.accent_text};
    border: none;
    font-weight: 600;
}}

QPushButton[class="primary"]:hover {{
    background-color: {'#A87248' if theme.name == 'dark' else '#7A5230'};
}}

QPushButton[class="ghost"] {{
    background: transparent;
    border: 1px solid {theme.border};
    color: {theme.dim};
}}

QPushButton[class="ghost"]:hover {{
    background-color: {theme.raised};
    color: {theme.text};
}}

/* ── Segment Control (segmented toggle) ──────────── */
QWidget[class="segment-bg"] {{
    background-color: {theme.raised};
    border: 1px solid {theme.border};
    border-radius: 10px;
}}

QPushButton[class="seg-active"] {{
    background-color: {theme.accent};
    color: {theme.accent_text};
    border: none;
    border-radius: 7px;
    font-weight: 600;
    padding: 8px 0;
}}

QPushButton[class="seg-inactive"] {{
    background: transparent;
    color: {theme.dim};
    border: none;
    border-radius: 7px;
    font-weight: 500;
    padding: 8px 0;
}}

QPushButton[class="seg-inactive"]:hover {{
    color: {theme.text};
}}

/* ── Sliders ─────────────────────────────────────── */
QSlider::groove:horizontal {{
    height: 5px;
    background: {'#2C2721' if theme.name == 'dark' else '#E0DDD7'};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background: {theme.accent};
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}

QSlider::sub-page:horizontal {{
    background: {theme.accent};
    border-radius: 3px;
}}

/* ── Toggle Switch (styled checkbox) ─────────────── */
QCheckBox {{
    spacing: 8px;
    font-size: 12.5px;
    color: {theme.dim};
}}

QCheckBox::indicator {{
    width: 38px;
    height: 21px;
    border-radius: 11px;
}}

QCheckBox::indicator:unchecked {{
    background-color: {'#2C2721' if theme.name == 'dark' else '#D4D1CC'};
}}

QCheckBox::indicator:checked {{
    background-color: {theme.accent};
}}

/* ── Scroll area ─────────────────────────────────── */
QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollBar:vertical {{
    width: 6px;
    background: transparent;
    margin: 4px 0;
}}

QScrollBar::handle:vertical {{
    background: {theme.dim};
    border-radius: 3px;
    min-height: 24px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    height: 0;
}}

/* ── Input fields ────────────────────────────────── */
QLineEdit {{
    background-color: {theme.raised};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 9px;
    padding: 9px 12px;
    font-size: 13px;
    selection-background-color: {theme.accent};
}}

QLineEdit:focus {{
    border-color: {theme.accent};
}}

/* ── Combo box ───────────────────────────────────── */
QComboBox {{
    background-color: {theme.raised};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 9px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 20px;
}}

QComboBox:hover {{
    border-color: {theme.border_strong};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {theme.surface};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 8px;
    selection-background-color: {theme.raised};
    selection-color: {theme.text};
    outline: 0;
    padding: 4px;
}}

/* ── Card containers ─────────────────────────────── */
QFrame[class="card"] {{
    background-color: {theme.raised};
    border: 1px solid {theme.border};
    border-radius: 10px;
}}

QFrame[class="card-active"] {{
    background-color: {theme.raised};
    border: 1px solid {'rgba(75,158,142,0.4)' if theme.name == 'dark' else 'rgba(59,125,111,0.4)'};
    border-radius: 10px;
}}

QFrame[class="card-surface"] {{
    background-color: {theme.surface};
    border: 1px solid {theme.border};
    border-radius: 14px;
}}

/* ── Separator ───────────────────────────────────── */
QFrame[class="separator"] {{
    background-color: {theme.border};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* ── Tab bar (sidebar) ───────────────────────────── */
QPushButton[class="tab-active"] {{
    background-color: {theme.raised};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 8px;
    text-align: left;
    padding: 10px 14px;
    font-weight: 500;
}}

QPushButton[class="tab-inactive"] {{
    background: transparent;
    color: {theme.dim};
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 10px 14px;
}}

QPushButton[class="tab-inactive"]:hover {{
    background-color: {theme.raised};
    color: {theme.text};
}}

/* ── Menu (tray) ─────────────────────────────────── */
QMenu {{
    background-color: {theme.surface};
    border: 1px solid {theme.border_strong};
    border-radius: 12px;
    padding: 7px;
}}

QMenu::item {{
    padding: 8px 11px;
    border-radius: 8px;
    font-size: 13px;
    color: {theme.text};
}}

QMenu::item:selected {{
    background-color: {'rgba(255,255,255,0.06)' if theme.name == 'dark' else 'rgba(0,0,0,0.05)'};
}}

QMenu::item:disabled {{
    color: {theme.dim};
}}

QMenu::separator {{
    height: 1px;
    background: {theme.border};
    margin: 4px 6px;
}}
"""


def apply_theme(widget, theme: ThemeColors, use_custom_fonts: bool = True) -> None:
    """Apply a full theme stylesheet to a widget (usually the top-level window)."""
    widget.setStyleSheet(generate_stylesheet(theme, use_custom_fonts))
