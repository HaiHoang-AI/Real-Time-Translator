"""System-audio (WASAPI loopback) capture + resampling to 16 kHz mono float32.

Captures whatever is playing on the default speakers (YouTube, Netflix, a
meeting, a game...) without a virtual cable, using pyaudiowpatch's loopback
support. Output is normalized to the format Whisper expects: 16 kHz, mono,
float32 in [-1, 1].
"""

from __future__ import annotations

import numpy as np
import pyaudiowpatch as pyaudio

TARGET_RATE = 16000


class LoopbackCapture:
    """Blocking-read capture of the default output device's loopback stream."""

    def __init__(self, chunk_ms: int = 30) -> None:
        self._pa = pyaudio.PyAudio()
        self.device = self._default_loopback_device()
        self.rate = int(self.device["defaultSampleRate"])
        self.channels = int(self.device["maxInputChannels"])
        self.chunk_frames = max(1, int(self.rate * chunk_ms / 1000))
        self._stream = None

    def _default_loopback_device(self) -> dict:
        pa = self._pa
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as exc:  # pragma: no cover - platform dependent
            raise RuntimeError("WASAPI host API not available on this system.") from exc

        default_out = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if default_out.get("isLoopbackDevice"):
            return default_out

        # Find the loopback endpoint that mirrors the default speakers.
        for loopback in pa.get_loopback_device_info_generator():
            if default_out["name"] in loopback["name"]:
                return loopback
        raise RuntimeError(
            "No WASAPI loopback device found for the default speakers. "
            "Make sure an output device is active."
        )

    def start(self) -> None:
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.rate,
            frames_per_buffer=self.chunk_frames,
            input=True,
            input_device_index=self.device["index"],
        )

    def read(self) -> np.ndarray:
        """Read one chunk. Returns interleaved int16 samples (channels mixed in)."""
        assert self._stream is not None, "call start() first"
        data = self._stream.read(self.chunk_frames, exception_on_overflow=False)
        return np.frombuffer(data, dtype=np.int16)

    def read_available(self) -> np.ndarray:
        """Non-blocking read of whatever frames are ready (possibly none).

        WASAPI loopback STOPS delivering frames when no app is rendering
        audio, so a blocking read() would hang on system silence. Callers
        that need a steady timeline must synthesize silence themselves
        (see app.Pipeline._capture_loop).
        """
        assert self._stream is not None, "call start() first"
        avail = self._stream.get_read_available()
        if avail < self.chunk_frames:
            return np.zeros(0, dtype=np.int16)
        data = self._stream.read(self.chunk_frames, exception_on_overflow=False)
        return np.frombuffer(data, dtype=np.int16)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        self._pa.terminate()

    def __enter__(self) -> "LoopbackCapture":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class MonoResampler16k:
    """Downmix to mono and resample the incoming rate to 16 kHz using PyAV.

    PyAV's resampler keeps internal state across calls, so streaming chunks stay
    phase-continuous (no clicks at chunk boundaries).
    """

    def __init__(self, in_rate: int, in_channels: int) -> None:
        import av  # pulled in as a faster-whisper dependency
        from fractions import Fraction

        self.in_rate = in_rate
        self.in_channels = in_channels
        self._resampler = av.AudioResampler(format="flt", layout="mono", rate=TARGET_RATE)
        self._av = av
        self._time_base = Fraction(1, in_rate)
        self._pts = 0

    def process(self, int16_interleaved: np.ndarray) -> np.ndarray:
        if int16_interleaved.size == 0:
            return np.zeros(0, dtype=np.float32)

        # Downmix channels -> mono float32 in [-1, 1].
        mono = int16_interleaved.reshape(-1, self.in_channels).astype(np.float32).mean(axis=1)
        mono /= 32768.0

        frame = self._av.AudioFrame.from_ndarray(
            mono.reshape(1, -1), format="flt", layout="mono"
        )
        frame.rate = self.in_rate
        frame.pts = self._pts
        frame.time_base = self._time_base
        self._pts += mono.shape[0]

        chunks = []
        for out in self._resampler.resample(frame):
            chunks.append(out.to_ndarray().reshape(-1).astype(np.float32))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)


def list_loopback_devices() -> list[dict]:
    """Diagnostic helper: list all WASAPI loopback endpoints."""
    pa = pyaudio.PyAudio()
    try:
        return list(pa.get_loopback_device_info_generator())
    finally:
        pa.terminate()


if __name__ == "__main__":
    print("WASAPI loopback devices:")
    for dev in list_loopback_devices():
        print(f"  [{dev['index']}] {dev['name']}  "
              f"({int(dev['defaultSampleRate'])} Hz, {dev['maxInputChannels']} ch)")

    cap = LoopbackCapture()
    print(f"\nDefault loopback -> [{cap.device['index']}] {cap.device['name']}")
    print(f"Rate={cap.rate} Hz, channels={cap.channels}, chunk={cap.chunk_frames} frames")
    res = MonoResampler16k(cap.rate, cap.channels)
    cap.start()
    print("Capturing 2 s ... play some audio now.")
    peak = 0.0
    for _ in range(int(2000 / 30)):
        mono = res.process(cap.read())
        if mono.size:
            peak = max(peak, float(np.max(np.abs(mono))))
    cap.close()
    print(f"Peak level over 2 s: {peak:.4f} (0 = silence, ~1 = loud). "
          f"{'OK, audio detected.' if peak > 0.001 else 'Silence — is audio playing?'}")
