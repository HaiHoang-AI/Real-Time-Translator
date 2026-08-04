"""Real-time conversation history & transcript manager.

Handles recording of committed sentences, session persistence in JSON format,
export to .srt / .txt / .md formats, and 7-day auto-cleanup of old sessions.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal


def _transcripts_dir() -> Path:
    """Directory for storing session transcript JSON files."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    d = base / "rtt" / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class TranscriptEntry:
    """Single sentence entry in a transcript."""
    index: int                      # 1-based index
    start_time_s: float             # seconds since session start
    end_time_s: float               # seconds since session start
    time_str: str                   # formatted e.g. "41:52" or "01:23:45"
    source_text: str                # original audio transcript
    target_text: str                # translated text
    timestamp_iso: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SessionMetadata:
    """Metadata for a recorded session."""
    session_id: str                 # timestamp string identifier
    start_time_iso: str
    duration_s: float = 0.0
    total_sentences: int = 0
    src_lang: str = "en"
    tgt_lang: str = "vi"


class TranscriptSession(QObject):
    """Active session manager recording live sentences."""

    entry_added = Signal(object)    # emits TranscriptEntry
    session_updated = Signal()      # emits when metadata changes

    def __init__(self, src_lang: str = "en", tgt_lang: str = "vi", parent=None) -> None:
        super().__init__(parent)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = time.time()
        self.start_time_iso = datetime.now().isoformat()
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.entries: List[TranscriptEntry] = []
        self._file_path = _transcripts_dir() / f"session_{self.session_id}.json"

    def add_entry(self, source_text: str, target_text: str, duration_s: float = 3.0) -> TranscriptEntry:
        """Record a newly committed sentence."""
        now_s = time.time() - self.start_time
        start_s = max(0.0, now_s - duration_s)
        end_s = now_s

        # Format time_str (MM:SS or HH:MM:SS)
        mins = int(end_s // 60)
        secs = int(end_s % 60)
        hours = mins // 60
        mins = mins % 60
        if hours > 0:
            time_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
        else:
            time_str = f"{mins:02d}:{secs:02d}"

        entry = TranscriptEntry(
            index=len(self.entries) + 1,
            start_time_s=start_s,
            end_time_s=end_s,
            time_str=time_str,
            source_text=source_text.strip(),
            target_text=target_text.strip(),
        )
        self.entries.append(entry)
        self.save()
        self.entry_added.emit(entry)
        self.session_updated.emit()
        return entry

    @property
    def duration_s(self) -> float:
        return time.time() - self.start_time

    @property
    def formatted_duration(self) -> str:
        d = int(self.duration_s)
        mins = d // 60
        secs = d % 60
        return f"{mins:02d}:{secs:02d}"

    def save(self) -> None:
        """Persist session data to JSON file."""
        meta = SessionMetadata(
            session_id=self.session_id,
            start_time_iso=self.start_time_iso,
            duration_s=self.duration_s,
            total_sentences=len(self.entries),
            src_lang=self.src_lang,
            tgt_lang=self.tgt_lang,
        )
        payload = {
            "metadata": asdict(meta),
            "entries": [asdict(e) for e in self.entries],
        }
        try:
            self._file_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[history] error saving session: {exc}")

    # ──────────────────────────────────── EXPORT HELPERS ──────────────

    def export_srt(self, include_source: bool = True, include_timestamp: bool = True) -> str:
        """Format session entries as a standard SubRip (.srt) subtitle string."""
        lines = []
        for i, entry in enumerate(self.entries, 1):
            s_hrs, s_rem = divmod(entry.start_time_s, 3600)
            s_mins, s_secs = divmod(s_rem, 60)
            s_ms = int((s_secs - int(s_secs)) * 1000)

            e_hrs, e_rem = divmod(entry.end_time_s, 3600)
            e_mins, e_secs = divmod(e_rem, 60)
            e_ms = int((e_secs - int(e_secs)) * 1000)

            time_range = (
                f"{int(s_hrs):02d}:{int(s_mins):02d}:{int(s_secs):02d},{s_ms:03d} --> "
                f"{int(e_hrs):02d}:{int(e_mins):02d}:{int(e_secs):02d},{e_ms:03d}"
            )

            lines.append(str(i))
            lines.append(time_range)
            if include_source and entry.source_text:
                lines.append(entry.source_text)
            lines.append(entry.target_text)
            lines.append("")

        return "\n".join(lines)

    def export_txt(self, include_source: bool = True, include_timestamp: bool = True) -> str:
        """Format session entries as plain text."""
        lines = []
        for entry in self.entries:
            prefix = f"[{entry.time_str}] " if include_timestamp else ""
            if include_source and entry.source_text:
                lines.append(f"{prefix}{entry.source_text}")
                lines.append(f"  {entry.target_text}")
            else:
                lines.append(f"{prefix}{entry.target_text}")
            lines.append("")
        return "\n".join(lines)

    def export_md(self, include_source: bool = True, include_timestamp: bool = True) -> str:
        """Format session entries as Markdown document."""
        dt = datetime.fromisoformat(self.start_time_iso).strftime("%d/%m/%Y %H:%M")
        lines = [
            f"# Transcript — {dt}",
            f"**Cặp ngôn ngữ:** {self.src_lang.upper()} → {self.tgt_lang.upper()}  ",
            f"**Thời lượng:** {self.formatted_duration} | **Số câu:** {len(self.entries)}",
            "",
            "---",
            "",
        ]
        for entry in self.entries:
            ts = f"`{entry.time_str}` " if include_timestamp else ""
            if include_source and entry.source_text:
                lines.append(f"{ts}*{entry.source_text}*")
                lines.append(f"> {entry.target_text}")
            else:
                lines.append(f"{ts}{entry.target_text}")
            lines.append("")
        return "\n".join(lines)


class TranscriptManager:
    """Manager for loading past sessions and performing retention cleanup."""

    @staticmethod
    def list_past_sessions() -> List[dict]:
        """List past session metadata ordered from newest to oldest."""
        sessions = []
        folder = _transcripts_dir()
        for p in folder.glob("session_*.json"):
            try:
                raw = json.loads(p.read_text("utf-8"))
                meta = raw.get("metadata", {})
                start_dt = datetime.fromisoformat(meta.get("start_time_iso", datetime.now().isoformat()))
                dur_m = int(meta.get("duration_s", 0) // 60)

                # Formatted label e.g. "Hôm nay · 14:02 · 18′"
                now = datetime.now()
                if start_dt.date() == now.date():
                    day_str = "Hôm nay"
                elif start_dt.date() == (now - timedelta(days=1)).date():
                    day_str = "Hôm qua"
                else:
                    day_str = start_dt.strftime("%d/%m")

                time_str = start_dt.strftime("%H:%M")
                summary_label = f"{day_str} · {time_str} · {dur_m}′"

                sessions.append({
                    "file_path": str(p),
                    "session_id": meta.get("session_id"),
                    "start_dt": start_dt,
                    "summary_label": summary_label,
                    "sentences": meta.get("total_sentences", 0),
                    "src_lang": meta.get("src_lang", "en"),
                    "tgt_lang": meta.get("tgt_lang", "vi"),
                })
            except Exception as exc:
                print(f"[history] error reading {p.name}: {exc}")

        sessions.sort(key=lambda x: x["start_dt"], reverse=True)
        return sessions

    @staticmethod
    def cleanup_old_sessions(max_days: int = 7) -> int:
        """Delete session files older than `max_days`."""
        cutoff = datetime.now() - timedelta(days=max_days)
        deleted = 0
        folder = _transcripts_dir()
        for p in folder.glob("session_*.json"):
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                if mtime < cutoff:
                    p.unlink()
                    deleted += 1
            except Exception as exc:
                print(f"[history] cleanup error on {p.name}: {exc}")
        return deleted


# ──────────────────────────────────── standalone test ──────────────

if __name__ == "__main__":
    sess = TranscriptSession("en", "vi")
    print(f"Started session: {sess.session_id}")

    sess.add_entry("We call that gap the ear-voice span.", "Khoảng cách đó được gọi là ear-voice span.")
    sess.add_entry("It is usually two to four seconds.", "Nó thường kéo dài hai đến bốn giây.")
    sess.add_entry("The mistake is trying to push it down to zero.", "Sai lầm là cố ép nó về không.")

    sys.stdout.reconfigure(encoding="utf-8")
    print("\n--- SRT EXPORT ---")
    print(sess.export_srt())

    print("\n--- MD EXPORT ---")
    print(sess.export_md())

    past = TranscriptManager.list_past_sessions()
    print(f"\nPast sessions found: {len(past)}")
    for p in past:
        print(" ", p["summary_label"], f"({p['sentences']} câu)")
    print("OK")
