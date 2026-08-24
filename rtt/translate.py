"""Local machine translation via NLLB-200 (CTranslate2).

Runs Meta's NLLB-200 distilled 600M fully offline through ctranslate2 —
no PyTorch needed. Vietnamese is a first-class citizen here (vie_Latn is
one of NLLB's stronger pairs with English).

The Translator interface is deliberately tiny so we can later drop in an
LLM engine (Ollama) without touching callers.

Smart Term Locking
------------------
Before each translation call, a :class:`~rtt.term_locker.TermLocker`
protects technical terms (LLM, GPU, DNA, …) by replacing them with opaque
placeholders (``__T0__``, ``__T1__``, …).  NLLB translates the remainder
of the sentence, and the terms are restored verbatim (or with their correct
Vietnamese equivalents) afterward.  This prevents the model from garbling
specialised vocabulary.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Optional, Protocol

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

NLLB_REPO = "entai2965/nllb-200-distilled-600M-ctranslate2"
NLLB_1B3_REPO = "OpenNMT/nllb-200-distilled-1.3B-ct2-int8"

# Friendly ISO-639-1 -> NLLB (FLORES-200) codes for the languages we surface
# in the UI. NLLB supports 200; extend freely.
LANG_TO_NLLB = {
    "en": "eng_Latn",
    "vi": "vie_Latn",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "zh": "zho_Hans",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "de": "deu_Latn",
    "ru": "rus_Cyrl",
    "th": "tha_Thai",
    "id": "ind_Latn",
    "pt": "por_Latn",
    "it": "ita_Latn",
    "ar": "arb_Arab",
    "hi": "hin_Deva",
}

LANG_NAMES = {
    "en": "tiếng Anh",
    "vi": "tiếng Việt",
    "ja": "tiếng Nhật",
    "ko": "tiếng Hàn",
    "zh": "tiếng Trung",
    "fr": "tiếng Pháp",
    "es": "tiếng Tây Ban Nha",
    "de": "tiếng Đức",
    "ru": "tiếng Nga",
    "th": "tiếng Thái",
    "id": "tiếng Indonesia",
    "pt": "tiếng Bồ Đào Nha",
    "it": "tiếng Ý",
    "ar": "tiếng Ả Rập",
    "hi": "tiếng Hindi",
}


def _clean_llm_translation(raw: str) -> str:
    """Strip out any LLM prefixes, quotes, meta-commentary, or refusal hallucinations."""
    if not raw:
        return ""
    res = raw.strip()

    # Strip markdown codeblocks if any
    if res.startswith("```") and res.endswith("```"):
        lines = res.splitlines()
        if len(lines) >= 3:
            res = "\n".join(lines[1:-1]).strip()

    # If the response contains apology / conversational boilerplate, extract the quoted/actual text
    if any(k in res.lower() for k in ("xin lỗi", "dưới đây là", "không cần dịch", "câu trả lời", "bản dịch lại")):
        # Check if there is a quoted section
        quotes = re.findall(r'["“](.+?)["”]', res, flags=re.DOTALL)
        if quotes:
            res = quotes[-1].strip()
        else:
            lines = [line.strip() for line in res.splitlines() if line.strip()]
            valid_lines = [
                l for l in lines
                if not any(l.lower().startswith(k) for k in ("tôi xin lỗi", "xin lỗi", "dưới đây là", "vì câu này", "lưu ý", "ghi chú", "đây là"))
            ]
            if valid_lines:
                res = " ".join(valid_lines).strip()

    # Strip outer quotes
    if (res.startswith('"') and res.endswith('"')) or (res.startswith('“') and res.endswith('”')) or (res.startswith("'") and res.endswith("'")):
        res = res[1:-1].strip()

    # Match prefix patterns like:
    # "Dịch sang tiếng Việt (Vietnamese): ..."
    # "Dịch sang tiếng Việt: ..."
    # "Bản dịch: ..."
    # "Vietnamese: ..."
    prefix_regex = r'(?:Dịch\s*sang\s*tiếng\s*[\w\u00C0-\u1EF9\s]+(?:\s*\([^\)]*\))?|Bản\s*dịch|Lời\s*dịch|Câu\s*dịch|Translation|Vietnamese|Tiếng\s*Việt)\s*[:：\-]\s*'
    if re.search(prefix_regex, res, flags=re.IGNORECASE):
        parts = re.split(prefix_regex, res, flags=re.IGNORECASE)
        for p in reversed(parts):
            if p.strip():
                res = p.strip()
                break

    # Strip any remaining leading prefix
    res = re.sub(r'^(?:Dịch\s*sang\s*tiếng\s*[\w\u00C0-\u1EF9\s]+(?:\s*\([^\)]*\))?|Bản\s*dịch|Lời\s*dịch|Câu\s*dịch|Translation|Vietnamese|Tiếng\s*Việt)\s*[:：\-]\s*', '', res, flags=re.IGNORECASE).strip()

    # Strip again outer quotes
    if (res.startswith('"') and res.endswith('"')) or (res.startswith('“') and res.endswith('”')) or (res.startswith("'") and res.endswith("'")):
        res = res[1:-1].strip()

    return res


class ContextMemory:
    """Rolling memory of recent source-target sentence pairs and session topic."""

    def __init__(self, max_items: int = 5) -> None:
        self.max_items = max_items
        self._history: list[tuple[str, str]] = []
        self.topic: str = ""

    def set_topic(self, topic: str) -> None:
        self.topic = (topic or "").strip()

    def get_topic(self) -> str:
        return self.topic

    def add(self, src: str, tgt: str) -> None:
        src = src.strip()
        tgt = tgt.strip()
        if not src:
            return
        self._history.append((src, tgt))
        if len(self._history) > self.max_items:
            self._history = self._history[-self.max_items:]

    def get_context_text(self, max_pairs: int = 3) -> str:
        """Format recent context pairs as reference dialogue."""
        pairs = self._history[-max_pairs:]
        if not pairs:
            return ""
        lines = []
        for s, t in pairs:
            lines.append(f"- Gốc: \"{s}\" -> Dịch: \"{t}\"")
        return "\n".join(lines)

    def clear(self) -> None:
        self._history.clear()


class Translator(Protocol):
    def translate(self, text: str, src: str, tgt: str) -> str: ...


class NllbTranslator:
    """NLLB-200 (600M or 1.3B), int8 on CPU/CUDA (fast enough for subtitle cadence).

    Parameters
    ----------
    device:
        ``"auto"`` tries CUDA first, falls back to CPU.
    compute_type:
        CTranslate2 compute type override (``int8``, ``int8_float16``, …).
    model_repo:
        HuggingFace CTranslate2 model repository ID.
    """

    def __init__(
        self,
        device: str = "auto",
        compute_type: str | None = None,
        model_repo: str = NLLB_1B3_REPO,
    ) -> None:  # noqa: D107
        import ctranslate2
        from huggingface_hub import snapshot_download
        from transformers import AutoTokenizer

        from rtt.cudalibs import setup_cuda_dll_dirs

        setup_cuda_dll_dirs()
        model_dir = snapshot_download(model_repo)

        attempts: list[tuple[str, str]] = []
        if device in ("auto", "cuda"):
            # int8_float16: half the VRAM of float16, same MT quality class,
            # and it avoids OOM spikes when Whisper shares the GPU.
            attempts.append(("cuda", compute_type or "int8_float16"))
        if device in ("auto", "cpu"):
            attempts.append(("cpu", compute_type or "int8"))
        last_err: Exception | None = None
        for dev, compute in attempts:
            try:
                self._translator = ctranslate2.Translator(
                    model_dir, device=dev, compute_type=compute
                )
                self.device = dev
                break
            except Exception as exc:  # noqa: BLE001 - try the next backend
                last_err = exc
        else:
            raise RuntimeError(f"Could not load NLLB on any device: {last_err}")
        # One tokenizer per source language is required (src_lang changes the
        # prefix token), so cache them lazily.
        self._tok_cls = AutoTokenizer
        self._model_dir = model_dir
        self._tokenizers: dict[str, object] = {}

        # Smart term locker — lazy import to avoid circular deps at import time
        from rtt.term_locker import TermLocker
        self._locker = TermLocker()

    def _tokenizer(self, src_nllb: str):
        tok = self._tokenizers.get(src_nllb)
        if tok is None:
            tok = self._tok_cls.from_pretrained(self._model_dir, src_lang=src_nllb)
            self._tokenizers[src_nllb] = tok
        return tok

    def translate(
        self,
        text: str,
        src: str,
        tgt: str,
        beam: int = 2,
        glossary: list[dict] | None = None,
        auto_lock_caps: bool = True,
        auto_lock_camel: bool = True,
    ) -> str:
        """Translate *text* from *src* to *tgt* with smart term locking.

        Parameters
        ----------
        text:
            Raw source sentence.
        src / tgt:
            ISO-639-1 language codes (e.g. ``"en"``, ``"vi"``).
        beam:
            NLLB beam search width.  Use 1 for low-latency live preview,
            4 for committed sentences.
        glossary:
            User glossary entries (list of ``{"source": str, "target": str}``
            dicts) from ``settings.data.glossary.entries``.
        auto_lock_caps:
            Automatically protect ALL_CAPS tokens (GPU, API, …).
        auto_lock_camel:
            Automatically protect CamelCase proper nouns (OpenAI, GitHub, …).
        """
        text = text.strip()
        if not text or src == tgt:
            return text

        # ── Term Locking (pre-translation) ────────────────────────────────
        locked, mapping = self._locker.lock(
            text,
            glossary_entries=glossary or [],
            auto_caps=auto_lock_caps,
            auto_camel=auto_lock_camel,
        )

        # ── NLLB Translation ──────────────────────────────────────────────
        translated = self._nllb_translate(locked, src, tgt, beam)

        # ── Term Restoration (post-translation) ───────────────────────────
        return self._locker.restore(translated, mapping)

    def _nllb_translate(self, text: str, src: str, tgt: str, beam: int = 2) -> str:
        """Raw NLLB-200 translation without term locking."""
        src_nllb = LANG_TO_NLLB.get(src, src)
        tgt_nllb = LANG_TO_NLLB.get(tgt, tgt)

        tok = self._tokenizer(src_nllb)
        source = tok.convert_ids_to_tokens(tok.encode(text))
        results = self._translator.translate_batch(
            [source],
            target_prefix=[[tgt_nllb]],
            beam_size=beam,
            max_decoding_length=512,
        )
        target = results[0].hypotheses[0]
        if target and target[0] == tgt_nllb:
            target = target[1:]
        return tok.decode(tok.convert_tokens_to_ids(target), skip_special_tokens=True)


class GeminiTranslator:
    """Real-time Context-Aware Translation using Google Gemini API.

    Uses sliding context memory of preceding sentences to ensure coherent,
    domain-accurate translation with natural pronouns and flow.
    Falls back gracefully to NLLB if offline or on network error.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "gemini-2.0-flash",
        fallback_translator: Optional[NllbTranslator] = None,
        context_memory: Optional[ContextMemory] = None,
        on_status: Optional[object] = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        self.model = model or "gemini-2.0-flash"
        self.fallback = fallback_translator
        self.context = context_memory or ContextMemory()
        self.on_status = on_status
        self.device = "cloud/api"
        self._last_error: str = ""
        self._last_notify_time: float = 0.0

    def _notify(self, msg: str) -> None:
        now = time.time()
        # Debounce notification so it doesn't spam on every sentence
        if self.on_status and (now - self._last_notify_time > 8.0):
            self._last_notify_time = now
            try:
                if callable(self.on_status):
                    self.on_status(msg)
                elif hasattr(self.on_status, "emit"):
                    self.on_status.emit(msg)
            except Exception:
                pass

    def translate(
        self,
        text: str,
        src: str,
        tgt: str,
        beam: int = 1,
        glossary: list[dict] | None = None,
        auto_lock_caps: bool = True,
        auto_lock_camel: bool = True,
    ) -> str:
        text = text.strip()
        if not text or src == tgt:
            return text

        if not self.api_key:
            if self.fallback:
                return self.fallback.translate(
                    text, src, tgt, beam=beam, glossary=glossary,
                    auto_lock_caps=auto_lock_caps, auto_lock_camel=auto_lock_camel
                )
            return text

        try:
            translated = self._call_gemini(text, src, tgt, glossary=glossary)
            if translated:
                self.context.add(text, translated)
                self._last_error = ""
                return translated
        except Exception as exc:
            if os.environ.get("RTT_DEBUG") == "1":
                print(f"[gemini_mt] warning: {exc}, using fallback")

        # Fallback to local NLLB 1.3B on any API error or empty response
        if self.fallback:
            if self._last_error == "429_quota":
                self._notify("⚠️ Hết hạn ngạch Gemini (429) — Đang tự động dịch bằng NLLB 1.3B Offline")
            else:
                self._notify("⚠️ Mất kết nối Gemini API — Đang tự động dịch bằng NLLB 1.3B Offline")

            out = self.fallback.translate(
                text, src, tgt, beam=beam, glossary=glossary,
                auto_lock_caps=auto_lock_caps, auto_lock_camel=auto_lock_camel
            )
            self.context.add(text, out)
            return out

        return text

    def _nllb_translate(self, text: str, src: str, tgt: str, beam: int = 1) -> str:
        """Forward raw translation to fallback NLLB when in speed mode or raw mode."""
        if self.fallback:
            return self.fallback._nllb_translate(text, src, tgt, beam=beam)
        return text

    def _call_gemini(self, text: str, src: str, tgt: str, glossary: list[dict] | None = None) -> str:
        src_name = LANG_NAMES.get(src, src)
        tgt_name = LANG_NAMES.get(tgt, tgt)

        context_str = self.context.get_context_text(max_pairs=3)
        context_section = f"\n[Ngữ cảnh các câu gần nhất]:\n{context_str}\n" if context_str else ""

        glossary_section = ""
        if glossary:
            terms = [f"- {e.get('source', '')} -> {e.get('target', '')}" for e in glossary if e.get('source')]
            if terms:
                glossary_section = f"\n[Thuật ngữ ưu tiên]:\n" + "\n".join(terms[:10]) + "\n"

        topic = self.context.get_topic()
        topic_section = f"\n[Bối cảnh tham khảo]: {topic} (Chỉ dùng để hiểu đúng thuật ngữ. Bắt buộc dịch câu thoại, không bình luận về bối cảnh).\n" if topic else ""

        system_instruction = (
            f"Bạn là chuyên gia thông dịch viên cabin trực tiếp từ {src_name} sang {tgt_name}.\n"
            f"QUY TẮC BẮT BUỘC:\n"
            f"1. Dịch chuẩn xác, tự nhiên, bám sát ngữ cảnh nói/thuyết trình.\n"
            f"2. Tuyệt đối KHÔNG lặp lại các tiền tố như 'Dịch sang...', 'Bản dịch:', 'Vietnamese:', KHÔNG giải thích hay bình luận.\n"
            f"3. CHỈ XUẤT DUY NHẤT BẢN DỊCH {tgt_name} thuần túy, không kèm dấu ngoặc kép."
        )

        user_content = f"{system_instruction}\n{topic_section}{context_section}{glossary_section}\nCâu cần dịch: {text}"

        candidates = [
            ("v1beta", self.model),
            ("v1beta", "gemini-2.5-flash-lite"),
            ("v1beta", "gemini-2.5-flash"),
            ("v1beta", "gemini-flash-latest"),
            ("v1beta", "gemini-3.7-flash"),
            ("v1beta", "gemini-2.0-flash"),
            ("v1beta", "gemini-1.5-flash"),
            ("v1", "gemini-1.5-flash"),
        ]

        payload = {
            "contents": [
                {
                    "parts": [{"text": user_content}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1024,
                "thinkingConfig": {
                    "thinkingBudget": 0
                }
            }
        }
        data = json.dumps(payload).encode("utf-8")

        # Payload fallback without thinkingConfig for older versions
        payload_plain = {
            "contents": [
                {
                    "parts": [{"text": user_content}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1024,
            }
        }
        data_plain = json.dumps(payload_plain).encode("utf-8")

        for api_ver, m_name in candidates:
            if not m_name:
                continue
            clean_m = m_name.replace("models/", "")
            url = f"https://generativelanguage.googleapis.com/{api_ver}/models/{clean_m}:generateContent?key={self.api_key}"
            
            for post_data in (data, data_plain):
                req = urllib.request.Request(
                    url,
                    data=post_data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                try:
                    with urllib.request.urlopen(req, timeout=3.5) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                        cand_list = body.get("candidates", [])
                        if cand_list:
                            parts = cand_list[0].get("content", {}).get("parts", [])
                            if parts:
                                res = parts[0].get("text", "").strip()
                                res = _clean_llm_translation(res)
                                if res:
                                    return res
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        self._last_error = "429_quota"
                    else:
                        self._last_error = f"http_{e.code}"
                    continue
                except (urllib.error.URLError, TimeoutError, OSError):
                    self._last_error = "network_error"
                    continue
                except Exception:
                    self._last_error = "error"
                    continue
        return ""


class OllamaTranslator:
    """
    Offline Local LLM Translator powered by Ollama (Qwen 2.5).
    Runs 100% locally on GPU/CPU with full Context Memory support.
    """

    def __init__(
        self,
        model: str = "qwen2.5:3b",
        host: str = "http://localhost:11434",
        fallback_translator: Optional[NllbTranslator] = None,
        context_memory: Optional[ContextMemory] = None,
        on_status: Optional[object] = None,
    ) -> None:
        self.model = model or "qwen2.5:3b"
        self.host = host.rstrip("/")
        self.fallback = fallback_translator
        self.context = context_memory or ContextMemory()
        self.on_status = on_status
        self.device = "local/gpu"
        self._last_notify_time: float = 0.0

    def _notify(self, msg: str) -> None:
        now = time.time()
        if self.on_status and (now - self._last_notify_time > 8.0):
            self._last_notify_time = now
            try:
                if callable(self.on_status):
                    self.on_status(msg)
                elif hasattr(self.on_status, "emit"):
                    self.on_status.emit(msg)
            except Exception:
                pass

    def translate(
        self,
        text: str,
        src: str,
        tgt: str,
        beam: int = 1,
        glossary: list[dict] | None = None,
        auto_lock_caps: bool = True,
        auto_lock_camel: bool = True,
    ) -> str:
        text = text.strip()
        if not text:
            return ""

        try:
            res = self._call_ollama(text, src, tgt, glossary=glossary)
            if res:
                self.context.add(text, res)
                return res
        except Exception as exc:
            if os.environ.get("RTT_DEBUG") == "1":
                print(f"[ollama_mt] warning: {exc}, using fallback")

        # Fallback to local NLLB 1.3B on any Ollama error or empty response
        if self.fallback:
            self._notify("⚠️ Không kết nối được Ollama — Đang tự động dịch bằng NLLB 1.3B Offline")
            out = self.fallback.translate(
                text, src, tgt, beam=beam, glossary=glossary,
                auto_lock_caps=auto_lock_caps, auto_lock_camel=auto_lock_camel
            )
            self.context.add(text, out)
            return out

        return text

    def _nllb_translate(self, text: str, src: str, tgt: str, beam: int = 1) -> str:
        if self.fallback:
            return self.fallback._nllb_translate(text, src, tgt, beam=beam)
        return text

    def _call_ollama(self, text: str, src: str, tgt: str, glossary: list[dict] | None = None) -> str:
        src_name = LANG_NAMES.get(src, src)
        tgt_name = LANG_NAMES.get(tgt, tgt)

        context_str = self.context.get_context_text(max_pairs=3)
        glossary_section = ""
        if glossary:
            terms = [f"- {e.get('source', '')} -> {e.get('target', '')}" for e in glossary if e.get('source')]
            if terms:
                glossary_section = f"\n[Thuật ngữ chuyên ngành]:\n" + "\n".join(terms[:10])

        system_instruction = (
            f"Bạn là hệ thống dịch cabin phụ đề tự động từ {src_name} sang {tgt_name}.\n"
            f"Nhiệm vụ: Dịch trung thực và tự nhiên câu thoại sang {tgt_name}.\n"
            f"QUY TẮC BẮT BUỘC:\n"
            f"1. Dịch trung thực câu thoại sang {tgt_name}. Tuyệt đối KHÔNG trả lời câu hỏi, KHÔNG đối thoại, KHÔNG xin lỗi, KHÔNG giải thích, KHÔNG từ chối dịch.\n"
            f"2. Tuyệt đối KHÔNG lặp lại các tiền tố như 'Dịch sang...', 'Bản dịch:', 'Vietnamese:', 'Tiếng Việt:' hoặc tên chủ đề.\n"
            f"3. Giữ đúng đại từ nhân xưng và ngữ điệu tự nhiên của người nói.\n"
            f"4. CHỈ XUẤT DUY NHẤT câu dịch {tgt_name} thuần túy, không có chữ Hán, không kèm ngoặc kép."
        )

        messages = [
            {"role": "system", "content": system_instruction}
        ]
        topic = self.context.get_topic()
        if topic:
            messages.append({"role": "system", "content": f"[Bối cảnh tham khảo]: {topic} (Chỉ dùng để hiểu đúng thuật ngữ. Bắt buộc dịch toàn bộ câu thoại, không bình luận về bối cảnh)."})
        if context_str:
            messages.append({"role": "system", "content": f"[Ngữ cảnh các câu trước đó]:\n{context_str}"})
        if glossary_section:
            messages.append({"role": "system", "content": glossary_section})

        messages.append({"role": "user", "content": f"Dịch sang {tgt_name}:\n{text}"})

        candidate_models = [self.model, "llama3.2:3b", "qwen2.5:3b", "qwen2.5:7b"]
        # Remove duplicates while preserving order
        seen = set()
        models_to_try = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

        for m_name in models_to_try:
            url = f"{self.host}/api/chat"
            payload = {
                "model": m_name,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_predict": 128,
                }
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    res = body.get("message", {}).get("content", "").strip()
                    res = _clean_llm_translation(res)
                    if res:
                        return res
            except Exception:
                continue

        return ""


# --------------------------------------------------------------------- demo

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Offline NLLB translation demo")
    parser.add_argument("--src", default="en")
    parser.add_argument("--tgt", default="vi")
    parser.add_argument("texts", nargs="*", default=[
        "Hello everyone, and welcome back to the channel.",
        "Machine learning models can now translate speech in real time, which is truly amazing.",
        "Thank you so much for watching, and see you in the next video.",
    ])
    args = parser.parse_args()

    t0 = time.perf_counter()
    print(f"Loading NLLB-200 ({NLLB_REPO}) ...")
    mt = NllbTranslator()
    print(f"Ready in {time.perf_counter() - t0:.1f}s.\n")

    for text in args.texts:
        t0 = time.perf_counter()
        out = mt.translate(text, args.src, args.tgt)
        ms = (time.perf_counter() - t0) * 1000
        print(f"[{args.src}] {text}")
        print(f"[{args.tgt}] {out}   ({ms:.0f} ms)\n")


if __name__ == "__main__":
    main()
