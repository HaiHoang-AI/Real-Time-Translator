"""Application settings — load, save, change-notify.

Stores user preferences in ``%APPDATA%/rtt/settings.json`` (Windows) so
they persist across sessions.  ``AppSettings`` is a QObject that emits
``changed`` whenever any field is modified, letting UI and pipeline
components react in real time.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal


def _settings_dir() -> Path:
    """Per-user config directory (``%APPDATA%/rtt`` on Windows)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    d = base / "rtt"
    d.mkdir(parents=True, exist_ok=True)
    return d


_SETTINGS_FILE = _settings_dir() / "settings.json"


# ──────────────────────────────────── data model ───────────────────

@dataclass
class DisplaySettings:
    """Overlay appearance."""
    font_size: int = 25             # px, translated subtitle
    bg_opacity: float = 0.78        # 0–1
    position: str = "bottom"        # bottom | center | top
    screen: str = "primary"         # primary | 1 | 2 | follow_mouse
    show_original: bool = True      # show source text above translation
    alignment: str = "center"       # left | center | right
    overlay_width: int = 680        # px, subtitle overlay card length (400 - 1000)


@dataclass
class ModelSettings:
    """STT + MT engine selection."""
    stt_model: str = "large-v3-turbo"   # large-v3-turbo | small | large-v3 | auto
    mt_engine: str = "nllb-1.3b"        # nllb-1.3b | nllb | llm-hybrid
    device: str = "auto"               # auto | cuda | cpu


@dataclass
class DubSettings:
    """TTS / cabin mode."""
    enabled: bool = False
    voice: str = "vi_VN-vais1000-medium"
    ducking: float = 0.18           # 0–1, how much to lower other apps
    max_speed: float = 1.45         # TTS speed ceiling


@dataclass
class GlossaryEntry:
    source: str
    target: str


@dataclass
class GlossarySettings:
    """User glossary for forced translations."""
    entries: list[dict] = field(default_factory=lambda: [
        {"source": "ear-voice span", "target": "giữ nguyên"},
        {"source": "ducking", "target": "hạ tiếng gốc"},
        {"source": "Whisper", "target": "giữ nguyên"},
    ])
    strip_fillers: bool = True      # remove "uhm", "you know" etc.
    auto_lock_caps: bool = True     # auto-protect ALL_CAPS tokens (GPU, API…)
    auto_lock_camel: bool = True    # auto-protect CamelCase proper nouns (OpenAI…)


@dataclass
class UiPrefs:
    """Miscellaneous UI preferences."""
    theme: str = "dark"             # dark | light | auto
    use_custom_fonts: bool = True   # bundled fonts vs system defaults
    src_lang: str = "en"
    tgt_lang: str = "vi"


@dataclass
class SummarySettings:
    """AI Summary & Session Management settings."""
    api_key: str = ""                         # Gemini API key
    model: str = "gemini-2.0-flash"          # gemini-2.0-flash | gemini-1.5-flash | gemini-1.5-pro
    style: str = "bullet"                     # bullet | paragraph | detailed
    auto_cleanup_days: int = 30               # auto delete sessions older than X days (0 = disabled)
    auto_new_session_minutes: int = 10        # auto create new session after X min silence (0 = disabled)


@dataclass
class SettingsData:
    """Root container for all settings."""
    display: DisplaySettings = field(default_factory=DisplaySettings)
    model: ModelSettings = field(default_factory=ModelSettings)
    dub: DubSettings = field(default_factory=DubSettings)
    glossary: GlossarySettings = field(default_factory=GlossarySettings)
    ui: UiPrefs = field(default_factory=UiPrefs)
    summary: SummarySettings = field(default_factory=SummarySettings)


# ──────────────────────────────────── AppSettings ──────────────────

class AppSettings(QObject):
    """Singleton-like settings manager with change notification.

    Read a field:   ``settings.data.display.font_size``
    Write a field:  ``settings.update(display={"font_size": 30})``
                    — this saves to disk and emits ``changed``.
    """

    changed = Signal()              # emitted after any update + save

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.data = SettingsData()
        self._load()

    # ─────────────────────────────────── persistence ───────────────

    def _load(self) -> None:
        if not _SETTINGS_FILE.exists():
            return
        try:
            raw = json.loads(_SETTINGS_FILE.read_text("utf-8"))
            self._apply_dict(raw)
        except Exception as exc:
            print(f"[settings] failed to load {_SETTINGS_FILE}: {exc}")

    def save(self) -> None:
        try:
            _SETTINGS_FILE.write_text(
                json.dumps(asdict(self.data), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[settings] failed to save: {exc}")

    # ─────────────────────────────────── update API ────────────────

    def update(self, **section_patches: dict[str, Any]) -> None:
        """Patch one or more sections and emit ``changed``.

        Example::

            settings.update(display={"font_size": 30, "position": "top"})
            settings.update(ui={"theme": "light"})
        """
        for section_name, patch in section_patches.items():
            section = getattr(self.data, section_name, None)
            if section is None:
                continue
            for key, value in patch.items():
                if hasattr(section, key):
                    setattr(section, key, value)
        self.save()
        self.changed.emit()

    def set_glossary_entries(self, entries: list[dict]) -> None:
        """Replace the entire glossary list."""
        self.data.glossary.entries = entries
        self.save()
        self.changed.emit()

    def add_glossary_entry(self, source: str, target: str) -> None:
        self.data.glossary.entries.append({"source": source, "target": target})
        self.save()
        self.changed.emit()

    def remove_glossary_entry(self, index: int) -> None:
        if 0 <= index < len(self.data.glossary.entries):
            self.data.glossary.entries.pop(index)
            self.save()
            self.changed.emit()

    # ─────────────────────────────────── helpers ───────────────────

    def _apply_dict(self, raw: dict) -> None:
        """Merge a raw JSON dict into the current data, ignoring unknowns."""
        for section_name, section_dict in raw.items():
            section = getattr(self.data, section_name, None)
            if section is None or not isinstance(section_dict, dict):
                continue
            for key, value in section_dict.items():
                if hasattr(section, key):
                    setattr(section, key, value)

    def reset(self) -> None:
        """Restore factory defaults."""
        self.data = SettingsData()
        self.save()
        self.changed.emit()


# ──────────────────────────────────── standalone test ──────────────

if __name__ == "__main__":
    s = AppSettings()
    print(f"Settings file: {_SETTINGS_FILE}")
    print(f"Theme: {s.data.ui.theme}")
    print(f"Font size: {s.data.display.font_size}")
    print(f"Custom fonts: {s.data.ui.use_custom_fonts}")
    print(f"Glossary: {len(s.data.glossary.entries)} entries")
    s.update(display={"font_size": 28})
    print(f"Font size after update: {s.data.display.font_size}")
    print("OK")
