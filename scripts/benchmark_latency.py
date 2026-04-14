"""
scripts/benchmark_latency.py — Measures per-stage latency using pre-recorded audio.
Generates a latency report showing where time is spent in the pipeline.

Usage:
  python scripts/benchmark_latency.py --audio path/to/sample.wav --rounds 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import cfg
from src.stt.soniox_client import SonioxSTTClient
from src.translation.llm_translator import LLMTranslator
from src.tts.elevenlabs_client import ElevenLabsTTSClient


def load_wav(path: str) -> tuple[bytes, int]:
    """Load a WAV file and return (pcm_bytes, sample_rate)."""
    with wave.open(path, "rb") as wf:
        n_frames = wf.getnframes()
        pcm = wf.readframes(n_frames)
        rate = wf.getframerate()
        return pcm, rate


async def benchmark_stt(pcm: bytes, rounds: int) -> list[float]:
    """Benchmark Soniox STT latency."""
    client = SonioxSTTClient()
    latencies = []

    for i in range(rounds):
        t0 = time.perf_counter()
        chunk_size = cfg.audio.sample_rate * 2 // 10  # 100ms chunks

        async def _audio_gen():
            for start in range(0, len(pcm), chunk_size):
                yield pcm[start : start + chunk_size]
                await asyncio.sleep(0)

        final_text = ""
        async for t in client.transcribe_stream(_audio_gen()):
            if t.is_final:
                final_text = t.text
                break

        elapsed = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed)
        print(f"  STT round {i+1}: {elapsed:.0f}ms  → \"{final_text[:50]}\"")

    await client.close()
    return latencies


async def benchmark_translation(text: str, rounds: int) -> list[float]:
    """Benchmark LLM translation latency."""
    translator = LLMTranslator()
    latencies = []

    for i in range(rounds):
        t0 = time.perf_counter()
        result = await translator.translate(text)
        elapsed = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed)
        lang_count = len([v for v in result.translations.values() if v])
        print(f"  LLM round {i+1}: {elapsed:.0f}ms  → {lang_count} languages")

    await translator.close()
    return latencies


async def benchmark_tts(translations: dict, rounds: int) -> list[float]:
    """Benchmark ElevenLabs TTS latency (parallel synthesis)."""
    client = ElevenLabsTTSClient()
    latencies = []

    for i in range(rounds):
        t0 = time.perf_counter()
        results = await client.synthesize_all(translations)
        elapsed = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed)
        total_bytes = sum(len(r.audio_bytes) for r in results)
        print(f"  TTS round {i+1}: {elapsed:.0f}ms  → {len(results)} tracks, {total_bytes:,} bytes")

    await client.close()
    return latencies


def print_stats(label: str, values: list[float]) -> None:
    if not values:
        return
    print(f"\n  {label}:")
    print(f"    Mean  : {statistics.mean(values):.0f} ms")
    print(f"    Median: {statistics.median(values):.0f} ms")
    print(f"    Stdev : {statistics.stdev(values) if len(values) > 1 else 0:.0f} ms")
    print(f"    Min   : {min(values):.0f} ms")
    print(f"    Max   : {max(values):.0f} ms")


async def run(args: argparse.Namespace) -> None:
    print("\n" + "=" * 60)
    print("  Pipeline Latency Benchmark")
    print("=" * 60)
    print(f"  Rounds per stage : {args.rounds}")
    print(f"  Languages        : {', '.join(l.code for l in cfg.enabled_languages)}")
    print("=" * 60 + "\n")

    # ── STT ─────────────────────────────────────────────────
    stt_latencies: list[float] = []
    stt_text = args.text or "Hello, this is a benchmark test of the translation system."

    if args.audio:
        print("[ STT Benchmark ]")
        pcm, rate = load_wav(args.audio)
        stt_latencies = await benchmark_stt(pcm, args.rounds)
    else:
        print("[ STT Benchmark ] Skipped (no --audio provided)")

    # ── Translation ──────────────────────────────────────────
    print("\n[ Translation Benchmark ]")
    trans_latencies = await benchmark_translation(stt_text, args.rounds)

    # Use last translation result for TTS benchmark
    translator = LLMTranslator()
    last_result = await translator.translate(stt_text)
    await translator.close()

    # ── TTS ──────────────────────────────────────────────────
    print("\n[ TTS Benchmark (parallel) ]")
    tts_latencies = await benchmark_tts(last_result.translations, args.rounds)

    # ── Report ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)

    if stt_latencies:
        print_stats("Soniox STT", stt_latencies)
    print_stats("LLM Translation (Llama)", trans_latencies)
    print_stats("ElevenLabs TTS (parallel)", tts_latencies)

    # Combined estimate
    combined = []
    for t, l in zip(trans_latencies, tts_latencies):
        combined.append(t + l)
    if stt_latencies:
        for i in range(min(len(combined), len(stt_latencies))):
            combined[i] += stt_latencies[i]

    print_stats("Estimated End-to-End", combined)
    print(f"\n  Target: {cfg.pipeline.target_latency_ms}ms")
    if combined:
        avg = statistics.mean(combined)
        gap = avg - cfg.pipeline.target_latency_ms
        if gap > 0:
            print(f"  ⚠ Average exceeds target by {gap:.0f}ms")
            print(f"    → Consider: dedicated HF Inference Endpoint, ElevenLabs turbo model,")
            print(f"                speculative translation enabled in config.yaml")
        else:
            print(f"  ✓ Target met!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline latency benchmark")
    parser.add_argument("--audio", type=str, default="", help="Path to WAV file for STT benchmark")
    parser.add_argument("--text", type=str, default="", help="Text to use for translation/TTS benchmark")
    parser.add_argument("--rounds", type=int, default=3, help="Benchmark rounds per stage")
    asyncio.run(run(parser.parse_args()))
