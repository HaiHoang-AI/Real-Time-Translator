"""AI Session Summarizer using Google Gemini API.

Provides:
- Gemini API client using standard library urllib (zero external dependency).
- Multi-model auto-discovery and fallback (gemini-1.5-flash, gemini-2.0-flash, gemini-pro).
- Multi-style summarization (gạch đầu dòng, đoạn văn ngắn, báo cáo chi tiết).
- Asynchronous QThread worker for smooth, non-blocking UI.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Signal


class SessionSummarizer:
    """Synchronous caller for Gemini REST API with auto-discovery and fallback."""

    def __init__(self, api_key: str = "", model: str = "gemini-1.5-flash") -> None:
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.model = model or "gemini-1.5-flash"

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

        # Build prioritized list of model & version candidates
        candidates = [
            ("v1beta", "gemini-2.5-flash"),
            ("v1beta", "gemini-flash-latest"),
            ("v1beta", "gemini-2.5-flash-lite"),
            ("v1beta", "gemini-3.7-flash"),
            ("v1beta", "gemini-1.5-flash"),
            ("v1beta", "gemini-2.0-flash"),
            ("v1", "gemini-1.5-flash"),
            ("v1beta", "gemini-2.0-flash-exp"),
            ("v1beta", "gemini-1.5-flash-latest"),
            ("v1beta", "gemini-1.5-flash-8b"),
            ("v1beta", "gemini-pro"),
            ("v1", "gemini-pro"),
        ]

        # Put user-configured model first if provided
        if self.model:
            clean_m = self.model.replace("models/", "")
            candidates.insert(0, ("v1beta", clean_m))
            candidates.insert(1, ("v1", clean_m))

        last_error = None
        for api_ver, m_name in candidates:
            url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{m_name}:generateContent?key={self.api_key}"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=35) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    cand_list = res_data.get("candidates", [])
                    if cand_list:
                        parts = cand_list[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
                    raise ValueError("Không nhận được nội dung phản hồi từ Gemini.")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                last_error = f"HTTP {e.code}: {err_body}"
                if e.code == 400 and ("API_KEY_INVALID" in err_body or "API key not valid" in err_body):
                    raise ValueError("Gemini API Key không hợp lệ. Vui lòng kiểm tra lại khóa API trong Cài đặt.")
                if e.code == 404:
                    # Model not found on this endpoint, try next candidate
                    continue
                if e.code == 429:
                    raise RuntimeError("Đã vượt quá giới hạn lượt gọi API (Rate limit 429). Vui lòng thử lại sau 1 phút.")
            except urllib.error.URLError as e:
                raise ConnectionError(f"Không thể kết nối đến máy chủ Google: {e.reason}")
            except Exception as e:
                last_error = str(e)
                continue

        # If all predefined models 404'd, attempt dynamic model discovery
        discovered = self._discover_models()
        if discovered:
            for api_ver, m_name in discovered:
                url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{m_name}:generateContent?key={self.api_key}"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=35) as response:
                        res_data = json.loads(response.read().decode("utf-8"))
                        cand_list = res_data.get("candidates", [])
                        if cand_list:
                            parts = cand_list[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "").strip()
                except Exception:
                    continue

        raise RuntimeError(f"Không thể tạo tóm tắt: {last_error}")

    def _discover_models(self) -> List[tuple[str, str]]:
        """Query Gemini API to list all models enabled for this API key."""
        found = []
        for api_ver in ("v1beta", "v1"):
            url = f"https://generativelanguage.googleapis.com/{api_ver}/models?key={self.api_key}"
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=15) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    for m in data.get("models", []):
                        name = m.get("name", "").replace("models/", "")
                        methods = m.get("supportedGenerationMethods", [])
                        if "generateContent" in methods:
                            found.append((api_ver, name))
            except Exception:
                continue
        return found


class SummarizeWorker(QThread):
    """Background worker for non-blocking UI summarization."""

    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        api_key: str,
        content: str,
        model: str = "gemini-1.5-flash",
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
