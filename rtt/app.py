"""Real-Time Translate — main app.

Wires the whole pipeline together:

    loopback audio -> StreamingTranscriber -> NLLB translation -> overlay / dub / transcript

UI components:
  - SubtitleOverlay  : translucent click-through subtitle bar (rtt/overlay.py)
  - MainWindow       : single unified 820x620px control window with top nav tabs (rtt/main_window.py)
                       combining HUD, Transcript History, and Settings.
  - System Tray      : tray menu adhering to design spec (rtt/app.py)

Threads:
  - capture thread : reads WASAPI loopback, feeds transcriber
  - stt thread     : VAD + whisper (owned by StreamingTranscriber)
  - mt thread      : translates committed sentences from a queue
  - Qt main thread : overlay window + MainWindow + system tray

Run:  uv run python -m rtt.app --src en --tgt vi
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import sys
import threading
import time
from typing import Any

import numpy as np

from rtt.audio import LoopbackCapture, MonoResampler16k
from rtt.settings import AppSettings
from rtt.stt import SttConfig, StreamingTranscriber, create_transcriber
from rtt.theme import apply_theme, get_theme, load_custom_fonts

DEBUG = os.environ.get("RTT_DEBUG") == "1"

# English disfluencies ("uh", "um", "uhm", "erm", "hmm", "ah") as whole words,
# with a trailing comma/space. Kept narrow on purpose: no "like"/"you know".
_FILLER_RE = re.compile(r"(?i)(?<![\w'])(?:u+h+m*|u+m+|e+r+m+|h+m+|a+h+)(?![\w'])[,.]?\s*")


def strip_fillers(text: str) -> str:
    out = _FILLER_RE.sub("", text)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,")
    return out[:1].upper() + out[1:] if out and text[:1].isupper() else out


class Pipeline:
    def __init__(
        self,
        args,
        bridge,
        settings: AppSettings | None = None,
        session: Any = None,
    ) -> None:
        self.args = args
        self.bridge = bridge
        self.settings = settings
        self.session_mgr = None
        self.session = None

        from rtt.history import SessionManager, TranscriptSession
        if isinstance(session, SessionManager):
            self.session_mgr = session
            self.session = self.session_mgr.active_session
            self.session_mgr.session_switched.connect(self._on_session_switched)
            self.session_mgr.paused_changed.connect(self._on_pause_toggled)
        elif isinstance(session, TranscriptSession):
            self.session = session
            self.session.paused_changed.connect(self._on_pause_toggled)

        self._stop = threading.Event()
        self._mt_queue: "queue.Queue[str]" = queue.Queue()
        self._threads: list[threading.Thread] = []
        self.translator = None  # loaded in the mt thread (slow import/download)
        self.dub = None  # DubPlayer when --dub / settings.dub.enabled is on

        # Latest partial waiting for a live translation (1-slot, newest wins).
        self._live_lock = threading.Lock()
        self._live_text: str | None = None

        # Determine effective parameters from CLI or settings
        model_name = args.model
        src_lang = args.src
        tgt_lang = args.tgt
        device = args.device
        self._speed_mode = False

        if settings is not None:
            self._speed_mode = settings.data.model.speed_mode
            if settings.data.model.stt_model:
                model_name = settings.data.model.stt_model
            if src_lang == "en" and settings.data.ui.src_lang != "en":
                src_lang = settings.data.ui.src_lang
            if tgt_lang == "vi" and settings.data.ui.tgt_lang != "vi":
                tgt_lang = settings.data.ui.tgt_lang

        if model_name.startswith("faster-whisper "):
            model_name = model_name[len("faster-whisper "):].strip()
        if not model_name or model_name == "auto":
            model_name = "large-v3-turbo"

        # ⚡ Speed mode: override STT config for minimum latency
        if self._speed_mode:
            stt_cfg = SttConfig.speed_preset(
                language=None if src_lang == "auto" else src_lang,
                device=device,
            )
        else:
            stt_cfg = SttConfig(
                model_name=model_name,
                language=None if src_lang == "auto" else src_lang,
                device=device,
            )

        # The STT model is loaded in start() (background thread, after the
        # translator) — loading it here froze the UI thread for seconds.
        self._stt_cfg = stt_cfg
        self.stt = None

        self._dub_loading = False
        # Configured voice that failed to load — don't retry it on every
        # unrelated settings change (slider ticks…), only when it changes.
        self._dub_failed_voice: str | None = None

        if settings is not None:
            settings.changed.connect(self._sync_dub_settings)

    def _create_dub(self) -> None:
        """Load the Piper voice + start the dub player (slow: call off the UI thread)."""
        if self.dub is not None or self._dub_loading:
            return
        self._dub_loading = True
        try:
            from rtt.dub import DEFAULT_VOICE, DEFAULT_VOICE_DIR, DubPlayer, PiperSpeaker

            dub_cfg = self.settings.data.dub if self.settings else None
            configured = (dub_cfg.voice if dub_cfg else "") or DEFAULT_VOICE
            voice = configured
            if not (DEFAULT_VOICE_DIR / f"{voice}.onnx").exists():
                voice = DEFAULT_VOICE
            self._dub_failed_voice = configured  # cleared below on success
            self.bridge.status_changed.emit("Đang tải giọng thuyết minh…")
            player = DubPlayer(
                speaker=PiperSpeaker(voice=voice),
                duck_level=dub_cfg.ducking if dub_cfg else 0.18,
                max_speed=dub_cfg.max_speed if dub_cfg else 1.45,
            )
            player.start()
            self.dub = player
            self._dub_failed_voice = None
            print(f"[app] dub voice ready: {voice}")
        except FileNotFoundError:
            print("[app] dub disabled: Piper voice not downloaded")
            self.bridge.status_changed.emit(
                "Chưa có giọng thuyết minh — tải bằng: python -m piper.download_voices"
            )
        except Exception as exc:  # noqa: BLE001 - dub is optional, never kill MT
            print(f"[app] dub initialization failed: {exc}")
            self.bridge.status_changed.emit("Không khởi động được thuyết minh")
        finally:
            self._dub_loading = False

    def _echo_gate_active(self) -> bool:
        """True while our own dub voice is audible and must not be captured."""
        dub = self.dub
        if dub is None or not dub.enabled or not dub.active.is_set():
            return False
        return self.settings is None or self.settings.data.dub.block_self_echo

    def _sync_dub_settings(self) -> None:
        if not self.settings:
            return

        # Live sync STT language preference
        src = self.settings.data.ui.src_lang
        if self.stt and hasattr(self.stt, "cfg"):
            self.stt.cfg.language = None if src == "auto" else src

        dub_cfg = self.settings.data.dub
        is_enabled = dub_cfg.enabled or self.args.dub

        if is_enabled:
            if self.dub is None:
                from rtt.dub import DEFAULT_VOICE

                if self._dub_loading or self._dub_failed_voice == (dub_cfg.voice or DEFAULT_VOICE):
                    return
                # Loading Piper takes seconds — never block the UI thread.
                threading.Thread(target=self._create_dub, daemon=True, name="dub-init").start()
            else:
                self.dub.enabled = True
                self.dub.ducker.duck_level = dub_cfg.ducking
                self.dub.max_speed = dub_cfg.max_speed
        else:
            if self.dub is not None:
                self.dub.enabled = False
                self.dub.ducker.restore()

    def _src_lang(self) -> str:
        """Effective source language (Whisper's detection in auto mode)."""
        src = self.args.src
        if self.settings and src == "en" and self.settings.data.ui.src_lang:
            src = self.settings.data.ui.src_lang
        if src == "auto":
            return getattr(self.stt, "detected_language", None) or "en"
        return src or "en"

    def _tgt_lang(self) -> str:
        tgt = self.args.tgt
        if self.settings and self.settings.data.ui.tgt_lang:
            tgt = self.settings.data.ui.tgt_lang
        return tgt or "vi"

    # ------------------------------------------------------------ callbacks

    def _on_partial(self, text: str) -> None:
        if self.session and self.session.is_paused:
            self.bridge.partial_changed.emit("")
            return

        self.bridge.partial_changed.emit(("… " + text) if text else "")
        # ⚡ Speed mode: skip live translation to avoid GPU contention
        # (commits arrive fast enough with aggressive timing)
        if self._speed_mode:
            return
        # Queue the newest partial for live translation
        tgt = self._tgt_lang()
        src = self._src_lang()
        if (
            text
            and len(text.split()) >= 4
            and tgt != src
            and not self.args.no_live
        ):
            with self._live_lock:
                self._live_text = text

    def _on_session_switched(self, new_sess) -> None:
        self.session = new_sess
        if self.translator and hasattr(self.translator, "context"):
            self.translator.context.set_topic(new_sess.session_name if new_sess else "")

    def _on_pause_toggled(self, is_paused: bool) -> None:
        self.bridge.paused_changed.emit(is_paused)
        if is_paused:
            # Immediately clear overlay subtitle display
            self.bridge.partial_changed.emit("")
            self.bridge.committed_changed.emit("")
            with self._live_lock:
                self._live_text = None
            # Drain translation queue
            while not self._mt_queue.empty():
                try:
                    self._mt_queue.get_nowait()
                except Exception:
                    break
        else:
            # Resumed: drop audio buffered before the pause so stale speech
            # isn't transcribed (the old code cleared a non-existent attribute).
            reset = getattr(self.stt, "reset", None)
            if callable(reset):
                reset()

    def _on_commit(self, text: str, _latency: float) -> None:
        # Check auto inactivity session split
        if self.session_mgr and self.settings:
            auto_min = getattr(self.settings.data.summary, "auto_new_session_minutes", 10)
            self.session_mgr.check_inactivity(auto_min)

        # Skip recording and processing if session is paused
        if self.session and self.session.is_paused:
            return

        # Strip duplicate headers from safety margins
        prev = getattr(self, "_last_commit_text", None)
        first_dot = text.find(". ")
        if prev and 0 <= first_dot < len(text) - 2:
            head = text[: first_dot + 1].strip(" .…").lower()
            if head and head in prev.lower():
                text = text[first_dot + 2:].strip()

        if not text or text == prev:
            return
        self._last_commit_text = text

        tgt = self._tgt_lang()
        src = self._src_lang()
        if src == "en" and self.settings is not None and self.settings.data.glossary.strip_fillers:
            text = strip_fillers(text)
            if not text:
                return
        if tgt and tgt != src:
            # ⚡ Speed mode: drop old items if NLLB can't keep up with fast speech
            if self._speed_mode and self._mt_queue.qsize() > 3:
                dropped = 0
                while self._mt_queue.qsize() > 1:
                    try:
                        self._mt_queue.get_nowait()
                        dropped += 1
                    except queue.Empty:
                        break
                if dropped:
                    print(f"[mt] [speed] dropped {dropped} stale item(s) — fast speech overflow")
            self._mt_queue.put(text)
        else:
            self.bridge.committed_changed.emit(text)
            if self.session is not None:
                self.session.add_entry("", text)

    def _glossary_kwargs(self) -> dict:
        g = self.settings.data.glossary if self.settings else None
        return {
            "glossary": list(g.entries) if g else [],
            "auto_lock_caps": g.auto_lock_caps if g else True,
            "auto_lock_camel": g.auto_lock_camel if g else True,
        }

    # -------------------------------------------------------------- threads

    def _capture_loop(self) -> None:
        try:
            cap = LoopbackCapture()
            res = MonoResampler16k(cap.rate, cap.channels)
            cap.start()
        except Exception as exc:  # noqa: BLE001
            print(f"[capture] cannot open system audio: {exc}")
            self.bridge.status_changed.emit(
                "Không bắt được âm thanh hệ thống — kiểm tra thiết bị phát (loa/tai nghe)"
            )
            return
        # Keep muting a short tail after the dub voice stops (device latency).
        gate_tail_until = 0.0

        from rtt.stt import RATE as STT_RATE

        chunk_s = cap.chunk_frames / cap.rate
        pushed = 0
        t_start = time.monotonic()
        try:
            while not self._stop.is_set():
                # If paused, drop audio capture and idle lightly without STT
                if self.session and self.session.is_paused:
                    _ = cap.read_available()
                    t_start = time.monotonic()
                    pushed = 0
                    time.sleep(chunk_s)
                    continue

                chunk = res.process(cap.read_available())
                if chunk.size == 0:
                    time.sleep(chunk_s / 2)

                # Feedback gate: the loopback hears our own dub voice too.
                # Replace it with silence (keeps the timeline continuous) so
                # it is never transcribed and re-translated in a loop.
                now = time.monotonic()
                if self._echo_gate_active():
                    gate_tail_until = now + 0.35
                if chunk.size and now < gate_tail_until:
                    chunk = np.zeros_like(chunk)

                if chunk.size:
                    self.stt.push(chunk)
                    pushed += chunk.size

                expected = int((time.monotonic() - t_start) * STT_RATE)
                deficit = expected - pushed
                if deficit >= STT_RATE // 10:
                    self.stt.push(np.zeros(deficit, dtype=np.float32))
                    pushed += deficit
        finally:
            cap.close()

    def _mt_loop(self) -> None:
        from rtt.translate import (
            ContextMemory,
            GeminiTranslator,
            NLLB_1B3_REPO,
            NLLB_REPO,
            NllbTranslator,
            OllamaTranslator,
        )

        mt_engine = self.settings.data.model.mt_engine if self.settings else "gemini-flash"
        # ⚡ Speed mode: always use 600M (smaller, faster)
        if self._speed_mode:
            repo = NLLB_REPO
        else:
            repo = NLLB_REPO if mt_engine == "nllb" else NLLB_1B3_REPO

        self.bridge.status_changed.emit("Đang tải mô hình dịch…")
        try:
            if not self._speed_mode and mt_engine in ("gemini-flash", "llm-hybrid"):
                api_key = self.settings.data.summary.api_key if self.settings else ""
                model = self.settings.data.summary.model if self.settings else "gemini-2.0-flash"
                fallback = NllbTranslator(model_repo=NLLB_1B3_REPO)
                self.translator = GeminiTranslator(
                    api_key=api_key,
                    model=model,
                    fallback_translator=fallback,
                    context_memory=ContextMemory(max_items=5),
                    on_status=self.bridge.status_changed.emit,
                )
            elif not self._speed_mode and mt_engine in ("llama-3b", "llama", "llama3.2", "llama-3.2", "llama3.2:3b"):
                fallback = NllbTranslator(model_repo=NLLB_1B3_REPO)
                self.translator = OllamaTranslator(
                    model="llama3.2:3b",
                    fallback_translator=fallback,
                    context_memory=ContextMemory(max_items=5),
                    on_status=self.bridge.status_changed.emit,
                )
            elif not self._speed_mode and mt_engine in ("qwen", "qwen-3b", "ollama"):
                fallback = NllbTranslator(model_repo=NLLB_1B3_REPO)
                self.translator = OllamaTranslator(
                    model="qwen2.5:3b",
                    fallback_translator=fallback,
                    context_memory=ContextMemory(max_items=5),
                    on_status=self.bridge.status_changed.emit,
                )
            elif not self._speed_mode and mt_engine == "qwen-7b":
                fallback = NllbTranslator(model_repo=NLLB_1B3_REPO)
                self.translator = OllamaTranslator(
                    model="qwen2.5:7b",
                    fallback_translator=fallback,
                    context_memory=ContextMemory(max_items=5),
                    on_status=self.bridge.status_changed.emit,
                )
            else:
                self.translator = NllbTranslator(model_repo=repo)
            
            if self.translator and hasattr(self.translator, "context") and self.session:
                self.translator.context.set_topic(self.session.session_name or "")
        except Exception as exc:  # noqa: BLE001
            print(f"[mt] FAILED to load translator, passing text through: {exc}")
            self.translator = None
            self.bridge.status_changed.emit("")
            self._mt_ready.set()
            while not self._stop.is_set():
                try:
                    self.bridge.committed_changed.emit(self._mt_queue.get(timeout=0.3))
                except queue.Empty:
                    continue
            return

        is_dub = self.args.dub or (self.settings and self.settings.data.dub.enabled)
        if is_dub:
            # A missing Piper voice used to raise here and kill the MT thread,
            # leaving the app silently translating nothing.
            self._create_dub()

        # "Ready" is announced by start() once the speech model is loaded too.
        self._mt_ready.set()
        # ⚡ Speed mode: faster poll, no live translation overhead
        poll_timeout = 0.05 if self._speed_mode else 0.15
        commit_beam = 1 if self._speed_mode else 4
        while not self._stop.is_set():
            src = self._src_lang()
            tgt = self._tgt_lang()
            try:
                text = self._mt_queue.get(timeout=poll_timeout)
            except queue.Empty:
                # ⚡ Speed mode: no live partial translation
                if self._speed_mode:
                    continue
                with self._live_lock:
                    live, self._live_text = self._live_text, None
                if live:
                    try:
                        t0 = time.perf_counter()
                        preview = getattr(self.translator, "translate_preview", None)
                        if callable(preview):
                            out = preview(live, src, tgt, **self._glossary_kwargs())
                        else:
                            out = self.translator.translate(
                                live, src, tgt, beam=1, **self._glossary_kwargs()
                            )
                        if DEBUG:
                            print(f"[dbg] mt live {len(live)} chars in "
                                  f"{time.perf_counter()-t0:.2f}s", flush=True)
                        if out:
                            self.bridge.committed_changed.emit(out + " …")
                    except Exception as exc:  # noqa: BLE001
                        print(f"[mt] live error: {exc}")
                continue
            try:
                t0 = time.perf_counter()
                if self._speed_mode:
                    # ⚡ Consumer-side drain: skip to newest if backlogged
                    while not self._mt_queue.empty():
                        try:
                            text = self._mt_queue.get_nowait()
                        except queue.Empty:
                            break
                    # ⚡ Skip term locker, call raw NLLB translate (beam=1 greedy)
                    out = self.translator._nllb_translate(text, src, tgt, beam=commit_beam)
                else:
                    out = self.translator.translate(
                        text, src, tgt, beam=commit_beam, **self._glossary_kwargs()
                    )
                if DEBUG:
                    print(f"[dbg] mt commit {len(text)} chars in "
                          f"{time.perf_counter()-t0:.2f}s", flush=True)
            except Exception as exc:  # noqa: BLE001
                out = text
                print(f"[mt] error: {exc}")
            self.bridge.committed_changed.emit(out)
            if self.session is not None:
                self.session.add_entry(text, out)
            if self.dub is not None:
                self.dub.speak(out)

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self._mt_ready = threading.Event()
        mt = threading.Thread(target=self._mt_loop, daemon=True, name="mt")
        mt.start()
        self._threads.append(mt)
        self._mt_ready.wait(timeout=120)
        if self._stop.is_set():
            return

        self.bridge.status_changed.emit("Đang tải mô hình nhận dạng giọng nói…")
        try:
            self.stt = create_transcriber(
                self._stt_cfg,
                on_partial=self._on_partial,
                on_commit=self._on_commit,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[stt] FAILED to load speech model: {exc}")
            self.bridge.status_changed.emit("Không tải được mô hình nhận dạng giọng nói")
            return
        self.bridge.status_changed.emit(
            "Chế độ tốc độ cao đã sẵn sàng" if self._speed_mode else "Sẵn sàng — đang nghe âm thanh hệ thống"
        )
        clear = threading.Timer(3.0, self.bridge.status_changed.emit, args=("",))
        clear.daemon = True
        clear.start()
        self.stt.start()
        cap = threading.Thread(target=self._capture_loop, daemon=True, name="capture")
        cap.start()
        self._threads.append(cap)

    def stop(self) -> None:
        self._stop.set()
        if self.stt is not None:
            self.stt.stop()
        if self.dub is not None:
            self.dub.stop()  # also restores ducked app volumes
        if self.settings is not None:
            self.settings.flush()
        if self.session is not None:
            self.session.save()


# ──────────────────────────────────── Tray Menu (Design 4a) ─────────

def _toggle_window(win) -> None:
    """Show + raise the control window, or hide it if it is already in front."""
    if win.isVisible() and not win.isMinimized() and win.isActiveWindow():
        win.hide()
        return
    if win.isMinimized():
        win.showNormal()
    win.show()
    win.raise_()
    win.activateWindow()


def _make_tray(app, overlay, main_win, pipeline, settings: AppSettings):
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QMenu, QSystemTrayIcon

    icon = app.windowIcon()
    if icon.isNull():
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setBrush(QColor("#10B981"))
        painter.setPen(QColor("#ffffff"))
        painter.drawRoundedRect(4, 16, 56, 32, 8, 8)
        painter.drawText(pixmap.rect(), 0x84, "VI")  # AlignCenter
        painter.end()
        icon = QIcon(pixmap)

    tray = QSystemTrayIcon(icon)
    menu = QMenu()

    # Exactly 2 menu items as requested
    ctrl_act = menu.addAction("Cửa sổ điều khiển")
    ctrl_act.triggered.connect(lambda: _toggle_window(main_win))

    quit_action = menu.addAction("Thoát")
    def do_quit() -> None:
        pipeline.stop()
        tray.hide()
        app.quit()

    quit_action.triggered.connect(do_quit)
    tray.setContextMenu(menu)
    tray.setToolTip("Real-Time Translator — Ctrl+Alt+E: mở/ẩn · Ctrl+Alt+P: tạm dừng")

    # Left-click / double-click on the tray icon opens the window (it did nothing).
    def on_activated(reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            _toggle_window(main_win)

    tray.activated.connect(on_activated)

    def update_tray() -> None:
        t_colors = get_theme(settings.data.ui.theme)
        apply_theme(menu, t_colors, settings.data.ui.use_custom_fonts)

    settings.appearance_changed.connect(update_tray)
    update_tray()

    tray.show()
    return tray


def _resolve_model(name: str) -> str:
    """'auto' -> the best locally-available Whisper model."""
    if name != "auto":
        return name
    try:
        from huggingface_hub import snapshot_download

        snapshot_download("Systran/faster-whisper-large-v3", local_files_only=True)
        return "large-v3"
    except Exception:
        return "small"


def _takeover_single_instance() -> None:
    """Kill any older rtt.app instance so relaunching 'just works'."""
    import tempfile
    import psutil
    from pathlib import Path

    pid_file = Path(tempfile.gettempdir()) / "rtt_app.pid"
    me = psutil.Process()
    family = {me.pid}
    try:
        for p in me.parents():
            family.add(p.pid)
        for p in me.children(recursive=True):
            family.add(p.pid)
    except Exception:
        pass

    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text("utf-8").strip())
            if old_pid not in family and psutil.pid_exists(old_pid):
                proc = psutil.Process(old_pid)
                # PIDs get reused: only kill it if it really is an rtt.app
                # process, never some unrelated Python program.
                try:
                    cmdline = " ".join(proc.cmdline()).lower()
                except Exception:
                    cmdline = ""
                if (
                    proc.is_running()
                    and proc.name().lower() in ("python.exe", "pythonw.exe")
                    and "rtt.app" in cmdline
                ):
                    print(f"[app] taking over from old instance pid={old_pid}")
                    proc.kill()
                    time.sleep(1.5)
        except Exception as exc:
            print(f"[app] takeover note: {exc}")

    try:
        pid_file.write_text(str(me.pid), encoding="utf-8")
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Real-Time Translate")
    parser.add_argument("--model", default="auto",
                        help="faster-whisper model id, or 'auto' (best available)")
    parser.add_argument("--src", default="en",
                        help="source language (en, ja, ko, ...) or 'auto' to detect")
    parser.add_argument("--tgt", default="vi", help="target language (vi, en, ...)")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--console", action="store_true", help="print instead of overlay")
    parser.add_argument("--dub", action="store_true",
                        help="cabin mode: speak the translation over the original audio")
    parser.add_argument("--no-live", action="store_true",
                        help="disable live translation of in-progress sentences")
    args = parser.parse_args()
    args.model = _resolve_model(args.model)
    print(f"[app] whisper model: {args.model}")
    _takeover_single_instance()

    # Load settings
    settings = AppSettings()

    # Create SessionManager & retention cleanup (excluding pinned sessions)
    from rtt.history import SessionManager
    src_code = settings.data.ui.src_lang if settings.data.ui.src_lang != "auto" else args.src
    tgt_code = settings.data.ui.tgt_lang or args.tgt
    session_mgr = SessionManager(src_lang=src_code, tgt_lang=tgt_code)

    cleanup_days = getattr(settings.data.summary, "auto_cleanup_days", 30)
    cleaned = session_mgr.cleanup_old_sessions(cleanup_days)
    if cleaned > 0:
        print(f"[app] cleaned up {cleaned} unpinned transcript session(s) older than {cleanup_days} days")

    session = session_mgr.active_session

    if args.console:
        t0 = time.time()

        class _Sig:
            def __init__(self, tag):
                self.tag = tag

            def emit(self, text):
                if text:
                    sys.stdout.write(f"[{time.time() - t0:7.2f}s] {self.tag} {text}\n")
                    sys.stdout.flush()

        class _Bridge:
            partial_changed = _Sig("PARTIAL")
            committed_changed = _Sig("COMMIT ")
            status_changed = _Sig("STATUS ")
            paused_changed = _Sig("PAUSED ")

        pipeline = Pipeline(args, _Bridge(), settings=settings, session=session)
        pipeline.start()
        print("Console mode — Ctrl+C to stop.")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pipeline.stop()
        return

    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QApplication

    from rtt.main_window import MainWindow
    from rtt.overlay import OverlayBridge, SubtitleOverlay

    if sys.platform == "win32":
        try:
            import ctypes
            app_id = "HaiHoang.RealTimeTranslator.1.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    from pathlib import Path
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QImage, QPixmap

    icon_path = Path(__file__).parent.parent / "rtt_icon.ico"
    if icon_path.exists():
        src_img = QImage(str(icon_path))
        if not src_img.isNull():
            app_icon = QIcon()
            for s in (16, 24, 32, 48, 64, 128, 256):
                scaled = src_img.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                app_icon.addPixmap(QPixmap.fromImage(scaled))
            app.setWindowIcon(app_icon)
        else:
            app.setWindowIcon(QIcon(str(icon_path)))

    # Load custom fonts after QApplication is initialized
    font_ok = load_custom_fonts()
    print(f"[app] custom fonts loaded: {font_ok}")

    bridge = OverlayBridge()
    if session_mgr:
        bridge.pause_requested.connect(session_mgr.toggle_pause)
    overlay = SubtitleOverlay(bridge, settings=settings, session=session_mgr)
    overlay.show()

    # Create single unified MainWindow containing HUD, Transcript, and Settings tabs
    main_window = MainWindow(settings=settings, session=session_mgr, bridge=bridge)
    main_window.show()

    # System-wide hotkeys (work even while a video player has focus).
    from rtt.hotkeys import MOD_ALT, MOD_CONTROL, GlobalHotkeys

    hotkeys = GlobalHotkeys()
    hotkeys.register(MOD_CONTROL | MOD_ALT, "E", lambda: _toggle_window(main_window))
    hotkeys.register(MOD_CONTROL | MOD_ALT, "P", session_mgr.toggle_pause)
    hotkeys.register(MOD_CONTROL | MOD_ALT, "S", overlay.toggle_move_mode)
    # Fallback when RegisterHotKey is unavailable: works while our window has focus.
    shortcut_main = QShortcut(QKeySequence("Ctrl+Alt+E"), main_window)
    shortcut_main.activated.connect(lambda: _toggle_window(main_window))

    # Pipeline
    pipeline = Pipeline(args, bridge, settings=settings, session=session_mgr)
    bridge.status_changed.emit("Đang tải mô hình…")
    threading.Thread(target=pipeline.start, daemon=True, name="boot").start()

    tray = _make_tray(app, overlay, main_window, pipeline, settings)  # noqa: F841

    def on_quit() -> None:
        hotkeys.unregister_all()
        settings.flush()
        if session_mgr.active_session is not None:
            session_mgr.active_session.save()

    app.aboutToQuit.connect(on_quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
