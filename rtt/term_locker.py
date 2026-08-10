"""Smart Term Locker — protect technical terms across NLLB-200 translation.

Since NLLB-200 is a pure sequence-to-sequence model without system prompts,
we cannot inject domain instructions directly into the model. Instead, we
protect known technical terms *before* translation using unique placeholders
(``__T0__``, ``__T1__``, …), let the model translate the remaining text, then
restore the protected terms with their correct target forms afterward.

Three sources of protected terms (applied in priority order):
1. **User Glossary** — entries from ``settings.data.glossary.entries``.
   If ``target == "giữ nguyên"``, the original source term is preserved.
   Otherwise the target string is used as the replacement.
2. **Built-in Domain Terms** — ``rtt.domain_terms.DOMAIN_TERMS``, a curated
   dictionary of ~300+ technical terms across AI/ML, Software, Biology, etc.
3. **Auto-detect rules** — ALL_CAPS words, CamelCase proper nouns, and
   version/unit strings (``8GB``, ``v3.5``, ``4K``) are kept verbatim when
   ``auto_lock_caps`` / ``auto_lock_camel`` are enabled in glossary settings.

Usage
-----
::

    locker = TermLocker()
    locked_text, mapping = locker.lock(raw_text, glossary_entries,
                                        auto_caps=True, auto_camel=True)
    translated = nllb.translate(locked_text, src, tgt)
    final = locker.restore(translated, mapping)
"""

from __future__ import annotations

import re
from typing import Any


# Sentinel for "keep original English term"
_KEEP = "giữ nguyên"

# Placeholder pattern: __T0__, __T1__, ...
_PH_FMT = "__T{i}__"
_PH_PATTERN = re.compile(r"__T\d+__")

# Auto-detect patterns
# ALL_CAPS: 2+ uppercase letters/digits/hyphens, no lowercase (e.g. GPU, CI/CD, LLM)
_RE_ALL_CAPS = re.compile(r"\b([A-Z][A-Z0-9\-]{1,}(?:/[A-Z0-9\-]+)?)\b")
# CamelCase: starts uppercase, has at least one lowercase, at least one more uppercase
# e.g. OpenAI, ChatGPT, GitHub, DeepMind, YouTube
_RE_CAMEL = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z0-9]*)+(?:-\d+[a-z]?)?)\b")
# Version / unit strings: 8GB, v3.5, GPT-4o, 4K, 2x, 1080p, etc.
_RE_VERSION = re.compile(r"\b(\d+[A-Za-z]+|\bv\d[\d.]*[a-z]?|[A-Za-z]+-\d+[a-z0-9]*)\b")


class TermLocker:
    """Lock technical terms before NLLB translation and restore them after."""

    def __init__(self) -> None:
        # Load built-in domain terms (case-insensitive lookup dict)
        from rtt.domain_terms import DOMAIN_TERMS
        # Build a lowercase → (original_key, target) lookup
        self._domain: dict[str, tuple[str, str | None]] = {
            k.lower(): (k, v) for k, v in DOMAIN_TERMS.items()
        }
        # Pre-build sorted list of domain term lengths (longest first) so multi-word
        # terms like "fine-tuning" are matched before shorter sub-matches like "tuning".
        self._domain_sorted: list[str] = sorted(
            self._domain.keys(), key=len, reverse=True
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lock(
        self,
        text: str,
        glossary_entries: list[dict[str, Any]] | None = None,
        auto_caps: bool = True,
        auto_camel: bool = True,
    ) -> tuple[str, dict[str, str]]:
        """Replace protected terms with placeholders.

        Parameters
        ----------
        text:
            Raw source sentence from STT output.
        glossary_entries:
            User glossary from ``settings.data.glossary.entries``.
            Each entry is a dict with ``"source"`` and ``"target"`` keys.
        auto_caps:
            Whether to auto-lock ALL_CAPS words not already in glossary/domain.
        auto_camel:
            Whether to auto-lock CamelCase proper nouns.

        Returns
        -------
        (locked_text, mapping)
            ``locked_text`` is the text with protected regions replaced by
            ``__T0__``, ``__T1__``, … placeholders.
            ``mapping`` maps each placeholder back to the correct output string.
        """
        glossary_entries = glossary_entries or []

        # We build a list of (start, end, replacement_str) spans to swap.
        # We then replace them in reverse order (right-to-left) to preserve offsets.
        replacements: list[tuple[int, int, str]] = []
        already_locked: set[tuple[int, int]] = set()  # track locked spans

        counter = [0]  # mutable int via list for nested fn

        def _add(start: int, end: int, target: str) -> None:
            """Register a span + its output string."""
            # Skip if already locked by a higher-priority rule
            for s, e in already_locked:
                if not (end <= s or start >= e):
                    return
            ph = _PH_FMT.format(i=counter[0])
            counter[0] += 1
            replacements.append((start, end, ph))
            already_locked.add((start, end))
            mapping[ph] = target

        mapping: dict[str, str] = {}

        # ── Priority 1: User Glossary ──────────────────────────────────────
        for entry in glossary_entries:
            src_term: str = entry.get("source", "").strip()
            tgt_term: str = entry.get("target", "").strip()
            if not src_term:
                continue
            # Determine what to restore after translation
            keep_original = tgt_term.lower() == _KEEP.lower()
            restore_as = src_term if keep_original else tgt_term

            pattern = re.compile(
                r"(?<!\w)" + re.escape(src_term) + r"(?!\w)",
                re.IGNORECASE,
            )
            for m in pattern.finditer(text):
                # If keep original, preserve the exact casing from source text
                actual_restore = m.group(0) if keep_original else restore_as
                _add(m.start(), m.end(), actual_restore)

        # ── Priority 2: Built-in Domain Terms ─────────────────────────────
        for term_lower in self._domain_sorted:
            original_key, domain_target = self._domain[term_lower]
            pattern = re.compile(
                r"(?<!\w)" + re.escape(term_lower) + r"(?!\w)",
                re.IGNORECASE,
            )
            for m in pattern.finditer(text):
                # Restore as: domain_target string if set, else preserve original casing
                restore_as = domain_target if domain_target is not None else m.group(0)
                _add(m.start(), m.end(), restore_as)

        # ── Priority 3a: Auto-lock ALL_CAPS ───────────────────────────────
        if auto_caps:
            for m in _RE_ALL_CAPS.finditer(text):
                word = m.group(1)
                # Skip short acronyms that are common English words (I, A, etc.)
                if len(word) < 2:
                    continue
                # Skip if it's a domain term we already handled
                if word.lower() in self._domain:
                    continue
                _add(m.start(), m.end(), word)

        # ── Priority 3b: Auto-lock CamelCase ──────────────────────────────
        if auto_camel:
            for m in _RE_CAMEL.finditer(text):
                word = m.group(1)
                if word.lower() in self._domain:
                    continue
                _add(m.start(), m.end(), word)

        # ── Priority 3c: Auto-lock version/unit strings ────────────────────
        for m in _RE_VERSION.finditer(text):
            word = m.group(0)
            if word.lower() in self._domain:
                continue
            _add(m.start(), m.end(), word)

        # ── Apply replacements right-to-left ──────────────────────────────
        locked_text = _apply_replacements(text, replacements)
        return locked_text, mapping

    def restore(self, translated: str, mapping: dict[str, str]) -> str:
        """Replace ``__Tx__`` placeholders in translated text with their targets.

        Also handles cases where NLLB may have added spaces inside or around
        the placeholder tokens (e.g. ``__ T0 __``).
        """
        if not mapping:
            return translated

        # NLLB sometimes splits the placeholder into sub-tokens; normalise first.
        text = _normalise_placeholders(translated)

        def _replace(m: re.Match) -> str:
            ph = m.group(0)
            return mapping.get(ph, ph)  # fall back to placeholder if not found

        return _PH_PATTERN.sub(_replace, text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_replacements(
    text: str, replacements: list[tuple[int, int, str]]
) -> str:
    """Apply (start, end, replacement) spans in right-to-left order."""
    # Sort by start position descending
    replacements.sort(key=lambda x: x[0], reverse=True)
    result = text
    for start, end, ph in replacements:
        result = result[:start] + ph + result[end:]
    return result


def _normalise_placeholders(text: str) -> str:
    """Fix common NLLB tokenization artifacts inside placeholder tokens.

    NLLB's SentencePiece tokenizer may insert spaces, making
    ``__T0__`` appear as ``__ T 0 __`` in the decoded output.
    We fix these by collapsing spaces between ``__`` markers.
    """
    # Match __T<digits>__ with optional whitespace noise between characters
    noise = re.compile(r"_\s*_\s*T\s*(\d+)\s*_\s*_")
    return noise.sub(lambda m: f"__T{m.group(1)}__", text)
