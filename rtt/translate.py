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

import time
from typing import Protocol

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
