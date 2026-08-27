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
    """All color tokens for one theme variant in Playful Claymorphism style."""
    name: str

    bg: str
    surface: str
    raised: str
    text: str
    dim: str
    border: str          # subtle border color
    border_strong: str   # distinct border

    accent: str          # vibrant emerald green
    accent_text: str     # text on accent bg
    teal: str            # source-language color

    error: str           # red-ish
    warning: str         # amber / orange

    glass_opacity: float  # 0–1, overlay backdrop
    glass_blur: int       # px

    # Playful Clean extensions
    border_chunky: str = "rgba(0,0,0,0.08)"
    cta_bg: str = "#10B981"
    cta_hover: str = "#059669"
    cta_text: str = "#FFFFFF"
    pill_bg: str = "rgba(16, 185, 129, 0.15)"
    pill_border: str = "rgba(16, 185, 129, 0.35)"
    pill_text: str = "#059669"
    accent_blue: str = "#0284C7"
    accent_amber: str = "#D97706"
    accent_purple: str = "#9333EA"


DARK = ThemeColors(
    name="dark",
    bg="#121316",
    surface="#1C1E26",
    raised="#252834",
    text="#F8FAFC",
    dim="#94A3B8",
    border="rgba(255,255,255,0.08)",
    border_strong="rgba(255,255,255,0.15)",
    border_chunky="rgba(255,255,255,0.08)",
    accent="#10B981",
    accent_text="#FFFFFF",
    teal="#2DD4BF",
    cta_bg="#10B981",
    cta_hover="#059669",
    cta_text="#FFFFFF",
    pill_bg="rgba(16, 185, 129, 0.18)",
    pill_border="rgba(16, 185, 129, 0.40)",
    pill_text="#34D399",
    accent_blue="#38BDF8",
    accent_amber="#FBBF24",
    accent_purple="#C084FC",
    error="#F87171",
    warning="#FBBF24",
    glass_opacity=0.82,
    glass_blur=22,
)

LIGHT = ThemeColors(
    name="light",
    bg="#FAF8F5",
    surface="#FFFFFF",
    raised="#F3EFE8",
    text="#18181B",
    dim="#64748B",
    border="rgba(0, 0, 0, 0.08)",
    border_strong="rgba(0, 0, 0, 0.12)",
    border_chunky="rgba(0, 0, 0, 0.08)",
    accent="#10B981",
    accent_text="#FFFFFF",
    teal="#0D9488",
    cta_bg="#10B981",
    cta_hover="#059669",
    cta_text="#FFFFFF",
    pill_bg="#DCFCE7",
    pill_border="#86EFAC",
    pill_text="#15803D",
    accent_blue="#0284C7",
    accent_amber="#D97706",
    accent_purple="#9333EA",
    error="#EF4444",
    warning="#F59E0B",
    glass_opacity=0.92,
    glass_blur=22,
)

THEMES: dict[str, ThemeColors] = {"dark": DARK, "light": LIGHT}


def get_theme(name: str) -> ThemeColors:
    """Get a theme by name. 'auto' defaults to dark."""
    return THEMES.get(name, DARK)


# ──────────────────────────────────────── QSS generation ───────────

def generate_stylesheet(theme: ThemeColors, use_custom_fonts: bool = True) -> str:
    """Generate a full QSS stylesheet string for the given theme in Playful Claymorphism style."""
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

QWidget#CentralContainer {{
    background-color: {theme.surface};
    border: none;
    border-radius: 18px;
}}

/* ── Labels ──────────────────────────────────────── */
QLabel {{
    background: transparent;
    border: none;
    padding: 0;
}}

QLabel[class="heading"] {{
    font-size: 17px;
    font-weight: 700;
    color: {theme.text};
}}

QLabel[class="subheading"] {{
    font-size: 14px;
    font-weight: 600;
    color: {theme.text};
}}

QLabel[class="dim"] {{
    font-size: 12px;
    color: {theme.dim};
}}

QLabel[class="mono"] {{
    font-family: '{mono}', 'Consolas', monospace;
    font-size: 11px;
    letter-spacing: 0.04em;
    color: {theme.dim};
}}

QLabel[class="mono-accent"] {{
    font-family: '{mono}', 'Consolas', monospace;
    font-size: 11px;
    font-weight: 600;
    color: {theme.accent};
}}

QLabel[class="mono-teal"] {{
    font-family: '{mono}', 'Consolas', monospace;
    font-size: 11px;
    font-weight: 600;
    color: {theme.teal};
}}

QLabel[class="section-title"] {{
    font-family: '{ui}', 'Segoe UI', sans-serif;
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 700;
    color: {theme.dim};
}}

/* ── Buttons (Playful Clean Style) ───────────────── */
QPushButton {{
    background-color: {theme.raised};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 10px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: {'#EAE5DD' if theme.name == 'light' else '#2E3242'};
    border-color: {theme.border_strong};
}}

QPushButton:pressed {{
    background-color: {theme.accent};
    color: {theme.accent_text};
    border: none;
}}

/* Primary & CTA Buttons (Vibrant Emerald) */
QPushButton[class="primary"],
QPushButton[class="btn-cta"] {{
    background-color: {theme.cta_bg};
    color: {theme.cta_text};
    border: none;
    border-radius: 12px;
    font-weight: 700;
    font-size: 13.5px;
    padding: 9px 18px;
}}

QPushButton[class="primary"]:hover,
QPushButton[class="btn-cta"]:hover {{
    background-color: {theme.cta_hover};
    border: none;
}}

QPushButton[class="ghost"] {{
    background: transparent;
    border: 1px solid {theme.border};
    border-radius: 10px;
    color: {theme.dim};
    font-weight: 600;
}}

QPushButton[class="ghost"]:hover {{
    background-color: {theme.raised};
    border-color: {theme.border_strong};
    color: {theme.text};
}}

/* ── Segment Control (segmented toggle) ──────────── */
QWidget[class="segment-bg"] {{
    background-color: {theme.raised};
    border: 1px solid {theme.border};
    border-radius: 12px;
}}

QPushButton[class="seg-active"] {{
    background-color: {theme.accent};
    color: {theme.accent_text};
    border: none;
    border-radius: 9px;
    font-weight: 700;
    padding: 8px 0;
}}

QPushButton[class="seg-inactive"] {{
    background: transparent;
    color: {theme.dim};
    border: none;
    border-radius: 9px;
    font-weight: 600;
    padding: 8px 0;
}}

QPushButton[class="seg-inactive"]:hover {{
    color: {theme.text};
    background-color: {'rgba(0,0,0,0.04)' if theme.name == 'light' else 'rgba(255,255,255,0.06)'};
}}

/* ── Sliders ─────────────────────────────────────── */
QSlider::groove:horizontal {{
    height: 7px;
    background: {'#E2DDD4' if theme.name == 'light' else '#2C303E'};
    border: 1px solid {theme.border};
    border-radius: 4px;
}}

QSlider::handle:horizontal {{
    background: {theme.accent};
    border: 2px solid {theme.surface};
    width: 18px;
    height: 18px;
    margin: -7px 0;
    border-radius: 9px;
}}

QSlider::handle:horizontal:hover {{
    background: {theme.cta_hover};
}}

QSlider::sub-page:horizontal {{
    background: {theme.accent};
    border-radius: 4px;
}}

/* ── Toggle Switch (styled checkbox) ─────────────── */
QCheckBox {{
    spacing: 10px;
    font-size: 13px;
    font-weight: 500;
    color: {theme.text};
}}

QCheckBox::indicator {{
    width: 42px;
    height: 23px;
    border-radius: 12px;
    border: 1.5px solid {theme.border};
}}

QCheckBox::indicator:unchecked {{
    background-color: {'#DDD7CD' if theme.name == 'light' else '#2C303E'};
}}

QCheckBox::indicator:checked {{
    background-color: {theme.accent};
    border-color: {theme.accent};
}}

/* ── Scroll area ─────────────────────────────────── */
QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollBar:vertical {{
    width: 7px;
    background: transparent;
    margin: 4px 0;
}}

QScrollBar::handle:vertical {{
    background: {theme.dim};
    border-radius: 3px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {theme.accent};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    height: 0;
}}

/* ── Input fields ────────────────────────────────── */
QLineEdit {{
    background-color: {theme.surface};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 10px;
    padding: 9px 13px;
    font-size: 13px;
    selection-background-color: {theme.accent};
}}

QLineEdit:focus {{
    border: 1.5px solid {theme.accent};
    background-color: {theme.surface};
}}

/* ── Combo box ───────────────────────────────────── */
QComboBox {{
    background-color: {theme.raised};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 10px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 500;
    min-height: 22px;
}}

QComboBox:hover {{
    border-color: {theme.border_strong};
}}

QComboBox::drop-down {{
    border: none;
    width: 26px;
}}

QComboBox QAbstractItemView {{
    background-color: {theme.surface};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 10px;
    selection-background-color: {theme.raised};
    selection-color: {theme.accent};
    outline: 0;
    padding: 6px;
}}

/* ── Card containers (Clean Soft Cards) ─────────── */
QFrame[class="card"],
QFrame[class="clay-card"] {{
    background-color: {theme.surface};
    border: 1px solid {theme.border};
    border-radius: 14px;
}}

QFrame[class="card-active"] {{
    background-color: {theme.surface};
    border: 1.5px solid {theme.accent};
    border-radius: 14px;
}}

QFrame[class="card-surface"],
QFrame[class="clay-hero"] {{
    background-color: {theme.raised};
    border: 1px solid {theme.border};
    border-radius: 16px;
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
    border-radius: 10px;
    text-align: left;
    padding: 10px 14px;
    font-weight: 600;
}}

QPushButton[class="tab-inactive"] {{
    background: transparent;
    color: {theme.dim};
    border: none;
    border-radius: 10px;
    text-align: left;
    padding: 10px 14px;
    font-weight: 500;
}}

QPushButton[class="tab-inactive"]:hover {{
    background-color: {theme.raised};
    color: {theme.text};
}}

/* ── Menu (tray) ─────────────────────────────────── */
QMenu {{
    background-color: {theme.surface};
    border: 1.5px solid {theme.border_strong};
    border-radius: 14px;
    padding: 8px;
}}

QMenu::item {{
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    color: {theme.text};
}}

QMenu::item:selected {{
    background-color: {theme.raised};
    color: {theme.accent};
}}

QMenu::item:disabled {{
    color: {theme.dim};
}}

QMenu::separator {{
    height: 1px;
    background: {theme.border};
    margin: 5px 6px;
}}
"""


def apply_theme(widget, theme: ThemeColors, use_custom_fonts: bool = True) -> None:
    """Apply a full theme stylesheet to a widget (usually the top-level window)."""
    widget.setStyleSheet(generate_stylesheet(theme, use_custom_fonts))
