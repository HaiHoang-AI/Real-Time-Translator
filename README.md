# Real-Time Translator

**Local, real-time speech translation for your PC.** Listens to whatever your
computer is playing (YouTube, Netflix, online meetings, games…), then shows
live translated subtitles as an on-screen overlay — and can even *speak* the
translation over the original audio like a simultaneous interpreter
("dub / cabin mode"). Everything runs **100% on your machine**: no cloud, no
account, no audio ever leaves your PC.

> 🇻🇳 Người Việt? Xem [hướng dẫn tiếng Việt](#-hướng-dẫn-tiếng-việt) bên dưới.

## Features

- 🎧 **System-audio capture** via WASAPI loopback — no virtual cable needed
- 📝 **Real-time subtitles**: live partial updates ~0.8 s, sentences finalized
  in ~1–4 s (GPU) using an early-commit algorithm that cuts on punctuation,
  so non-stop narration (TED talks, news) still translates sentence by sentence
- 🌐 **Offline translation** with NLLB-200 (200 languages, strong Vietnamese)
- 🗣️ **Dub / cabin mode** (`--dub`): a local TTS voice (Piper) speaks the
  translation over the original, auto-ducking other apps' volume and
  dynamically speeding up to catch up — like a human interpreter
- ⚡ **CUDA acceleration** with automatic CPU fallback; auto-selects the best
  Whisper model available locally (`large-v3` → `small`)
- 🖥️ **Overlay** that is frameless, always-on-top and click-through — it never
  steals focus from your game or video

## Requirements

- Windows 11 (WASAPI loopback + per-app volume control)
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Optional: NVIDIA GPU (≈20× faster; first CUDA run JIT-compiles once)
- Note: Windows **Smart App Control** must be off (it blocks unsigned DLLs
  shipped by mainstream ML wheels)

## Quick start

```bash
git clone https://github.com/HaiHoang-AI/Real-Time-Translator.git
cd Real-Time-Translator
uv sync

# one-time: download the Vietnamese dub voice
uv run python -m piper.download_voices --data-dir models/piper vi_VN-vais1000-medium

# subtitles only (English -> Vietnamese)
uv run python -m rtt.app --src en --tgt vi

# subtitles + spoken dub
uv run python -m rtt.app --src en --tgt vi --dub
```

Whisper and NLLB models download automatically to the Hugging Face cache on
first run (~1.1 GB with the default `small`; `large-v3` is picked up
automatically if you pre-download it):

```bash
uv run python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-large-v3')"
```

Useful flags: `--model auto|small|medium|large-v3`, `--device auto|cuda|cpu`,
`--no-live` (disable live partial translation), `--console` (debug mode).
Control the app from the tray icon (move subtitles / quit).

## How it works

```
Loopback audio (WASAPI) ──► Silero VAD ──► faster-whisper (STT)
        │                                     │ partials / commits
        │                                     ▼
        │                               NLLB-200 (MT)
        │                                     │
        │                     ┌───────────────┴──────────────┐
        │                     ▼                              ▼
        │              Subtitle overlay                Piper TTS (dub)
        │                                                    │
        └──── duck other apps' volume ◄──────────────────────┘
```

| Module | Role |
|---|---|
| `rtt/audio.py` | Loopback capture + streaming resample to 16 kHz mono; survives WASAPI starvation on silence |
| `rtt/stt.py` | Streaming STT: VAD + partial/commit + punctuation early-commit (word timestamps) |
| `rtt/translate.py` | NLLB-200 via CTranslate2, CUDA w/ CPU fallback |
| `rtt/overlay.py` | Transparent subtitle overlay (PySide6) |
| `rtt/dub.py` | Piper TTS + per-app ducking (pycaw) + catch-up pacing + feedback gate |
| `rtt/app.py` | Pipeline wiring, live translation, tray, single-instance |
| `rtt/cudalibs.py` | cuBLAS/cuDNN DLL resolution from pip wheels |

## Roadmap

- [ ] Process-exclusive loopback (keep hearing the original while the dub voice speaks)
- [ ] PhoWhisper for Vietnamese-source audio
- [ ] Settings UI (languages, font, position, voices)
- [ ] Packaged installer

## License & third-party notices

The source code in this repository is released under the **MIT License**
(see [LICENSE](LICENSE)). It depends on third-party components with their own
licenses — **read this before any commercial use**:

| Component | License | Implication |
|---|---|---|
| [NLLB-200 weights](https://huggingface.co/facebook/nllb-200-distilled-600M) | **CC-BY-NC 4.0** | ⚠️ **Non-commercial only.** Swap the MT engine before selling anything built on this. |
| [piper-tts](https://github.com/OHF-Voice/piper1-gpl) | **GPL-3.0** | Distributing a bundled binary that includes Piper makes the combined work GPL. Fine for this source repo / personal use. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) + Whisper weights | MIT | OK |
| [Silero VAD](https://github.com/snakers4/silero-vad) | MIT | OK |
| PySide6 / Qt | LGPL-3.0 | OK when dynamically linked (default) |
| pyaudiowpatch, pycaw, CTranslate2 | MIT | OK |

---

## 🇻🇳 Hướng dẫn tiếng Việt

Ứng dụng dịch **thời gian thực, chạy hoàn toàn trên máy bạn** — nghe âm thanh
hệ thống (YouTube, Netflix, họp online…), hiện phụ đề dịch nổi trên màn hình,
và có **chế độ thuyết minh**: giọng máy tiếng Việt đọc bản dịch đè lên tiếng
gốc như phiên dịch cabin. Không cloud, không tài khoản, âm thanh không rời máy.

### Cài đặt

```bash
git clone https://github.com/HaiHoang-AI/Real-Time-Translator.git
cd Real-Time-Translator
uv sync
uv run python -m piper.download_voices --data-dir models/piper vi_VN-vais1000-medium
```

### Chạy

```bash
# Phụ đề (Anh -> Việt)
uv run python -m rtt.app --src en --tgt vi

# Phụ đề + giọng thuyết minh tiếng Việt
uv run python -m rtt.app --src en --tgt vi --dub
```

- Điều khiển qua icon **VI** ở khay hệ thống (di chuyển phụ đề / thoát)
- Lần chạy đầu sẽ tải model (~1.1 GB) — các lần sau mở ngay
- Máy có GPU NVIDIA: nhanh hơn ~20 lần, lần đầu compile kernel ~10–30 giây
- Cần tắt **Smart App Control** (Windows Security → App & browser control)

### Lưu ý bản quyền

Code repo này dùng giấy phép MIT, nhưng model dịch **NLLB-200 là
CC-BY-NC (phi thương mại)** và **Piper TTS là GPL-3.0** — nếu định thương mại
hóa cần thay các thành phần này (xem bảng ở trên).
