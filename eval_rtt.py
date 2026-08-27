"""Evaluation Benchmark for Real-Time Translator (RTT).

Evaluates:
1. Translation Quality: BLEU, ChrF++, TER
2. Inference Latency: Mean, Median (P50), P95, Max (in ms)
3. Term Locking Accuracy: Preservation rate of technical terms (GPU, LLM, CUDA, etc.)
4. Beam Search Comparison: Low-Latency (beam=1) vs High-Accuracy (beam=4)

Usage:
    uv run --with sacrebleu python eval_rtt.py
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

try:
    import sacrebleu
except ImportError:
    print("[!] sacrebleu is required. Run with: uv run --with sacrebleu python eval_rtt.py")
    sys.exit(1)

from rtt.translate import NllbTranslator
from rtt.term_locker import TermLocker


# ─── Benchmark Dataset (English -> Vietnamese) ──────────────────────────────
DATASET = [
    {
        "domain": "Conversational",
        "src": "Hello everyone, and welcome back to the channel.",
        "ref": "Xin chào mọi người, và chào mừng quay lại kênh.",
        "terms": [],
    },
    {
        "domain": "Conversational",
        "src": "Thank you so much for watching, and see you in the next video.",
        "ref": "Cảm ơn bạn rất nhiều vì đã xem, và hẹn gặp lại trong video tiếp theo.",
        "terms": [],
    },
    {
        "domain": "Tech / AI",
        "src": "Machine learning models can now translate speech in real time, which is truly amazing.",
        "ref": "Các mô hình học máy giờ đây có thể dịch giọng nói theo thời gian thực, điều này thật tuyệt vời.",
        "terms": [],
    },
    {
        "domain": "Tech / AI",
        "src": "We run NLLB-200 with CTranslate2 and CUDA acceleration for minimum latency.",
        "ref": "Chúng tôi chạy NLLB-200 với CTranslate2 và tăng tốc CUDA để đạt độ trễ tối thiểu.",
        "terms": ["NLLB-200", "CTranslate2", "CUDA"],
    },
    {
        "domain": "Tech / Hardware",
        "src": "The NVIDIA GPU accelerates inference by nearly 20 times compared to CPU.",
        "ref": "GPU NVIDIA tăng tốc suy luận gấp gần 20 lần so với CPU.",
        "terms": ["NVIDIA", "GPU", "CPU"],
    },
    {
        "domain": "Daily / Meeting",
        "src": "Can everyone hear me clearly on Zoom?",
        "ref": "Mọi người có nghe tôi rõ trên Zoom không?",
        "terms": ["Zoom"],
    },
    {
        "domain": "Daily / Meeting",
        "src": "Let me share my screen to show the presentation slides.",
        "ref": "Để tôi chia sẻ màn hình để chiếu các trang trình bày.",
        "terms": [],
    },
]


@dataclass
class EvalResult:
    beam: int
    bleu: float
    chrf: float
    ter: float
    avg_latency_ms: float
    p95_latency_ms: float
    term_accuracy: float
    translations: list[dict]


def evaluate_beam_setting(translator: NllbTranslator, beam: int) -> EvalResult:
    hypotheses = []
    references = [[item["ref"] for item in DATASET]]
    latencies_ms = []
    translations = []
    
    total_terms_expected = 0
    total_terms_preserved = 0

    for item in DATASET:
        src = item["src"]
        ref = item["ref"]
        terms = item["terms"]

        t0 = time.perf_counter()
        out = translator.translate(src, src="en", tgt="vi", beam=beam)
        latency = (time.perf_counter() - t0) * 1000.0

        latencies_ms.append(latency)
        hypotheses.append(out)
        translations.append({"src": src, "ref": ref, "hyp": out, "ms": latency})

        # Term preservation check
        for term in terms:
            total_terms_expected += 1
            if term.lower() in out.lower():
                total_terms_preserved += 1

    # Quality Metrics
    bleu_res = sacrebleu.corpus_bleu(hypotheses, references)
    chrf_res = sacrebleu.corpus_chrf(hypotheses, references, word_order=2)
    ter_res = sacrebleu.corpus_ter(hypotheses, references)

    latencies_sorted = sorted(latencies_ms)
    p95_idx = int(len(latencies_sorted) * 0.95)
    
    term_acc = (total_terms_preserved / total_terms_expected * 100.0) if total_terms_expected > 0 else 100.0

    return EvalResult(
        beam=beam,
        bleu=bleu_res.score,
        chrf=chrf_res.score,
        ter=ter_res.score,
        avg_latency_ms=sum(latencies_ms) / len(latencies_ms),
        p95_latency_ms=latencies_sorted[p95_idx],
        term_accuracy=term_acc,
        translations=translations,
    )


def test_term_locker_standalone():
    print("\n" + "=" * 65)
    print("  TEST 1: TERM LOCKER PRESERVATION TEST")
    print("=" * 65)
    locker = TermLocker()
    sample_text = "Deploying LLM on NVIDIA GPU using PyTorch and CUDA API."
    locked, mapping = locker.lock(sample_text, auto_caps=True, auto_camel=True)
    print(f"Original: {sample_text}")
    print(f"Locked:   {locked}")
    print(f"Mapping:  {mapping}")
    restored = locker.restore(locked, mapping)
    print(f"Restored: {restored}")
    success = (restored == sample_text)
    print(f"Result:   {'[PASS]' if success else '[FAIL]'}")
    return success


def main():
    print("=" * 65)
    print("  EVALUATING REAL-TIME TRANSLATOR (RTT)")
    print("=" * 65)
    
    # 1. Term Locker Test
    test_term_locker_standalone()

    # 2. MT Loading
    print("\nLoading NLLB-200 model...")
    t0 = time.perf_counter()
    from rtt.translate import NLLB_REPO
    try:
        translator = NllbTranslator(model_repo=NLLB_REPO, device="cuda")
        # Test 1 sample translation to ensure CUDA DLLs work
        translator.translate("Test", "en", "vi")
    except Exception as e:
        print(f"[!] CUDA initialization/DLL load issue ({e}). Falling back to CPU...")
        translator = NllbTranslator(model_repo=NLLB_REPO, device="cpu")

    load_time = time.perf_counter() - t0
    print(f"Model loaded in {load_time:.2f}s on device: {translator.device.upper()}\n")

    # 3. Evaluate Beam 1 (Low Latency / Live Preview)
    print("Evaluating Beam=1 (Live Preview Mode)...")
    res_b1 = evaluate_beam_setting(translator, beam=1)

    # 4. Evaluate Beam 4 (High Accuracy / Sentence Commit)
    print("Evaluating Beam=4 (Committed Sentence Mode)...")
    res_b4 = evaluate_beam_setting(translator, beam=4)

    # 5. Output Summary Table
    print("\n" + "=" * 65)
    print("  BENCHMARK SUMMARY RESULTS")
    print("=" * 65)
    print(f"{'Metric':<25} | {'Beam 1 (Live Preview)':<20} | {'Beam 4 (Committed)':<20}")
    print("-" * 70)
    print(f"{'BLEU ↑ (Quality)':<25} | {res_b1.bleu:<20.2f} | {res_b4.bleu:<20.2f}")
    print(f"{'ChrF++ ↑ (Vietnamese)':<25} | {res_b1.chrf:<20.2f} | {res_b4.chrf:<20.2f}")
    print(f"{'TER ↓ (Edit Rate)':<25} | {res_b1.ter:<20.2f} | {res_b4.ter:<20.2f}")
    print(f"{'Avg Latency (ms)':<25} | {res_b1.avg_latency_ms:<20.1f} | {res_b4.avg_latency_ms:<20.1f}")
    print(f"{'P95 Latency (ms)':<25} | {res_b1.p95_latency_ms:<20.1f} | {res_b4.p95_latency_ms:<20.1f}")
    print(f"{'Term Locking Acc (%)':<25} | {res_b1.term_accuracy:<20.1f}% | {res_b4.term_accuracy:<20.1f}%")
    print("=" * 65)

    print("\nSample Translations (Beam=4):")
    for i, item in enumerate(res_b4.translations, 1):
        print(f"\n[{i}] Source: {item['src']}")
        print(f"    Ref:    {item['ref']}")
        print(f"    NLLB:   {item['hyp']} ({item['ms']:.0f} ms)")


if __name__ == "__main__":
    main()
