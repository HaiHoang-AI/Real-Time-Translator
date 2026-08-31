"""Dub / "cabin interpreter" mode — speak translations over the original audio.

Pieces:

  PiperSpeaker : local Vietnamese (or any Piper voice) TTS, ~22 kHz mono.
  Ducker       : lowers every OTHER app's volume while the dub voice speaks
                 (per-session, via Windows Core Audio / pycaw), restores after.
  DubPlayer    : queue + playback worker with *dynamic pacing* — the more
                 backlog, the faster the voice speaks (like a human
                 interpreter catching up), capped so it stays natural.

Continuous capture streaming: system audio capture streams continuously without frame dropping so original speech underneath is never lost.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path

import numpy as np

DEFAULT_VOICE_DIR = Path(__file__).resolve().parent.parent / "models" / "piper"
DEFAULT_VOICE = "vi_VN-vais1000-medium"


class PiperSpeaker:
    def __init__(self, voice: str = DEFAULT_VOICE, voice_dir: Path = DEFAULT_VOICE_DIR):
        from piper import PiperVoice

        onnx = Path(voice_dir) / f"{voice}.onnx"
        if not onnx.exists():
            raise FileNotFoundError(
                f"Piper voice not found: {onnx}\n"
                f"Download with: uv run python -m piper.download_voices "
                f"--data-dir \"{voice_dir}\" {voice}"
            )
        self.voice = PiperVoice.load(onnx)
        self.sample_rate = self.voice.config.sample_rate

    def synth(self, text: str, speed: float = 1.0) -> np.ndarray:
        """Synthesize to int16 mono at self.sample_rate. speed>1 = faster."""
        from piper import SynthesisConfig

        cfg = SynthesisConfig(length_scale=1.0 / max(speed, 0.25))
        chunks = [c.audio_int16_array for c in self.voice.synthesize(text, cfg)]
        if not chunks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(chunks)


class Ducker:
    """Duck all audio sessions except our own process while dubbing."""

    def __init__(self, duck_level: float = 0.18) -> None:
        self.duck_level = duck_level
        self._saved: dict[int, tuple[object, float]] = {}
        self._lock = threading.Lock()

    def duck(self) -> None:
        with self._lock:
            if self._saved:
                return
            try:
                from pycaw.pycaw import AudioUtilities

                for session in AudioUtilities.GetAllSessions():
                    if session.Process and session.Process.pid == os.getpid():
                        continue
                    vol = session.SimpleAudioVolume
                    if vol is None:
                        continue
                    current = vol.GetMasterVolume()
                    key = session.Process.pid if session.Process else id(session)
                    self._saved[key] = (vol, current)
                    vol.SetMasterVolume(max(current * self.duck_level, 0.0), None)
            except Exception as exc:  # noqa: BLE001 - ducking is best-effort
                print(f"[duck] warning: {exc}")

    def restore(self) -> None:
        with self._lock:
            for vol, level in self._saved.values():
                try:
                    vol.SetMasterVolume(level, None)
                except Exception:  # noqa: BLE001
                    pass
            self._saved.clear()


class DubPlayer:
    """Sequential playback of dub utterances with catch-up pacing."""

    def __init__(
        self,
        speaker: PiperSpeaker | None = None,
        duck_level: float = 0.18,
        base_speed: float = 1.0,
        max_speed: float = 1.45,
    ) -> None:
        self.speaker = speaker or PiperSpeaker()
        self.ducker = Ducker(duck_level)
        self.base_speed = base_speed
        self.max_speed = max_speed

        self.enabled = True
        self.active = threading.Event()  # ducking gate: set while audible
        self.is_speaking = False         # physical playback active flag
        self._recent_spoken: list[tuple[float, str]] = []
        self._history_lock = threading.Lock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._pa = None
        self._drain_s = 0.6

    def _record_spoken(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        now = time.time()
        with self._history_lock:
            self._recent_spoken.append((now, text))
            # Keep history to last 15 items and within 30s
            self._recent_spoken = [(t, s) for t, s in self._recent_spoken if (now - t) < 30.0][-15:]

    def is_recent_echo(self, candidate: str, max_age_s: float = 15.0) -> bool:
        """Check if incoming candidate string is an echo of recently spoken DUB text."""
        if not candidate:
            return False
        import re
        cand_clean = re.sub(r'[^\w\s]', '', candidate.lower()).strip()
        if not cand_clean or len(cand_clean) < 3:
            return False
        cand_words = set(cand_clean.split())
        now = time.time()

        with self._history_lock:
            self._recent_spoken = [(t, s) for t, s in self._recent_spoken if (now - t) < max_age_s]
            for _, spoken in self._recent_spoken:
                spoken_clean = re.sub(r'[^\w\s]', '', spoken.lower()).strip()
                if not spoken_clean:
                    continue
                # Exact or Substring match
                if cand_clean in spoken_clean or spoken_clean in cand_clean:
                    return True
                # Word overlap (Jaccard / containment)
                spoken_words = set(spoken_clean.split())
                overlap = len(cand_words & spoken_words)
                min_len = min(len(cand_words), len(spoken_words))
                if min_len > 0 and (overlap / min_len) >= 0.60:
                    return True
        return False

    def speak(self, text: str) -> None:
        if not getattr(self, "enabled", True):
            return
        text = text.strip()
        if text:
            self._record_spoken(text)
            self._queue.put(text)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="dub")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.ducker.restore()

    # ---------------------------------------------------------------- worker

    def _ensure_stream(self):
        if self._stream is None:
            import pyaudiowpatch as pyaudio

            # COM must be initialized in this thread for pycaw ducking too.
            try:
                import comtypes

                comtypes.CoInitialize()
            except Exception:  # noqa: BLE001
                pass
            self._pa = pyaudio.PyAudio()
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.speaker.sample_rate,
                output=True,
            )
            try:
                latency = self._stream.get_output_latency()
            except OSError:
                latency = 0.2
            self._drain_s = max(0.4, latency + 0.2)
        return self._stream

    def _speed_for_backlog(self) -> float:
        """More queued sentences -> faster voice, like an interpreter catching up."""
        backlog = self._queue.qsize()
        return min(self.base_speed + 0.15 * backlog, self.max_speed)

    def _run(self) -> None:
        idle_since: float | None = None
        while not self._stop.is_set():
            try:
                text = self._queue.get(timeout=0.1)
            except queue.Empty:
                if (
                    self.active.is_set()
                    and idle_since
                    and time.time() - idle_since > self._drain_s
                ):
                    self.active.clear()
                    self.ducker.restore()
                continue

            try:
                stream = self._ensure_stream()
                audio = self.speaker.synth(text, speed=self._speed_for_backlog())
                if audio.size == 0:
                    continue
                if not self.active.is_set():
                    self.active.set()
                    self.ducker.duck()
                self.is_speaking = True
                try:
                    stream.write(audio.tobytes())  # blocking write = natural pacing
                finally:
                    self.is_speaking = False
                idle_since = time.time()
            except Exception as exc:  # noqa: BLE001 - keep the voice alive
                self.is_speaking = False
                print(f"[dub] error: {exc}")


# --------------------------------------------------------------------- demo

def main() -> None:
    """Speak a few Vietnamese lines with catch-up pacing; duck other audio."""
    print("Loading Piper voice ...")
    player = DubPlayer()
    print(f"Voice ready ({player.speaker.sample_rate} Hz). Speaking ...")
    player.start()

    lines = [
        "Xin chào, đây là chế độ thuyết minh của ứng dụng dịch thời gian thực.",
        "Khi hàng đợi còn nhiều câu, giọng đọc sẽ tự động nói nhanh hơn để đuổi kịp.",
        "Âm lượng của các ứng dụng khác sẽ được giảm xuống trong lúc thuyết minh.",
    ]
    for line in lines:
        player.speak(line)

    while not player._queue.empty() or player.active.is_set():
        time.sleep(0.2)
    time.sleep(0.5)
    player.stop()
    print("Done.")


if __name__ == "__main__":
    main()
