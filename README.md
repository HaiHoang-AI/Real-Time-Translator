# 🌐 Real-Time Translator (RTT)

<div align="center">

![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078d7.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Ollama](https://img.shields.io/badge/LLM-Llama_3.2_%7C_Qwen_2.5-orange.svg)
![Gemini](https://img.shields.io/badge/Cloud-Gemini_2.5_Flash-4285F4.svg)
![Whisper](https://img.shields.io/badge/STT-Moonshine_%7C_Faster--Whisper-purple.svg)

**Chương trình dịch phụ đề & thuyết minh cabin thời gian thực cho PC (100% Offline hoặc Cloud LLM)**

*Tự động thu âm thanh hệ thống (YouTube, Netflix, Zoom, Google Meet, Game, Podcast…), nhận dạng giọng nói siêu tốc và hiển thị phụ đề dịch trực tiếp trên màn hình, hỗ trợ đọc thuyết minh tiếng Việt chèn lên âm thanh gốc.*

[English Overview](#-english-overview) • [Tính Năng Nổi Bật](#-tính-năng-nổi-bật) • [Cài Đặt Nhanh](#-cài-đặt-nhanh-quick-start) • [Kiến Trúc & Hoạt Động](#-kiến-trúc-hệ-thống) • [Phím Tắt & Điều Khiển](#-phím-tắt--điều-khiển)

</div>

---

## 🌟 Tính Năng Nổi Bật

### 1. 🎙️ Nhận Dạng Giọng Nói Đỉnh Cao (STT)
* **Moonshine Voice (Mới)**: Tối ưu cho phụ đề thời gian thực với độ trễ cực thấp (~0.03s – 0.08s), chạy nhẹ trên ONNX Runtime không tốn VRAM.
* **Faster-Whisper**: Hỗ trợ đầy đủ từ `large-v3-turbo`, `large-v3`, `medium`, `small` đến `base` / `tiny` với lượng tử hóa INT8 CUDA/CPU.
* **Thu âm WASAPI Loopback**: Tự động bắt trực tiếp âm thanh phát ra từ máy tính mà **không cần cài đặt VB-Cable** hay card âm thanh ảo.

### 2. 🤖 Bộ Dịch Đa Động Cơ (LLM & Neural MT)
* **Ollama Local LLM (100% Offline)**: Sử dụng **Llama 3.2 3B**, **Qwen 2.5 3B / 7B** ngay trên máy tính của bạn. Dịch văn phong tự nhiên, giữ trọn đại từ nhân xưng (`tôi / bạn / chúng ta`), loại bỏ hoàn toàn hiện tượng trả lời câu hỏi hoặc lặp lại tiêu đề.
* **Google Gemini API**: Tích hợp các dòng model siêu nhanh `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `gemini-2.0-flash` với độ trễ <300ms.
* **NLLB-200 Offline**: Động cơ dịch thần kinh CTranslate2 (1.3B & 600M) hỗ trợ 200 ngôn ngữ, hoạt động ổn định khi không có Internet.

### 3. 💡 Bộ Nhớ Ngữ Cảnh & Gợi Ý Chủ Đề Thông Minh (`ContextMemory`)
* **Hộp thoại Tạo Phiên Mới (`NewSessionDialog`)**: Nhập tên video, phim ảnh hoặc nội dung cuộc họp để AI hiểu bối cảnh và dịch sát thuật ngữ chuyên ngành.
* **5 Tag Gợi Ý 1-Chạm**: 🎬 *Phim ảnh*, 💼 *Cuộc họp*, 💻 *Công nghệ / IT*, 📚 *Học tập*, 🎙️ *Phỏng vấn*.
* **Rolling Context Memory**: Tự động lưu 3–5 cặp câu thoại gần nhất, giúp AI duy trì tính mạch lạc trong toàn bộ cuộc hội thoại mà không làm chậm tốc độ dịch.

### 4. 📝 Quản Lý Lịch Sử & Tóm Tắt Cuộc Họp Bằng AI
* **Giao diện Claude / Linear Style**: Thiết kế tối giản, hiện đại với Dark Mode và Light Mode cao cấp.
* **Tóm Tắt Bằng AI (Gemini AI Summary)**: Chọn một hoặc nhiều phiên thoại để AI tự động tổng hợp nội dung chính, ý kiến thảo luận và việc cần làm (Action Items).
* **Xuất File Đa Định Dạng**: Xuất trọn bộ phụ đề sang `.srt`, `.txt`, `.md` chỉ với 1 cú nhấp chuột.
* **Tìm Kiếm Toàn Cục (Cross-Session Search)**: Tra cứu nhanh mọi từ khóa đã từng được ghi lại trong quá khứ.

### 5. 🗣️ Chế Độ Thuyết Minh Cabin Đè Tiếng Gốc (`--dub`)
* **Piper TTS tiếng Việt**: Giọng đọc tự nhiên, tự động giảm nhỏ âm lượng ứng dụng khác (**Auto-Ducking**) và tự động tăng tốc đọc nhịp nhàng khi câu thoại dồn dập.

### 6. 🖥️ Subtitle Overlay Hiện Đại
* Cửa sổ phụ đề trong suốt, không viền, luôn nổi trên cùng (**Always-on-Top**), cho phép xuyên chuột (**Click-through**) không cản trở làm việc hay chơi game.

---

## 🚀 Cài Đặt Nhanh (Quick Start)

### Yêu Cầu Hệ Thống
* **Hệ điều hành**: Windows 10 / 11 (64-bit).
* **Python**: Phiên bản 3.11+ và công cụ quản lý gói siêu tốc [uv](https://docs.astral.sh/uv/).
* **Phần cứng**: CPU hoặc GPU NVIDIA (khuyên dùng GPU RTX có từ 4GB VRAM để đạt tốc độ thời gian thực tốt nhất).

### Các Bước Cài Đặt

1. **Clone mã nguồn và cài đặt thư viện**:
```bash
git clone https://github.com/HaiHoang-AI/Real-Time-Translator.git
cd Real-Time-Translator
uv sync
```

2. **(Tùy chọn) Tải giọng đọc thuyết minh tiếng Việt**:
```bash
uv run python -m piper.download_voices --data-dir models/piper vi_VN-vais1000-medium
```

3. **(Tùy chọn) Khởi động Ollama để dịch cục bộ**:
Cài đặt [Ollama](https://ollama.com/) và tải model dịch khuyên dùng:
```bash
ollama run llama3.2:3b
# hoặc
ollama run qwen2.5:3b
```

---

## 🎬 Hướng Dẫn Sử Dụng

### Khởi Chạy Ứng Dụng

```bash
# 1. Chạy với giao diện đồ họa đầy đủ (HUD + Lịch sử + Cài đặt):
uv run python -m rtt.app --src en --tgt vi

# 2. Chạy kèm giọng thuyết minh cabin:
uv run python -m rtt.app --src en --tgt vi --dub

# 3. Chạy chế độ dòng lệnh (Console Debug):
uv run python -m rtt.app --src en --tgt vi --console
```

### Các Tham Số Dòng Lệnh Thường Dùng:
| Tham số | Ý nghĩa | Ví dụ |
|---|---|---|
| `--src` | Ngôn ngữ nguồn (hoặc `auto` để tự phát hiện) | `--src en` / `--src ja` |
| `--tgt` | Ngôn ngữ dịch sang | `--tgt vi` / `--tgt en` |
| `--model` | Model Whisper (`auto`, `large-v3-turbo`, `small`...) | `--model auto` |
| `--device` | Thiết bị xử lý (`auto`, `cuda`, `cpu`) | `--device cuda` |
| `--dub` | Bật chế độ thuyết minh cabin tiếng Việt | `--dub` |
| `--no-live` | Tắt dịch từ nháp khi đang nói, chỉ dịch khi kết thúc câu | `--no-live` |

---

## ⌨️ Phím Tắt & Điều Khiển

* **`Ctrl + Alt + E`**: Ẩn / Hiện Bảng Điều Khiển Chính (MainWindow).
* **Khay hệ thống (System Tray)**: Nhấp chuột phải vào biểu tượng khay để bật menu điều khiển hoặc Thoát ứng dụng hoàn toàn.
* **Di chuyển phụ đề Overlay**: Nhấn giữ chuột trái vào thanh phụ đề để kéo đến vị trí mong muốn trên màn hình.

---

## 🏗️ Kiến Trúc Hệ Thống

```
                     ┌───────────────────────────┐
                     │   Windows Audio Output    │
                     │ (WASAPI Loopback Capture) │
                     └─────────────┬─────────────┘
                                   │
                                   ▼
                     ┌───────────────────────────┐
                     │    Silero VAD Filter      │
                     └─────────────┬─────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
       ┌────────────────────────┐    ┌────────────────────────┐
       │    Moonshine Voice     │    │  Faster-Whisper (CUDA) │
       │ (Ultra Low-Latency STT)│    │ (Large-v3-Turbo / INT8)│
       └────────────┬───────────┘    └────────────┬───────────┘
                    └──────────────┬──────────────┘
                                   │ Partials & Sentence Commits
                                   ▼
        ┌─────────────────────────────────────────────────────┐
        │       ContextMemory & Domain Topic Prompting        │
        └──────────────────────────┬──────────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            ▼                      ▼                      ▼
┌──────────────────────┐ ┌───────────────────┐ ┌────────────────────┐
│   Ollama Local LLM   │ │ Google Gemini API │ │  NLLB-200 Offline  │
│ (Llama 3.2 / Qwen 2.5│ │ (Flash 2.5 / 2.0) │ │ (CTranslate2 INT8) │
└───────────┬──────────┘ └─────────┬─────────┘ └──────────┬─────────┘
            └──────────────────────┼──────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
       ┌─────────────────────────┐   ┌──────────────────────────┐
       │ Transparent Subtitle UI │   │     Piper TTS Dubbing    │
       │ (Always-on-top Overlay) │   │ (Auto-Ducking Audio Mix) │
       └─────────────────────────┘   └──────────────────────────┘
```

---

## 📁 Cấu Trúc Mã Nguồn

```
Real-Time-Translator/
├── rtt/
│   ├── app.py              # Pipeline chính, điều phối âm thanh, giao diện và khay hệ thống
│   ├── audio.py            # Thu âm WASAPI Loopback, resample 16kHz mono
│   ├── stt.py              # Xử lý STT (Moonshine & Faster-Whisper + Silero VAD)
│   ├── translate.py        # Động cơ dịch (Ollama LLM, Gemini Cloud, NLLB-200 + ContextMemory)
│   ├── history.py          # Quản lý phiên thoại (SessionManager, JSONL storage, retention)
│   ├── main_window.py      # Cửa sổ ứng dụng hợp nhất (HUD + Transcript + Settings)
│   ├── transcript_ui.py    # Giao diện lịch sử phiên phong cách Claude & Tóm tắt AI
│   ├── settings_ui.py      # Giao diện cài đặt toàn diện (Model, Âm thanh, UI, Dubbing)
│   ├── overlay.py          # Cửa sổ phụ đề nổi trong suốt trên màn hình
│   ├── dub.py              # Thuyết minh Piper TTS + Per-App Volume Ducking (pycaw)
│   ├── motion.py           # Hệ thống Animation và hiệu ứng giao diện vật lý mượt mà
│   ├── theme.py            # Bảng màu Dark/Light & quản lý phông chữ tùy chỉnh
│   └── cudalibs.py         # Tự động nạp thư viện DLL CUDA/cuDNN cho CTranslate2
├── pyproject.toml          # Quản lý dependencies qua uv
└── README.md
```

---

## 🌍 English Overview

**Real-Time Translator (RTT)** is a production-grade, local speech translation and simultaneous cabin dubbing tool for Windows. It captures your computer's audio in real time via WASAPI loopback, runs speech-to-text (Moonshine Voice or Faster-Whisper), translates sentences through state-of-the-art Local LLMs (Ollama Llama 3.2 / Qwen 2.5), Gemini Cloud APIs, or offline NLLB-200 models, and renders subtitle overlays while optionally speaking the translation with Piper TTS.

### Key Highlights:
1. **Zero Virtual Audio Cables Required**: Direct WASAPI loopback capture.
2. **Sub-second Latency**: Streaming partial transcription and early punctuation commits.
3. **Local LLM Translations**: Natural Vietnamese cabin translations without server telemetry.
4. **Discourse Context & Topic Prime**: Maintains conversation history and movie/meeting context for accurate domain terminology.
5. **AI Summarization & Session Logs**: One-click multi-session meeting summaries with export to `.srt`, `.txt`, `.md`.

---

## 📄 License & Attribution

Mã nguồn được phân phối dưới giấy phép **MIT License** (xem file [LICENSE](LICENSE)).

*Lưu ý về các thành phần bên thứ ba:*
* **NLLB-200 Weights**: Giấy phép [CC-BY-NC 4.0](https://huggingface.co/facebook/nllb-200-distilled-600M) (Phi thương mại).
* **Piper TTS**: [GPL-3.0](https://github.com/OHF-Voice/piper1-gpl).
* **Faster-Whisper & Silero VAD**: MIT License.
* **PySide6 (Qt6)**: LGPL-3.0.
