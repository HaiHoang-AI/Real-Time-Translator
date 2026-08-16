****
Tuyệt, đây là bước nâng cấp lớn nhất và cũng là phần khó nhất. Mình xác định luôn: cái bạn muốn không còn là "dịch phụ đề" nữa, mà là **real-time speech-to-speech translation (dịch cabin / phiên dịch đồng thời)** — cùng đẳng cấp với những gì Google/Meta đang nghiên cứu. Phần overlay phụ đề là đã có đường mòn; phần **DUB đè lên tiếng gốc** mới là thứ chưa app local nào làm tốt. Đó vừa là thách thức vừa là cơ hội của bạn.

Để mình lưu lại project này vào bộ nhớ rồi trình bày kiến trúc kỹ thuật.

Đã lưu project vào bộ nhớ. Giờ vào phần kỹ thuật.

## 1. Bạn đang xây 2 chế độ, khác nhau về độ khó

||Mode Phụ đề (subtitle)|Mode Dub/Cabin (speech-to-speech)|
|---|---|---|
|Pipeline|Audio → STT → Dịch → **Text overlay**|Audio → STT → Dịch → **TTS → phát đè + ducking**|
|Độ trễ chấp nhận được|1–3s (mắt đọc kịp)|Phải **rất chặt**, và phải _nói nhanh hơn_ để đuổi kịp|
|Độ khó|Trung bình (có đường mòn)|**Cao** — đây là phần mới|

Nên MVP làm mode phụ đề trước, rồi mới bật mode dub trên cùng pipeline.

## 2. Stack local đề xuất (ưu tiên tiếng Việt)

|Khâu|Lựa chọn đề xuất|Lý do|
|---|---|---|
|**Bắt audio hệ thống**|`pyaudiowpatch` (WASAPI loopback) hoặc `soundcard`|Bắt đúng luồng loopback trên Windows, độ trễ thấp|
|**VAD (cắt câu)**|`Silero VAD`|Nhẹ, xác định lúc người nói dừng để "chốt" câu dịch|
|**STT**|**PhoWhisper** (VinAI, fine-tune cho tiếng Việt) hoặc `faster-whisper large-v3`|PhoWhisper mạnh nhất cho tiếng Việt; faster-whisper cho đa ngôn ngữ + tốc độ (CTranslate2)|
|**Dịch**|**NLLB-200** (offline) _hoặc_ LLM local qua **Ollama** (Qwen2.5 / Gemma)|NLLB nhanh & gọn; LLM xử lý câu dở dang + ngữ cảnh tốt hơn (giống lý do LiveCaptions-Translator khuyên dùng LLM)|
|**TTS tiếng Việt (dub)**|**Piper** (real-time, cực nhẹ) cho MVP; **viXTTS/XTTS-v2** khi cần giọng đẹp/clone|Piper latency thấp — bắt buộc cho dub thời gian thực; XTTS đẹp hơn nhưng nặng|
|**Trộn audio / ducking**|tự route qua thiết bị ảo (VB-Cable) hoặc mixer nội bộ|Giảm volume tiếng gốc khi giọng dub nói|
|**UI overlay**|**PySide6** (frameless, always-on-top, click-through `WA_TransparentForMouseEvents`)|Cùng ngôn ngữ Python với ML → 1 process, MVP nhanh|

> Ngôn ngữ chính: **Python** cho MVP (toàn bộ model đều native Python). Sau này nếu muốn app "xịn" đóng gói, có thể tách UI sang Tauri/Electron và giữ Python làm sidecar — nhưng đừng làm sớm.

## 3. Thiết kế Mode Dub/Cabin — phần khó, nói kỹ

Đây là nơi 90% khó khăn nằm. 4 vấn đề cốt lõi:

**① Ducking tiếng gốc (bắt buộc):** Khi giọng dub phát, phải hạ tiếng gốc xuống ~15–25% (không tắt hẳn, để giữ cảm giác + âm nhạc/hiệu ứng). Cách sạch nhất trên Windows: route audio gốc qua **VB-Audio Virtual Cable**, app bạn vừa "nghe" vừa điều khiển volume, rồi trộn giọng dub vào và xuất ra loa. Đây chính là mô hình "cabin" thật.

**② Độ trễ luôn tồn tại — chấp nhận nó:** Phiên dịch viên người thật cũng chậm hơn diễn giả 2–4s (gọi là _ear-voice span_). App của bạn không thể tức thời. Thiết kế đúng là: cho giọng dub **luôn trễ vài giây một cách có kiểm soát**, không cố ép về 0.

**③ Đuổi kịp nhịp (pacing):** Câu tiếng Việt dịch ra có thể dài/ngắn hơn câu gốc. Giải pháp: chỉnh **tốc độ đọc TTS động** (Piper hỗ trợ length_scale) — nếu đang tụt lại thì nói nhanh hơn; nếu nguồn ngừng thì để giọng đọc nốt. Có thể **bỏ bớt từ đệm** ("ừm", "you know") khi dịch để tiết kiệm thời gian.

**④ Chốt câu (commit) đúng lúc:** Không dịch từng từ (sẽ giật và sửa liên tục). Dùng VAD + Whisper partial: khi im lặng > ~500ms hoặc đủ 1 mệnh đề → chốt câu đó, gửi đi dịch + TTS. Đây là thuật toán quan trọng nhất quyết định app mượt hay không.

Luồng dữ liệu mode dub:

```
Loopback audio ──► ring buffer ──► Silero VAD ──► [chốt câu?]
                                                     │
                        ┌────────────────────────────┘
                        ▼
                     PhoWhisper (STT) ──► NLLB/LLM (dịch) ──► Piper TTS
                                                                  │
   Tiếng gốc (đã ducking) ──────────────────►  MIXER  ◄──────────┘
                                                 │
                                                 ▼
                                            Loa / tai nghe
```

## 4. Lộ trình xây dựng (phân giai đoạn)

- **P0 – Xương sống:** Bắt loopback audio + VAD + PhoWhisper → in text ra console. Chứng minh STT tiếng Việt/Anh chạy được, đo latency.
- **P1 – Mode phụ đề:** Thêm dịch (NLLB) + overlay PySide6 (frameless, always-on-top). → Đã có 1 app dùng được.
- **P2 – Mode dub (MVP):** Thêm Piper TTS + phát ra loa, chưa ducking. Cảm nhận độ trễ thật.
- **P3 – Cabin hoàn chỉnh:** Ducking qua VB-Cable + pacing động + thuật toán chốt câu tinh chỉnh.
- **P4 – Đánh bóng:** Chọn ngôn ngữ, chọn model theo máy (CPU/GPU), giọng dub, hotkey, đóng gói installer.

## 5. Rủi ro cần biết trước

- **Vòng lặp âm thanh (feedback):** giọng dub phát ra loa có thể bị chính app "nghe" lại → dịch lộn. Phải tách luồng loopback khỏi luồng dub (dùng virtual cable riêng).
- **GPU:** Whisper large + XTTS chạy CPU sẽ trễ. Nên hỗ trợ CUDA và cho chọn model nhẹ (Piper + faster-whisper `small/base`) cho máy yếu.
- **Bản quyền TTS/model:** kiểm tra license nếu định bán (Piper MIT ✅, XTTS có điều khoản riêng cho thương mại).

---

Bạn muốn mình bắt tay vào đâu tiếp theo? Vài hướng cụ thể:

1. **Dựng khung P0 ngay** — mình viết luôn script Python bắt loopback audio + VAD + faster-whisper, chạy thử trên máy bạn để đo latency thực tế.
2. **Vẽ sơ đồ kiến trúc chi tiết** (artifact có thể mở/zoom) để bạn tham chiếu khi code.
3. **So sánh sâu TTS tiếng Việt** (Piper vs viXTTS vs XTTS) về latency/chất lượng/license để bạn chốt.

Mình gợi ý bắt đầu từ **(1)** — có xương sống chạy được là mọi thứ khác dễ hơn nhiều. Bạn thấy sao?