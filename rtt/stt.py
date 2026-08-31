"""Streaming speech-to-text on top of faster-whisper + Silero VAD.

Core idea (the "sentence-commit" algorithm):

  - Audio accumulates in a rolling buffer (16 kHz mono float32).
  - Every `tick_s` seconds we run VAD over the buffer (cheap, CPU-only).
  - While the speaker is still talking, we transcribe the whole buffer and
    emit it as a *partial* result (may still change).
  - Once VAD sees >= `commit_silence_s` of silence after the last speech,
    the region up to that point is *committed*: transcribed one final time,
    emitted as stable text, and removed from the buffer.
  - If the buffer grows past `max_buffer_s` without a pause, we force-commit
    at the last internal silence boundary (or the whole buffer) so latency
    stays bounded on non-stop speech.

Partials give the UI something to show within ~1 s; commits are what the
translator (and later the TTS dub) consume.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

RATE = 16000
DEBUG = os.environ.get("RTT_DEBUG") == "1"


def _dbg(msg: str) -> None:
    if DEBUG:
        print(f"[dbg {time.perf_counter():9.2f}] {msg}", flush=True)


@dataclass
class SttConfig:
    model_name: str = "small"          # any faster-whisper / CT2 model id or path
    language: Optional[str] = None     # None = autodetect ("en", "vi", ...)
    device: str = "auto"               # "auto" -> try cuda, fall back to cpu
    tick_s: float = 0.35               # how often we re-run VAD/partials
    commit_silence_s: float = 0.45     # trailing silence that finalizes a sentence
    max_buffer_s: float = 10.0         # force-commit ceiling for non-stop speech
    min_speech_s: float = 0.25         # ignore blips shorter than this
    beam_size: int = 2                 # partials use greedy; commits use this
    # Early commit on punctuation: when the running transcript already contains
    # a finished sentence (".!?…") and the speaker has moved on, commit that
    # sentence immediately instead of waiting for a silence gap. This is what
    # keeps latency low on non-stop narration (TED talks, news, ...).
    early_commit: bool = True
    early_min_words: int = 3           # don't early-commit tiny fragments
    early_continue_s: float = 0.35     # speech needed *after* the boundary
    use_context_prompt: bool = True    # feed previous transcribed sentences as initial_prompt
    custom_initial_prompt: Optional[str] = None # static prompt if set

    @classmethod
    def speed_preset(cls, language: str | None = None, device: str = "auto") -> "SttConfig":
        """Return a config tuned for minimum latency (quality tradeoff).

        Balances speed against fast-speech resilience: we still commit
        quickly, but not so aggressively that non-stop narration floods
        the MT queue with micro-fragments.
        """
        return cls(
            model_name="tiny",
            language=language,
            device=device,
            tick_s=0.25,              # check VAD every 250ms (was 350)
            commit_silence_s=0.40,    # commit after 400ms silence (was 450, not 300)
            max_buffer_s=8.0,         # batch more speech per commit on non-stop talk
            min_speech_s=0.20,
            beam_size=1,              # greedy decoding
            early_commit=True,
            early_min_words=4,        # don't early-commit tiny 2-word fragments
            early_continue_s=0.25,
        )


class StreamingTranscriber:
    """Feed audio with push(); receive on_partial/on_commit callbacks."""

    def __init__(
        self,
        config: SttConfig | None = None,
        on_partial: Callable[[str], None] | None = None,
        on_commit: Callable[[str, float], None] | None = None,
    ) -> None:
        self.cfg = config or SttConfig()
        self.on_partial = on_partial or (lambda text: None)
        # on_commit(text, latency_s): latency = time since that speech ended
        self.on_commit = on_commit or (lambda text, latency: None)

        self.model, self.device = self._load_model()
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        self._vad = get_speech_timestamps
        self._vad_opts = VadOptions(
            threshold=0.5,
            min_speech_duration_ms=int(self.cfg.min_speech_s * 1000),
            min_silence_duration_ms=250,
            speech_pad_ms=150,
        )

        self._buf = np.zeros(0, dtype=np.float32)
        self._buf_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_partial = ""
        # Language Whisper detected on the most recent pass (only meaningful
        # when cfg.language is None, i.e. autodetect mode).
        self.detected_language: Optional[str] = None
        # Rolling context history of committed sentences to condition STT
        self._context_history: list[str] = []

    def _get_initial_prompt(self) -> Optional[str]:
        """Build initial prompt from custom prompt + rolling context history."""
        prompts = []
        if self.cfg.custom_initial_prompt:
            prompts.append(self.cfg.custom_initial_prompt.strip())
        if self.cfg.use_context_prompt and self._context_history:
            # Take last 2-3 committed sentences up to ~220 characters
            recent = []
            char_count = 0
            for s in reversed(self._context_history):
                if char_count + len(s) > 220:
                    break
                recent.insert(0, s)
                char_count += len(s) + 1
            if recent:
                prompts.append(" ".join(recent))
        return " ".join(prompts) if prompts else None

    def _record_context(self, text: str) -> None:
        """Store committed sentence in rolling context history."""
        text = text.strip()
        if not text:
            return
        self._context_history.append(text)
        if len(self._context_history) > 10:
            self._context_history = self._context_history[-10:]

    # ---------------------------------------------------------------- model

    def _load_model(self):
        from rtt.cudalibs import setup_cuda_dll_dirs

        setup_cuda_dll_dirs()
        from faster_whisper import WhisperModel

        cfg = self.cfg
        raw_name = (cfg.model_name or "").strip()
        if raw_name.startswith("faster-whisper "):
            raw_name = raw_name[len("faster-whisper "):].strip()

        candidate_names = [raw_name] if raw_name and raw_name != "auto" else []
        for default_name in ("large-v3-turbo", "small"):
            if default_name not in candidate_names:
                candidate_names.append(default_name)

        last_err: Exception | None = None
        for name in candidate_names:
            attempts = []
            if cfg.device in ("auto", "cuda"):
                attempts.append(("cuda", "float16"))
            if cfg.device in ("auto", "cpu"):
                attempts.append(("cpu", "int8"))

            for device, compute in attempts:
                try:
                    model = WhisperModel(name, device=device, compute_type=compute)
                    model.transcribe(np.zeros(RATE, dtype=np.float32), beam_size=1)
                    return model, device
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    _dbg(f"Failed loading Whisper model {name!r} ({device}/{compute}): {exc}")

        raise RuntimeError(f"Could not load any Whisper model: {last_err}")

    # ------------------------------------------------------------- lifecycle

    def push(self, samples: np.ndarray) -> None:
        """Append 16 kHz mono float32 samples (called from the capture thread)."""
        if samples.size == 0:
            return
        with self._buf_lock:
            self._buf = np.concatenate([self._buf, samples])

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="stt")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def flush_buffer(self) -> None:
        """Discard all buffered audio and reset partial state.

        Called by the capture gating logic when DUB starts speaking to prevent
        any TTS-contaminated audio from being processed by Whisper.
        """
        with self._buf_lock:
            self._buf = np.zeros(0, dtype=np.float32)
        self._last_partial = ""
        self.on_partial("")

    # ----------------------------------------------------------------- loop

    def _run(self) -> None:
        while not self._stop.is_set():
            time.sleep(self.cfg.tick_s)
            try:
                self._process()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                print(f"[stt] error: {exc}")

    def _process(self) -> None:
        with self._buf_lock:
            buf = self._buf.copy()
        if buf.size < int(0.4 * RATE):
            return

        speech = self._vad(buf, self._vad_opts, sampling_rate=RATE)
        if not speech:
            # Nothing but silence: keep a short tail so we never clip an onset.
            self._trim_to(int(1.0 * RATE), buf.size)
            if self._last_partial:
                self._last_partial = ""
                self.on_partial("")
            return

        last_end = speech[-1]["end"]
        trailing_silence = (buf.size - last_end) / RATE

        if trailing_silence >= self.cfg.commit_silence_s:
            self._commit(buf[:last_end], consumed=last_end, total=buf.size)
        elif buf.size >= int(self.cfg.max_buffer_s * RATE):
            # Non-stop speech: cut at the last internal silence gap if there
            # is one, otherwise take the whole buffer.
            cut = speech[-1]["start"] if len(speech) > 1 else last_end
            cut = max(cut, int(2 * RATE))  # never commit a microscopic head
            self._commit(buf[:cut], consumed=cut, total=buf.size)
        else:
            self._partial_tick(buf, speech_start=speech[0]["start"])

    def _partial_tick(self, buf: np.ndarray, speech_start: int) -> None:
        """Emit a partial; early-commit any finished sentence inside it.

        Uses Whisper's own segment boundaries (segments end at sentence
        punctuation) instead of word timestamps — same effect, ~40% cheaper.
        """
        seg_audio = buf[speech_start:]
        t0 = time.perf_counter()
        segments = self._transcribe_segments(seg_audio, beam_size=1)
        _dbg(f"partial pass: {seg_audio.size/RATE:.1f}s audio -> "
             f"{len(segments)} segments in {time.perf_counter()-t0:.2f}s")
        if not segments:
            return
        text = " ".join(s[0] for s in segments).strip()

        boundary = None
        if self.cfg.early_commit and len(segments) > 1:
            # Last segment that ends a sentence AND has speech continuing
            # after it (so the boundary is real, not a mid-sentence blip).
            for i in range(len(segments) - 2, -1, -1):
                s_text, _start, s_end = segments[i]
                if not s_text.rstrip().endswith((".", "!", "?", "…")):
                    continue
                committed_words = sum(len(s[0].split()) for s in segments[: i + 1])
                spoken_after = (seg_audio.size / RATE) - s_end
                if (
                    committed_words >= self.cfg.early_min_words
                    and spoken_after >= self.cfg.early_continue_s
                ):
                    boundary = i
                    break

        if boundary is not None:
            sentence = " ".join(s[0] for s in segments[: boundary + 1]).strip()
            # Cut at whichever comes first: this segment's end or the next
            # segment's start, then step BACK a safety margin. Whisper's
            # boundary timestamps overshoot into the next sentence on
            # continuous speech, which would eat its first words ("These
            # cells communicate" -> "communicate"). Re-hearing a fraction of
            # the committed tail is harmless; losing words is not.
            cut_s = min(segments[boundary][2], segments[boundary + 1][1]) - 0.3
            cut = speech_start + int(max(cut_s, 0.0) * RATE)
            cut = min(cut, buf.size)
            self._trim_to(buf.size - cut, buf.size)
            self._last_partial = ""
            if sentence:
                self._record_context(sentence)
                self.on_commit(sentence, time.perf_counter() - t0)
            rest = " ".join(s[0] for s in segments[boundary + 1:]).strip()
            if rest:
                self._last_partial = rest
                self.on_partial(rest)
        elif text and text != self._last_partial:
            self._last_partial = text
            self.on_partial(text)

    def _commit(self, audio: np.ndarray, consumed: int, total: int) -> None:
        t0 = time.perf_counter()
        text = self._transcribe(audio, beam_size=self.cfg.beam_size)
        _dbg(f"commit pass: {audio.size/RATE:.1f}s audio in {time.perf_counter()-t0:.2f}s")
        self._trim_to(total - consumed, total)
        self._last_partial = ""
        if text:
            self._record_context(text)
            self.on_commit(text, time.perf_counter() - t0)

    def _trim_to(self, keep: int, seen: int) -> None:
        """Drop everything except the last `keep` samples of the first `seen`."""
        with self._buf_lock:
            extra = self._buf.size - seen  # audio that arrived while we worked
            tail = keep + max(extra, 0)
            self._buf = self._buf[-tail:] if tail > 0 else np.zeros(0, dtype=np.float32)

    def _transcribe(self, audio: np.ndarray, beam_size: int) -> str:
        if audio.size < int(self.cfg.min_speech_s * RATE):
            return ""
        prompt = self._get_initial_prompt()
        segments, _info = self.model.transcribe(
            audio,
            language=self.cfg.language,
            beam_size=beam_size,
            initial_prompt=prompt,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,  # we already ran VAD ourselves
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def _transcribe_segments(
        self, audio: np.ndarray, beam_size: int
    ) -> list[tuple[str, float, float]]:
        """Transcribe with segment timestamps: [(text, start_s, end_s), ...]."""
        if audio.size < int(self.cfg.min_speech_s * RATE):
            return []
        prompt = self._get_initial_prompt()
        segments, info = self.model.transcribe(
            audio,
            language=self.cfg.language,
            beam_size=beam_size,
            initial_prompt=prompt,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        result = [(seg.text.strip(), seg.start, seg.end) for seg in segments]
        if result:  # only trust detection when it actually heard something
            self.detected_language = info.language
        return result


class MoonshineStreamingTranscriber:
    """Real-time ultra-low-latency streaming transcriber powered by Moonshine Voice."""

    def __init__(
        self,
        config: SttConfig | None = None,
        on_partial: Callable[[str], None] | None = None,
        on_commit: Callable[[str, float], None] | None = None,
    ) -> None:
        self.cfg = config or SttConfig()
        self.on_partial = on_partial or (lambda text: None)
        self.on_commit = on_commit or (lambda text, latency: None)
        self.detected_language: Optional[str] = self.cfg.language or "en"
        self.device = "onnx"

        from moonshine_voice import (
            ModelArch,
            TranscriptEventListener,
            Transcriber,
            get_model_for_language,
        )

        lang = self.cfg.language or "en"
        model_name = (self.cfg.model_name or "moonshine-medium").lower()

        if "tiny" in model_name:
            wanted_arch = ModelArch.TINY_STREAMING
        elif "small" in model_name:
            wanted_arch = ModelArch.SMALL_STREAMING
        else:
            wanted_arch = ModelArch.MEDIUM_STREAMING

        try:
            path, resolved_arch = get_model_for_language(lang, wanted_arch)
        except Exception:
            try:
                path, resolved_arch = get_model_for_language(lang)
            except Exception:
                path, resolved_arch = get_model_for_language("en", wanted_arch)

        self._transcriber = Transcriber(model_path=path, model_arch=resolved_arch)
        self._stream = self._transcriber.create_stream()

        parent = self

        class _Listener(TranscriptEventListener):
            def __init__(self):
                self._last_partial = ""

            def on_line_updated(self, event):
                text = event.line.text.strip()
                if text and text != self._last_partial:
                    self._last_partial = text
                    parent.on_partial(text)

            def on_line_completed(self, event):
                text = event.line.text.strip()
                if text:
                    self._last_partial = ""
                    lat = (event.line.last_transcription_latency_ms or 50) / 1000.0
                    parent.on_commit(text, lat)

        self._listener = _Listener()
        self._stream.add_listener(self._listener)
        self._stream.start()

        self._buf_queue: list[np.ndarray] = []
        self._buf_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def push(self, samples: np.ndarray) -> None:
        if samples.size == 0:
            return
        with self._buf_lock:
            self._buf_queue.append(samples)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="moonshine-stt")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        try:
            self._stream.stop()
            self._stream.close()
            self._transcriber.close()
        except Exception:
            pass

    def flush_buffer(self) -> None:
        """Discard all buffered audio and reset partial state.

        Called by the capture gating logic when DUB starts speaking to prevent
        any TTS-contaminated audio from being processed.
        """
        with self._buf_lock:
            self._buf_queue.clear()
        self._listener._last_partial = ""
        self.on_partial("")

    def _run(self) -> None:
        tick = 0.08
        while not self._stop.is_set():
            time.sleep(tick)
            chunks = []
            with self._buf_lock:
                if self._buf_queue:
                    chunks = self._buf_queue[:]
                    self._buf_queue.clear()

            if chunks:
                audio = np.concatenate(chunks)
                try:
                    self._stream.add_audio(audio)
                    self._stream.update_transcription()
                except Exception as exc:
                    _dbg(f"[moonshine] transcribe error: {exc}")


def create_transcriber(
    config: SttConfig | None = None,
    on_partial: Callable[[str], None] | None = None,
    on_commit: Callable[[str, float], None] | None = None,
) -> StreamingTranscriber | MoonshineStreamingTranscriber:
    """Factory creating either Faster-Whisper or Moonshine streaming transcriber."""
    cfg = config or SttConfig()
    name = (cfg.model_name or "").lower()
    if "moonshine" in name:
        return MoonshineStreamingTranscriber(cfg, on_partial, on_commit)
    return StreamingTranscriber(cfg, on_partial, on_commit)


# --------------------------------------------------------------------- demo

def main() -> None:
    """Live demo: transcribe whatever the PC is playing, print to console."""
    import argparse

    from rtt.audio import LoopbackCapture, MonoResampler16k

    parser = argparse.ArgumentParser(description="Live system-audio transcription demo")
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default=None, help="e.g. en, vi (default: autodetect)")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    args = parser.parse_args()

    def show_partial(text: str) -> None:
        line = f"  … {text}" if text else ""
        print(f"\r\x1b[2K{line[:110]}", end="", flush=True)

    def show_commit(text: str, latency: float) -> None:
        print(f"\r\x1b[2K>> {text}   [{latency*1000:.0f} ms]")

    print(f"Loading model {args.model!r} ...")
    stt = StreamingTranscriber(
        SttConfig(model_name=args.model, language=args.language, device=args.device),
        on_partial=show_partial,
        on_commit=show_commit,
    )
    print(f"Model ready on {stt.device.upper()}. Play some audio — Ctrl+C to stop.\n")

    cap = LoopbackCapture()
    res = MonoResampler16k(cap.rate, cap.channels)
    stt.start()
    cap.start()
    try:
        while True:
            stt.push(res.process(cap.read()))
    except KeyboardInterrupt:
        pass
    finally:
        cap.close()
        stt.stop()
        print("\nStopped.")


if __name__ == "__main__":
    main()
