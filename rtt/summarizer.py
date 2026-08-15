"""AI Session Summarizer using Google Gemini API.

Provides:
- Gemini API client using standard library urllib (zero external dependency).
- Multi-style summarization (gạch đầu dòng, đoạn văn ngắn, báo cáo chi tiết).
- Asynchronous QThread worker for smooth, non-blocking UI.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal


class SessionSummarizer:
    """Synchronous caller for Gemini REST API."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.0-flash") -> None:
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.model = model or "gemini-2.0-flash"

    def summarize(
        self,
        transcript_content: str,
        style: str = "bullet",
        target_lang: str = "vi",
    ) -> str:
        """Call Gemini API to generate a structured summary."""
        if not self.api_key:
            raise ValueError(
                "Chưa có Gemini API Key!\n\n"
                "Vui lòng vào Cài đặt -> Tóm tắt AI và dán Gemini API Key của bạn để sử dụng tính năng này."
            )

        if not transcript_content.strip():
            raise ValueError("Nội dung phiên trống, không có dữ liệu để tóm tắt.")

        # Construct prompt based on style
        style_instruction = {
            "bullet": (
                "Hãy tóm tắt ngắn gọn các ý chính dưới dạng các gạch đầu dòng rõ ràng, "
                "súc tích, tập trung vào những thông tin quan trọng nhất."
            ),
            "paragraph": (
                "Hãy viết một đoạn văn tóm tắt ngắn gọn (1-2 đoạn), liền mạch và dễ hiểu "
                "về nội dung chính của buổi hội thoại/bài phát biểu."
            ),
            "detailed": (
                "Hãy tóm tắt chi tiết có cấu trúc rõ ràng: Tổng quan chủ đề, các luận điểm chính, "
                "quyết định/kết luận, và các hành động tiếp theo (action items) nếu có."
            ),
        }.get(style, "Hãy tóm tắt các ý chính ngắn gọn dưới dạng gạch đầu dòng.")

        lang_name = "tiếng Việt" if target_lang == "vi" else "English"

        prompt = f"""Bạn là một chuyên gia tóm tắt tài liệu và biên bản cuộc họp thông minh.
Nhiệm vụ của bạn là đọc bản ghi chép các phiên dịch sau đây và đưa ra bản tóm tắt chất lượng cao bằng {lang_name}.

Yêu cầu định dạng:
- {style_instruction}
- Nếu có nhiều phiên, hãy chia mục tiêu đề rõ ràng cho từng phiên.
- Sử dụng định dạng Markdown chuẩn (tiêu đề, in đậm, danh sách).
- Trình bày mạch lạc, trang trọng, loại bỏ các câu trùng lặp hoặc tiếng đệm vô nghĩa.

--- NỘI DUNG BẢN GHI PHIÊN ---
{transcript_content}
"""

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 2048,
            }
        }

        # Candidate models to try in order
        models_to_try = [self.model]
        for fallback in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"):
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_error = None
        for m in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.api_key}"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=35) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    candidates = res_data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
                    raise ValueError("Không nhận được nội dung phản hồi từ Gemini.")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                last_error = f"Lỗi HTTP {e.code}: {err_body}"
                if e.code == 400 and "API_KEY_INVALID" in err_body:
                    raise ValueError("Gemini API Key không hợp lệ. Vui lòng kiểm tra lại khóa API trong Cài đặt.")
                if e.code == 404:
                    # Model not found on this endpoint, try next fallback model
                    continue
                raise RuntimeError(f"Lỗi gọi Gemini API (HTTP {e.code}): {err_body}")
            except urllib.error.URLError as e:
                raise ConnectionError(f"Không thể kết nối đến máy chủ Google: {e.reason}")
            except Exception as e:
                last_error = str(e)
                continue

        raise RuntimeError(f"Không thể tạo tóm tắt: {last_error}")


class SummarizeWorker(QThread):
    """Background worker for non-blocking UI summarization."""

    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        api_key: str,
        content: str,
        model: str = "gemini-2.0-flash",
        style: str = "bullet",
        target_lang: str = "vi",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.api_key = api_key
        self.content = content
        self.model = model
        self.style = style
        self.target_lang = target_lang

    def run(self) -> None:
        try:
            summarizer = SessionSummarizer(api_key=self.api_key, model=self.model)
            result = summarizer.summarize(
                transcript_content=self.content,
                style=self.style,
                target_lang=self.target_lang,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
