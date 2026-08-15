"""Real-time conversation history & multi-session manager.

Handles:
- Recording and persisting live speech/translation entries.
- Creating, switching, renaming, pinning, and deleting sessions.
- Cross-session search across all past sessions and transcripts.
- Pausing/resuming translation recording per session.
- Exporting to .srt, .txt, .md formats.
- Aggregating multi-session content for AI summarization.
- Auto-retention cleanup excluding pinned sessions.
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
    session_id: str                 # timestamp string identifier (YYYYMMDD_HHMMSS)
    session_name: str = ""          # custom name or auto-generated title
    start_time_iso: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_s: float = 0.0
    total_sentences: int = 0
    src_lang: str = "en"
    tgt_lang: str = "vi"
    is_pinned: bool = False
    last_active_iso: str = field(default_factory=lambda: datetime.now().isoformat())


class TranscriptSession(QObject):
    """Session recording live sentences or representing a loaded past session."""

    entry_added = Signal(object)    # emits TranscriptEntry
    session_updated = Signal()      # emits when metadata changes
    paused_changed = Signal(bool)   # emits when pause state toggles

    def __init__(
        self,
        src_lang: str = "en",
        tgt_lang: str = "vi",
        session_id: Optional[str] = None,
        session_name: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = time.time()
        self.start_time_iso = datetime.now().isoformat()
        self.last_active_time = time.time()
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.session_name = session_name
        self.is_pinned = False
        self._is_paused = False
        self.entries: List[TranscriptEntry] = []
        self._file_path = _transcripts_dir() / f"session_{self.session_id}.json"

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def pause(self) -> None:
        if not self._is_paused:
            self._is_paused = True
            self.paused_changed.emit(True)
            self.session_updated.emit()

    def resume(self) -> None:
        if self._is_paused:
            self._is_paused = False
            self.last_active_time = time.time()
            self.paused_changed.emit(False)
            self.session_updated.emit()

    def toggle_pause(self) -> bool:
        if self._is_paused:
            self.resume()
        else:
            self.pause()
        return self._is_paused

    def rename(self, new_name: str) -> None:
        self.session_name = new_name.strip()
        self.save()
        self.session_updated.emit()

    def set_pinned(self, pinned: bool) -> None:
        self.is_pinned = pinned
        self.save()
        self.session_updated.emit()

    @property
    def display_title(self) -> str:
        if self.session_name:
            return self.session_name
        if self.entries:
            # Auto-title from first entry (prefer target, fallback to source)
            first = self.entries[0]
            text = (first.target_text or first.source_text).strip()
            if text:
                words = text.split()
                if len(words) > 8:
                    text = " ".join(words[:8]) + "…"
                elif len(text) > 40:
                    text = text[:38] + "…"
                return text
        dt = datetime.fromisoformat(self.start_time_iso)
        return f"Phiên {dt.strftime('%d/%m %H:%M')}"

    def add_entry(self, source_text: str, target_text: str, duration_s: float = 3.0) -> Optional[TranscriptEntry]:
        """Record a newly committed sentence if not paused."""
        if self._is_paused:
            return None

        self.last_active_time = time.time()
        now_s = time.time() - self.start_time
        start_s = max(0.0, now_s - duration_s)
        end_s = now_s

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
        return max(0.0, time.time() - self.start_time)

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
            session_name=self.session_name,
            start_time_iso=self.start_time_iso,
            duration_s=self.duration_s,
            total_sentences=len(self.entries),
            src_lang=self.src_lang,
            tgt_lang=self.tgt_lang,
            is_pinned=self.is_pinned,
            last_active_iso=datetime.fromtimestamp(self.last_active_time).isoformat(),
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
            print(f"[history] error saving session {self.session_id}: {exc}")

    @classmethod
    def load_from_file(cls, path_or_id: str | Path) -> Optional[TranscriptSession]:
        """Load a saved session from file or session_id."""
        if isinstance(path_or_id, Path):
            p = path_or_id
        else:
            if not str(path_or_id).endswith(".json"):
                p = _transcripts_dir() / f"session_{path_or_id}.json"
            else:
                p = Path(path_or_id)

        if not p.exists():
            return None

        try:
            raw = json.loads(p.read_text("utf-8"))
            meta = raw.get("metadata", {})
            sess = cls(
                src_lang=meta.get("src_lang", "en"),
                tgt_lang=meta.get("tgt_lang", "vi"),
                session_id=meta.get("session_id"),
                session_name=meta.get("session_name", ""),
            )
            sess.start_time_iso = meta.get("start_time_iso", sess.start_time_iso)
            sess.is_pinned = meta.get("is_pinned", False)
            try:
                sess.start_time = datetime.fromisoformat(sess.start_time_iso).timestamp()
            except Exception:
                sess.start_time = p.stat().st_ctime

            sess.entries = [
                TranscriptEntry(**e) for e in raw.get("entries", [])
            ]
            sess._file_path = p
            return sess
        except Exception as exc:
            print(f"[history] failed to load session {p}: {exc}")
            return None

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
        title = self.display_title
        lines = [
            f"# {title}",
            f"**Thời gian:** {dt} | **Cặp ngôn ngữ:** {self.src_lang.upper()} → {self.tgt_lang.upper()}",
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


class SessionManager(QObject):
    """Orchestrates multiple sessions, active switching, search, and cleanup."""

    session_switched = Signal(object)     # emits TranscriptSession
    session_list_changed = Signal()       # emits when sessions created/deleted/renamed
    paused_changed = Signal(bool)         # emits pause state of active session

    def __init__(self, src_lang: str = "en", tgt_lang: str = "vi", parent=None) -> None:
        super().__init__(parent)
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self.active_session: TranscriptSession = self.create_session()

    def set_languages(self, src: str, tgt: str) -> None:
        self.src_lang = src
        self.tgt_lang = tgt
        if self.active_session:
            self.active_session.src_lang = src
            self.active_session.tgt_lang = tgt
            self.active_session.save()

    def create_session(self, name: str = "") -> TranscriptSession:
        """Create a new session, set it as active, and save immediately."""
        if hasattr(self, "active_session") and self.active_session:
            self.active_session.save()

        sess = TranscriptSession(
            src_lang=self.src_lang,
            tgt_lang=self.tgt_lang,
            session_name=name,
            parent=self,
        )
        sess.save()
        self.active_session = sess
        sess.paused_changed.connect(self.paused_changed.emit)
        self.session_switched.emit(sess)
        self.session_list_changed.emit()
        return sess

    def switch_to(self, session_id: str) -> Optional[TranscriptSession]:
        """Switch active session to an existing session."""
        if self.active_session and self.active_session.session_id == session_id:
            return self.active_session

        if self.active_session:
            self.active_session.save()

        sess = TranscriptSession.load_from_file(session_id)
        if sess:
            sess.setParent(self)
            sess.paused_changed.connect(self.paused_changed.emit)
            self.active_session = sess
            self.session_switched.emit(sess)
            return sess
        return None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session file from disk."""
        p = _transcripts_dir() / f"session_{session_id}.json"
        deleted = False
        if p.exists():
            try:
                p.unlink()
                deleted = True
            except Exception as exc:
                print(f"[history] failed to delete {p}: {exc}")

        # If deleted active session, switch to newest or create a new one
        if self.active_session and self.active_session.session_id == session_id:
            past = self.list_sessions()
            if past:
                self.switch_to(past[0]["session_id"])
            else:
                self.create_session()

        self.session_list_changed.emit()
        return deleted

    def delete_sessions(self, session_ids: list[str]) -> int:
        count = 0
        for sid in session_ids:
            if self.delete_session(sid):
                count += 1
        return count

    def rename_session(self, session_id: str, new_name: str) -> None:
        if self.active_session and self.active_session.session_id == session_id:
            self.active_session.rename(new_name)
        else:
            sess = TranscriptSession.load_from_file(session_id)
            if sess:
                sess.rename(new_name)
        self.session_list_changed.emit()

    def pin_session(self, session_id: str, is_pinned: bool) -> None:
        if self.active_session and self.active_session.session_id == session_id:
            self.active_session.set_pinned(is_pinned)
        else:
            sess = TranscriptSession.load_from_file(session_id)
            if sess:
                sess.set_pinned(is_pinned)
        self.session_list_changed.emit()

    def list_sessions(self, search_query: str = "") -> List[dict]:
        """List all sessions ordered by pinned first, then newest start date.

        If `search_query` is given, performs cross-session search matching:
        - Session custom name / title
        - Date / time strings
        - Any sentence in source text or translated target text
        """
        sessions = []
        folder = _transcripts_dir()
        q = search_query.strip().lower()

        for p in folder.glob("session_*.json"):
            try:
                raw = json.loads(p.read_text("utf-8"))
                meta = raw.get("metadata", {})
                start_dt = datetime.fromisoformat(meta.get("start_time_iso", datetime.now().isoformat()))
                dur_m = int(meta.get("duration_s", 0) // 60)
                dur_s = int(meta.get("duration_s", 0) % 60)
                total_sentences = meta.get("total_sentences", 0)
                custom_name = meta.get("session_name", "")
                is_pinned = meta.get("is_pinned", False)
                sid = meta.get("session_id", p.stem.replace("session_", ""))

                # Auto title from entries if no custom name
                entries = raw.get("entries", [])
                if custom_name:
                    display_title = custom_name
                elif entries:
                    first = entries[0]
                    t = (first.get("target_text") or first.get("source_text") or "").strip()
                    if len(t.split()) > 7:
                        t = " ".join(t.split()[:7]) + "…"
                    elif len(t) > 38:
                        t = t[:36] + "…"
                    display_title = t or f"Phiên {start_dt.strftime('%d/%m %H:%M')}"
                else:
                    display_title = f"Phiên {start_dt.strftime('%d/%m %H:%M')}"

                # Relative date string
                now = datetime.now()
                if start_dt.date() == now.date():
                    day_group = "Hôm nay"
                elif start_dt.date() == (now - timedelta(days=1)).date():
                    day_group = "Hôm qua"
                elif (now.date() - start_dt.date()).days <= 7:
                    day_group = "7 ngày qua"
                else:
                    day_group = start_dt.strftime("%m/%Y")

                time_str = start_dt.strftime("%H:%M")
                dur_str = f"{dur_m}′{dur_s}″" if dur_m < 60 else f"{dur_m//60}h{dur_m%60}′"

                # Cross-session search matching
                if q:
                    matched = False
                    if q in display_title.lower() or q in sid.lower() or q in time_str:
                        matched = True
                    else:
                        for e in entries:
                            if q in (e.get("source_text", "").lower()) or q in (e.get("target_text", "").lower()):
                                matched = True
                                break
                    if not matched:
                        continue

                sessions.append({
                    "file_path": str(p),
                    "session_id": sid,
                    "title": display_title,
                    "custom_name": custom_name,
                    "start_dt": start_dt,
                    "day_group": day_group,
                    "time_str": time_str,
                    "duration_str": dur_str,
                    "duration_s": meta.get("duration_s", 0),
                    "sentences": total_sentences,
                    "src_lang": meta.get("src_lang", "en"),
                    "tgt_lang": meta.get("tgt_lang", "vi"),
                    "is_pinned": is_pinned,
                })
            except Exception as exc:
                print(f"[history] error reading {p.name}: {exc}")

        # Sort: Pinned first, then by datetime descending
        sessions.sort(key=lambda x: (not x["is_pinned"], datetime.now() - x["start_dt"]))
        return sessions

    def get_sessions_content(self, session_ids: list[str]) -> str:
        """Aggregate transcript contents of one or more sessions for AI summarization."""
        sections = []
        for sid in session_ids:
            sess = TranscriptSession.load_from_file(sid)
            if not sess or not sess.entries:
                continue

            dt = datetime.fromisoformat(sess.start_time_iso).strftime("%d/%m/%Y %H:%M")
            title = sess.display_title
            lines = [f"=== PHIÊN: {title} ({dt}) ==="]
            for e in sess.entries:
                if e.target_text:
                    lines.append(f"- {e.target_text}")
                elif e.source_text:
                    lines.append(f"- {e.source_text}")
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def cleanup_old_sessions(self, max_days: int = 30) -> int:
        """Delete non-pinned session files older than `max_days`."""
        if max_days <= 0:
            return 0
        cutoff = datetime.now() - timedelta(days=max_days)
        deleted = 0
        folder = _transcripts_dir()
        for p in folder.glob("session_*.json"):
            try:
                raw = json.loads(p.read_text("utf-8"))
                meta = raw.get("metadata", {})
                if meta.get("is_pinned", False):
                    continue  # Pinned sessions are never auto-deleted!
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                if mtime < cutoff:
                    p.unlink()
                    deleted += 1
            except Exception as exc:
                print(f"[history] cleanup error on {p.name}: {exc}")
        return deleted

    def check_inactivity(self, silence_minutes: int) -> bool:
        """Auto create a new session if user was silent for more than `silence_minutes`."""
        if silence_minutes <= 0 or not self.active_session or not self.active_session.entries:
            return False

        elapsed_s = time.time() - self.active_session.last_active_time
        if elapsed_s >= (silence_minutes * 60):
            print(f"[session] Inactivity detected ({elapsed_s/60:.1f}m) -> auto starting new session")
            self.create_session()
            return True
        return False


# Compatibility aliases
TranscriptManager = SessionManager
