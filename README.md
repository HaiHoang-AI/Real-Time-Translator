# Real-Time Translate (rtt)

Ứng dụng PC dịch thuật **thời gian thực, chạy 100% local** — nghe âm thanh hệ thống
(YouTube, Netflix, họp online…), hiện **phụ đề overlay** và có **chế độ thuyết minh
(dub/cabin)**: giọng máy đọc bản dịch đè lên tiếng gốc, tự giảm âm lượng tiếng gốc.

Không có bất kỳ dữ liệu âm thanh nào rời khỏi máy.

## Tính năng

- 🎧 **Bắt âm thanh hệ thống** qua WASAPI loopback — không cần virtual cable
- 📝 **Phụ đề real-time**: partial hiện ngay (~0.8s), câu chốt sau ~1–4s
- 🌐 **Dịch offline** bằng NLLB-200 (hỗ trợ tiếng Việt tốt, 200 ngôn ngữ)
- 🗣️ **Chế độ thuyết minh (`--dub`)**: TTS tiếng Việt (Piper) đọc bản dịch,
  tự duck âm lượng các app khác như phiên dịch cabin, tự tăng tốc đọc khi bị tụt lại
- ⚡ **GPU (CUDA)** tự bật nếu có, fallback CPU; VAD + thuật toán chốt câu riêng
- 🖥️ **Overlay** không viền, always-on-top, click-through, kéo thả qua system tray

## Yêu cầu

- Windows 11 (WASAPI loopback + per-app volume)
- Python 3.11+ và [uv](https://docs.astral.sh/uv/)
- (Tùy chọn) GPU NVIDIA — nhanh hơn ~20 lần
- Lưu ý: **Smart App Control** phải tắt (chặn DLL chưa ký của thư viện ML)

## Cài đặt

```bash
uv sync
# Tải giọng thuyết minh tiếng Việt (1 lần):
uv run python -m piper.download_voices --data-dir models/piper vi_VN-vais1000-medium
```

Model Whisper + NLLB tự tải về cache HuggingFace ở lần chạy đầu (~1.1 GB).

## Chạy

```bash
# Phụ đề overlay: dịch Anh -> Việt
uv run python -m rtt.app --src en --tgt vi

# Chế độ thuyết minh (dub) + phụ đề
uv run python -m rtt.app --src en --tgt vi --dub

# Chế độ console (debug, không overlay)
uv run python -m rtt.app --console --src en --tgt vi
```

Tùy chọn: `--model small|medium|large-v3` (mặc định `small`), `--device auto|cuda|cpu`.
Điều khiển qua icon ở system tray (di chuyển phụ đề / thoát).

## Kiến trúc

```
Loopback audio (WASAPI) ──► VAD (Silero) ──► faster-whisper (STT)
        │                                        │ partial / commit
        │                                        ▼
        │                                  NLLB-200 (dịch)
        │                                        │
        │                        ┌───────────────┴──────────────┐
        │                        ▼                              ▼
        │                 Overlay phụ đề                 Piper TTS (dub)
        │                                                       │
        └── duck volume các app khác ◄──────────────────────────┘
```

| File | Vai trò |
|---|---|
| `rtt/audio.py` | Bắt loopback + resample 16 kHz mono; chống "đói" stream khi im lặng |
| `rtt/stt.py` | Streaming STT: VAD + thuật toán chốt câu (partial/commit) |
| `rtt/translate.py` | NLLB-200 qua CTranslate2, GPU/CPU tự chọn |
| `rtt/overlay.py` | Cửa sổ phụ đề trong suốt (PySide6) |
| `rtt/dub.py` | TTS Piper + ducking (pycaw) + pacing động + gate chống vòng lặp |
| `rtt/app.py` | Ghép pipeline, CLI, system tray |
| `rtt/cudalibs.py` | Nạp DLL cuBLAS/cuDNN từ pip cho CTranslate2 |

## Trạng thái & Lộ trình

- [x] P0–P2: pipeline hoàn chỉnh, đã test E2E (EN→VI, phụ đề + dub)
- [ ] V2: process-exclusive loopback (không mất lời gốc khi dub đang đọc)
- [ ] PhoWhisper cho STT tiếng Việt nguồn; chọn model theo máy; đóng gói installer
