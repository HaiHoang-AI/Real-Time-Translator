# Handover Document (handoff.md) - Real-Time Translator (rtt)

> **Ngày cập nhật:** 04/08/2026  
> **Dự án:** Real-Time Translator (rtt / Real-Time-Translator-V2)  
> **Tác giả / Repository:** [HaiHoang-AI/Real-Time-Translator-V2](https://github.com/HaiHoang-AI/Real-Time-Translator)

---

## 1. Tổng quan dự án (Project Overview)

**Real-Time Translator (`rtt`)** là ứng dụng desktop chạy trực tiếp trên Windows, tự động bắt âm thanh hệ thống (WASAPI loopback từ YouTube, Netflix, cuộc họp Zoom/Teams, game...), nhận diện giọng nói (STT), dịch thuật thời gian thực (MT) và hiển thị phụ đề nổi hoặc phát giọng thuyết minh đè lên âm thanh gốc ("chế độ cabin / thuyết minh").

### Đặc điểm cốt lõi:
- **100% Offline & Local:** Tất cả model AI (Whisper, NLLB-200, Piper TTS) đều chạy trực tiếp trên máy người dùng. Không tốn chi phí Cloud, không cần tài khoản, dữ liệu âm thanh tuyệt đối an toàn.
- **Bắt âm thanh trực tiếp (WASAPI Loopback):** Không cần cài đặt cáp âm thanh ảo (Virtual Audio Cable).
- **Phụ đề độ trễ cực thấp (Sub-second Latency):** Hiện bản dịch nháp (partial) chỉ sau ~0.8s và chốt câu hoàn chỉnh (commit) sau ~1–4s.
- **Chế độ thuyết minh Cabin (`--dub`):** Sử dụng giọng đọc nhân tạo (Piper TTS) phát bản dịch tiếng Việt đè lên video/cuộc họp, tự động né tiếng (ducking) các ứng dụng khác và tăng tốc độ đọc linh hoạt để đuổi kịp diễn giả.
- **Tăng tốc GPU CUDA:** Hỗ trợ NVIDIA GPU (tăng tốc ~20x), tự động fallback xuống CPU (int8) mượt mà.

---

## 2. Kiến trúc hệ thống & Luồng dữ liệu (Architecture & Data Flow)

```
[Âm thanh hệ thống WASAPI Loopback]
               │
               ▼
      (rtt/audio.py) ──► Resample 16kHz mono (PyAV) ──► Silero VAD (rtt/stt.py)
                                                               │
                                                               ▼
                                                    faster-whisper (STT)
                                                               │ (Partials & Commits)
                                                               ▼
                                                    NLLB-200 CT2 (rtt/translate.py)
                                                               │
                                       ┌───────────────────────┴───────────────────────┐
                                       ▼                                               ▼
                           Overlay Subtitle (rtt/overlay.py)              Piper TTS Dub (rtt/dub.py)
                                                                                       │
                                                                   [Ducking volume ứng dụng khác]
```

### Các Luồng (Threads) hoạt động đồng thời:
1. **Capture Thread (`audio.py`):** Đọc luồng âm thanh loopback từ card âm thanh, bơm silence giả khi hệ thống im lặng để giữ clock thời gian thực.
2. **STT Thread (`stt.py`):** Chạy VAD và Whisper (CTranslate2 backend) xử lý partials/commits.
3. **MT Thread (`translate.py`):** Quản lý hàng đợi dịch thuật các câu commit (beam=4) và dịch nháp partial mới nhất khi rảnh (beam=1).
4. **Dub Thread (`dub.py`):** Tổng hợp giọng đọc Piper TTS và phát âm thanh ra loa, quản lý né tiếng (pycaw).
5. **Qt Main Thread (`overlay.py` / `app.py`):** Quản lý giao diện phụ đề nổi trong suốt và khay hệ thống (System Tray).

---

## 3. Chi tiết các Module mã nguồn (Codebase Breakdown)

| File | Vai trò & Chi tiết kỹ thuật |
|---|---|
| [`rtt/cudalibs.py`](file:///d:/Real%20Time%20Translate%20project%20Anti/rtt/cudalibs.py) | Giải quyết lỗi load DLL CUDA trên Windows. Tìm các thư viện `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-nvrtc` trong pip wheel và nạp vào `os.add_dll_directory` & `PATH`. Xử lý JIT compile cho kiến trúc GPU mới (ví dụ Blackwell). |
| [`rtt/audio.py`](file:///d:/Real%20Time%20Translate%20project%20Anti/rtt/audio.py) | **`LoopbackCapture`**: Bắt âm thanh mặc định từ WASAPI qua `pyaudiowpatch`. Sử dụng non-blocking read (`read_available`) để không bị treo khi hệ thống im lặng.<br>**`MonoResampler16k`**: Dùng `av.AudioResampler` (PyAV) trộn mono và resample về 16kHz float32 liên tục, không bị đứt đoạn hay nổ tiếng giữa các chunk. |
| [`rtt/stt.py`](file:///d:/Real%20Time%20Translate%20project%20Anti/rtt/stt.py) | **`StreamingTranscriber`**: Thuật toán Sentence-Commit & Early-Commit đặc thù:<br>- **Commit khi ngắt câu:** VAD thấy im lặng `>= 0.45s` sau tiếng nói -> chốt câu.<br>- **Early-Commit bằng dấu câu:** Khi nói liên tục (TED talk, tin tức), nếu phân đoạn chứa dấu câu (`.!?…`) và có đoạn thoại tiếp theo (`>=0.35s`, `>=3 từ`), hệ thống chốt câu ngay lập tức với lề an toàn 0.3s (tránh mất từ đầu câu sau).<br>- **Force-Commit:** Giới hạn 10s buffer tối đa. |
| [`rtt/translate.py`](file:///d:/Real%20Time%20Translate%20project%20Anti/rtt/translate.py) | **`NllbTranslator`**: Sử dụng NLLB-200 distilled 600M qua CTranslate2 (`entai2965/nllb-200-distilled-600M-ctranslate2`). Sử dụng kiểu dữ liệu `int8_float16` trên CUDA để tiết kiệm VRAM và tránh tràn bộ nhớ GPU khi dùng chung với Whisper. Định nghĩa giao thức `Translator` dễ tháo lắp với LLM / Ollama sau này. |
| [`rtt/overlay.py`](file:///d:/Real%20Time%20Translate%20project%20Anti/rtt/overlay.py) | **`SubtitleOverlay`**: Giao diện PySide6 không viền (frameless), luôn ở trên cùng (always-on-top), trong suốt, cho phép click xuyên qua (click-through).<br>- **`_OutlinedLabel`**: Vẽ chữ có viền đen bóng xung quanh bằng `QPainter` để phụ đề luôn dễ đọc trên mọi nền sáng/tối mà không bị mất chữ.<br>- Phím tắt `Ctrl+Alt+S` hoặc menu khay hệ thống để bật/tắt chế độ di chuyển overlay. |
| [`rtt/dub.py`](file:///d:/Real%20Time%20Translate%20project%20Anti/rtt/dub.py) | **`PiperSpeaker`**: Đọc giọng Piper TTS tiếng Việt (`vi_VN-vais1000-medium`).<br>- **`Ducker`**: Dùng `pycaw` (Windows Core Audio API) giảm âm lượng các app khác xuống 18% khi thuyết minh.<br>- **`DubPlayer`**: Hàng đợi phát âm thanh với **Catch-Up Dynamic Pacing** (tự tăng tốc độ đọc từ 1.0x lên tối đa 1.45x nếu hàng đợi bị ứ đọng câu dịch).<br>- **Feedback Gate**: Tạm thời ngắt capture micro/loopback trong lúc thuyết minh phát ra loa để không bị thu lại giọng của chính mình. |
| [`rtt/app.py`](file:///d:/Real%20Time%20Translate%20project%20Anti/rtt/app.py) | **`Pipeline`**: Khởi tạo và liên kết toàn bộ pipeline đa luồng.<br>- **Nạp model an toàn:** Nạp NLLB trước khi nạp Whisper để tránh crash tràn VRAM ngầm.<br>- **Single-Instance Takeover:** Tự động phát hiện và ngắt tiến trình `rtt.app` cũ (bằng `psutil`), chờ 3 giây xả VRAM trước khi chạy instance mới. |

---

## 4. Hướng dẫn cài đặt & Vận hành (Setup & Usage)

### Khởi tạo môi trường
Yêu cầu: **Windows 11**, **Python 3.11+**, **uv** package manager. Tắt Windows Smart App Control (nếu bị chặn DLL).

```bash
git clone https://github.com/HaiHoang-AI/Real-Time-Translator.git
cd Real-Time-Translator
uv sync

# Tải giọng thuyết minh tiếng Việt Piper (chạy 1 lần duy nhất)
uv run python -m piper.download_voices --data-dir models/piper vi_VN-vais1000-medium
```

### Các lệnh khởi chạy phổ biến

```bash
# 1. Chạy phụ đề dịch (Anh -> Việt) - Mặc định UI Overlay
uv run python -m rtt.app --src en --tgt vi

# 2. Chạy phụ đề + Giọng thuyết minh Tiếng Việt (Cabin Mode)
uv run python -m rtt.app --src en --tgt vi --dub

# 3. Chạy chế độ Console (Debug/Log ra Terminal)
uv run python -m rtt.app --src en --tgt vi --console

# 4. Tùy chọn model Whisper lớn hơn (nếu đã pre-download large-v3)
uv run python -m rtt.app --src en --tgt vi --model large-v3 --device cuda
```

### Tham số tham chiếu CLI flags:
- `--src`: Ngôn ngữ nguồn (`en`, `ja`, `ko`, `zh`, hoặc `auto` để tự phát hiện).
- `--tgt`: Ngôn ngữ đích (`vi`, `en`, ...).
- `--model`: Model Whisper (`auto`, `small`, `medium`, `large-v3`).
- `--device`: Thiết bị tính toán (`auto`, `cuda`, `cpu`).
- `--dub`: Bật chế độ thuyết minh giọng nói.
- `--no-live`: Tắt dịch nháp các câu đang nói dở.
- `--console`: In log xuất bản dịch ra terminal thay vì mở UI overlay.

---

## 5. Trạng thái hiện tại (Current Status)

- [x] Catch luồng âm thanh hệ thống trực tiếp qua WASAPI loopback không qua cáp ảo.
- [x] Thuật toán Early-Commit dấu câu ngắt câu thông minh cho bài nói dài.
- [x] Dịch thuật offline NLLB-200 chạy mượt trên GPU / CPU int8.
- [x] Giao diện phụ đề nổi trong suốt, click-through, chỉnh vị trí mượt mà.
- [x] Giọng đọc thuyết minh Piper TTS + Auto-ducking âm lượng hệ thống + Tự động tăng tốc độ đọc khi chậm nhịp.
- [x] Quản lý bộ nhớ GPU an toàn, chống crash VRAM OOM, tự kill instance cũ khi khởi chạy lại.

---

## 6. Giấy phép & Tuân thủ bản quyền (License & Compliance)

Mã nguồn dự án phát hành theo giấy phép **MIT License**. Khi thương mại hóa hoặc đóng gói phân phối, cần lưu ý hai thư viện/model đi kèm:
1. **NLLB-200 Model Weights:** Giấy phép **CC-BY-NC 4.0 (Phi thương mại)**. Nếu muốn bán sản phẩm, cần thay thế engine dịch thuật (ví dụ dùng LLM commercial-friendly hoặc Helsinki-NLP).
2. **Piper TTS Engine:** Giấy phép **GPL-3.0**. Việc đóng gói chung binary sẽ khiến sản phẩm đóng gói mang giấy phép GPL.

---

## 7. Định hướng & Kế hoạch tiếp theo (Roadmap for Next Developer)

1. **Process-Exclusive Loopback (Lọc âm thanh ứng dụng):** Cho phép người dùng vẫn nghe thấy tiếng gốc của video/game ở âm lượng nhỏ hoặc chỉ bắt âm thanh từ 1 tiến trình chỉ định.
2. **PhoWhisper Integration:** Tích hợp PhoWhisper / Zipformer để tối ưu hóa nhận diện giọng nói nguồn là tiếng Việt (`src vi`).
3. **Settings UI (Giao diện Cấu hình):** Xây dựng bảng điều khiển PyQt/PySide6 chọn nhanh ngôn ngữ, đổi phông chữ, vị trí overlay, chọn giọng đọc TTS.
4. **Standalone Packaged Installer:** Đóng gói ứng dụng thành file `.exe` hoặc bộ cài đặt hoàn chỉnh (`PyInstaller` / `Nuitka` / `Inno Setup`).
