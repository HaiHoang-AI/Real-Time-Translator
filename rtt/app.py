"""Real-Time Translate — main app.

Wires the whole pipeline together:

    loopback audio -> StreamingTranscriber -> NLLB translation -> overlay

Threads:
  - capture thread : reads WASAPI loopback, feeds the transcriber
  - stt thread     : VAD + whisper (owned by StreamingTranscriber)
  - mt thread      : translates committed sentences from a queue
  - Qt main thread : overlay window + system tray

Run:  uv run python -m rtt.app --src en --tgt vi
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time

import numpy as np

from rtt.audio import LoopbackCapture, MonoResampler16k
from rtt.stt import SttConfig, StreamingTranscriber


class Pipeline:
    def __init__(self, args, bridge) -> None:
        self.args = args
        self.bridge = bridge
        self._stop = threading.Event()
        self._mt_queue: "queue.Queue[str]" = queue.Queue()
        self._threads: list[threading.Thread] = []
        self.translator = None  # loaded in the mt thread (slow import/download)
        self.dub = None  # DubPlayer when --dub is on (loaded in mt thread)
        # Latest partial waiting for a live translation (1-slot, newest wins).
        self._live_lock = threading.Lock()
        self._live_text: str | None = None

        self.stt = StreamingTranscriber(
            SttConfig(
                model_name=args.model,
                language=args.src,
                device=args.device,
            ),
            on_partial=self._on_partial,
            on_commit=self._on_commit,
        )

    # ------------------------------------------------------------ callbacks

    def _on_partial(self, text: str) -> None:
        self.bridge.partial_changed.emit(("… " + text) if text else "")
        # Queue the newest partial for live translation (translated whenever
        # the MT thread has a free moment; older partials are discarded).
        if text and self.args.tgt != self.args.src and not self.args.no_live:
            with self._live_lock:
                self._live_text = text

    def _on_commit(self, text: str, _latency: float) -> None:
        if self.args.tgt and self.args.tgt != self.args.src:
            self._mt_queue.put(text)
        else:
            self.bridge.committed_changed.emit(text)

    # -------------------------------------------------------------- threads

    def _capture_loop(self) -> None:
        cap = LoopbackCapture()
        res = MonoResampler16k(cap.rate, cap.channels)
        cap.start()
        gate_tail_until = 0.0

        # WASAPI loopback starves when nothing is playing, which would freeze
        # the STT timeline and break sentence-commit. We keep our own clock:
        # whenever the device under-delivers, we feed synthetic silence so the
        # buffer keeps flowing at real-time pace.
        from rtt.stt import RATE as STT_RATE

        chunk_s = cap.chunk_frames / cap.rate
        pushed = 0  # 16 kHz samples pushed so far
        t_start = time.monotonic()
        try:
            while not self._stop.is_set():
                chunk = res.process(cap.read_available())
                if chunk.size == 0:
                    time.sleep(chunk_s / 2)

                gated = False
                if self.dub is not None:
                    if self.dub.active.is_set():
                        gate_tail_until = time.time() + 0.6
                        gated = True
                    elif time.time() < gate_tail_until:
                        gated = True

                if not gated and chunk.size:
                    self.stt.push(chunk)
                    pushed += chunk.size

                # Top up with silence if we're behind the wall clock (device
                # starving or frames dropped by the gate).
                expected = int((time.monotonic() - t_start) * STT_RATE)
                deficit = expected - pushed
                if deficit >= STT_RATE // 10:  # >100 ms behind
                    if not gated:
                        self.stt.push(np.zeros(deficit, dtype=np.float32))
                    pushed += deficit
        finally:
            cap.close()

    def _mt_loop(self) -> None:
        from rtt.translate import NllbTranslator

        self.bridge.status_changed.emit("Đang tải mô hình dịch…")
        self.translator = NllbTranslator()
        if self.args.dub:
            from rtt.dub import DubPlayer

            self.bridge.status_changed.emit("Đang tải giọng thuyết minh…")
            self.dub = DubPlayer()
            self.dub.start()
        self.bridge.status_changed.emit("")
        src = self.args.src or "en"
        while not self._stop.is_set():
            try:
                text = self._mt_queue.get(timeout=0.15)
            except queue.Empty:
                # No committed sentence pending: live-translate the newest
                # partial so the subtitle keeps moving during long sentences.
                with self._live_lock:
                    live, self._live_text = self._live_text, None
                if live:
                    try:
                        out = self.translator.translate(live, src, self.args.tgt, beam=1)
                        self.bridge.committed_changed.emit(out + " …")
                    except Exception as exc:  # noqa: BLE001
                        print(f"[mt] live error: {exc}")
                continue
            try:
                out = self.translator.translate(text, src, self.args.tgt, beam=4)
            except Exception as exc:  # noqa: BLE001 - never kill the loop
                out = text
                print(f"[mt] error: {exc}")
            self.bridge.committed_changed.emit(out)
            if self.dub is not None:
                self.dub.speak(out)

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self.stt.start()
        for target, name in ((self._capture_loop, "capture"), (self._mt_loop, "mt")):
            t = threading.Thread(target=target, daemon=True, name=name)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self.stt.stop()
        if self.dub is not None:
            self.dub.stop()


def _make_tray(app, overlay, pipeline):
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QMenu, QSystemTrayIcon

    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setBrush(QColor("#3b82f6"))
    painter.setPen(QColor("#ffffff"))
    painter.drawRoundedRect(4, 16, 56, 32, 8, 8)
    painter.drawText(pixmap.rect(), 0x84, "VI")  # AlignCenter
    painter.end()

    tray = QSystemTrayIcon(QIcon(pixmap))
    menu = QMenu()
    move_action = menu.addAction("Di chuyển phụ đề (bật/tắt)")
    move_action.triggered.connect(overlay.toggle_move_mode)
    menu.addSeparator()
    quit_action = menu.addAction("Thoát")

    def do_quit() -> None:
        pipeline.stop()
        tray.hide()
        app.quit()

    quit_action.triggered.connect(do_quit)
    tray.setContextMenu(menu)
    tray.setToolTip("Real-Time Translate")
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
    except Exception:  # noqa: BLE001 - not downloaded yet
        return "small"


def _takeover_single_instance() -> None:
    """Kill any older rtt.app instance so relaunching 'just works'."""
    import psutil  # shipped with pycaw

    # Our own process FAMILY must be excluded: on Windows the venv shim
    # python.exe spawns the real interpreter as a child with the same command
    # line, so a naive scan would kill our own parent (and us with it).
    me = psutil.Process()
    family = {me.pid}
    try:
        family.update(p.pid for p in me.parents())
        family.update(p.pid for p in me.children(recursive=True))
    except psutil.Error:
        pass

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.pid in family or proc.info["name"] not in ("python.exe", "pythonw.exe"):
                continue
            cmdline = " ".join(proc.info["cmdline"] or ())
            if "rtt.app" in cmdline:
                print(f"[app] taking over from old instance pid={proc.pid}")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def main() -> None:
    parser = argparse.ArgumentParser(description="Real-Time Translate")
    parser.add_argument("--model", default="auto",
                        help="faster-whisper model id, or 'auto' (best available)")
    parser.add_argument("--src", default="en", help="source language (en, vi, ja, ...)")
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

    if args.console:
        t0 = time.time()

        class _Sig:
            def __init__(self, tag):
                self.tag = tag

            def emit(self, text):
                if text:
                    # One single write per line: safe against thread interleaving.
                    sys.stdout.write(f"[{time.time() - t0:7.2f}s] {self.tag} {text}\n")
                    sys.stdout.flush()

        class _Bridge:
            partial_changed = _Sig("PARTIAL")
            committed_changed = _Sig("COMMIT ")
            status_changed = _Sig("STATUS ")

        pipeline = Pipeline(args, _Bridge())
        pipeline.start()
        print("Console mode — Ctrl+C to stop.")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pipeline.stop()
        return

    from PySide6.QtWidgets import QApplication

    from rtt.overlay import OverlayBridge, SubtitleOverlay

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    bridge = OverlayBridge()
    overlay = SubtitleOverlay(bridge)
    overlay.show()

    pipeline = Pipeline(args, bridge)
    bridge.status_changed.emit("Đang tải mô hình…")
    threading.Thread(target=pipeline.start, daemon=True, name="boot").start()

    tray = _make_tray(app, overlay, pipeline)  # noqa: F841 - keep alive
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
