"""
scripts/test_mic.py — Quick standalone test for local mic → STT → Translation.
Bypasses the WebSocket server and runs the pipeline directly from mic input.
Useful for validating API keys and latency before deploying the full server.

Usage:
  python scripts/test_mic.py
  python scripts/test_mic.py --duration 10   # record for 10 seconds
  python scripts/test_mic.py --lang hi,te    # only translate to Hindi + Telugu
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audio.ingestion import AudioIngestion
from src.audio.vad import VADProcessor
from src.config_loader import cfg
from src.moderation.content_moderator import ContentModerator
from src.stt.soniox_client import SonioxSTTClient
from src.translation.llm_translator import LLMTranslator
from src.tts.elevenlabs_client import ElevenLabsTTSClient


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Local mic test for translation pipeline")
    p.add_argument("--duration", type=int, default=30, help="Recording duration (seconds)")
    p.add_argument("--lang", type=str, default="", help="Comma-separated language codes, e.g. hi,te,ta")
    p.add_argument("--no-tts", action="store_true", help="Skip TTS generation (faster for testing translation only)")
    p.add_argument("--output-dir", type=str, default="./output_audio", help="Dir to save generated audio files")
    return p.parse_args()


async def run_test(args: argparse.Namespace) -> None:
    print("\n" + "=" * 60)
    print("  Real-Time Translation — Local Mic Test")
    print("=" * 60)

    # Resolve target languages
    if args.lang:
        target_codes = set(args.lang.split(","))
        target_langs = [l for l in cfg.enabled_languages if l.code in target_codes]
    else:
        target_langs = cfg.enabled_languages

    print(f"  Source: {cfg.source.language_name}")
    print(f"  Targets: {', '.join(l.name for l in target_langs)}")
    print(f"  TTS: {'disabled' if args.no_tts else 'enabled'}")
    print(f"  Duration: {args.duration}s")
    print("=" * 60 + "\n")

    ingestion = AudioIngestion()
    vad = VADProcessor()
    stt = SonioxSTTClient()
    translator = LLMTranslator()
    moderator = ContentModerator()
    tts = ElevenLabsTTSClient() if not args.no_tts else None

    # Output directory for audio files
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    utterance_count = 0
    latencies: list[float] = []

    async def _translate_and_tts(text: str, utt_id: int) -> None:
        nonlocal utterance_count
        t_start = time.perf_counter()

        print(f"\n[UTT-{utt_id}] Translating: \"{text}\"")

        # Moderation
        try:
            mod = moderator.screen(text)
            if mod.flagged:
                print(f"  ⚠ Content flagged ({mod.strategy_applied})")
            text_clean = mod.text
        except ValueError as e:
            print(f"  ✗ Content blocked: {e}")
            return

        # Translation
        t_trans = time.perf_counter()
        result = await translator.translate(text_clean, target_langs)
        trans_ms = (time.perf_counter() - t_trans) * 1000
        print(f"  Translation: {trans_ms:.0f}ms")

        for lang in target_langs:
            translated = result.translations.get(lang.code, "")
            print(f"    {lang.name:10s} [{lang.code}]: {translated}")

        # TTS
        if tts and result.translations:
            t_tts = time.perf_counter()
            tts_results = await tts.synthesize_all(result.translations, target_langs)
            tts_ms = (time.perf_counter() - t_tts) * 1000
            print(f"  TTS: {tts_ms:.0f}ms  ({len(tts_results)} languages)")

            for r in tts_results:
                fname = output_dir / f"utt{utt_id}_{r.lang_code}.mp3"
                fname.write_bytes(r.audio_bytes)
                print(f"    Saved: {fname} ({len(r.audio_bytes):,} bytes)")

        total_ms = (time.perf_counter() - t_start) * 1000
        latencies.append(total_ms)
        utterance_count += 1
        print(f"  ✓ Total pipeline: {total_ms:.0f}ms")

    print("🎙 Speak now... (Ctrl+C to stop)\n")

    utt_id = 0
    start_time = time.time()

    try:
        async for utterance in vad.process_stream(ingestion.stream_microphone()):
            if time.time() - start_time > args.duration:
                print(f"\nDuration limit reached ({args.duration}s)")
                break

            # Feed to STT
            async def _single_source(data: bytes):
                yield data

            async for transcript in stt.transcribe_stream(_single_source(utterance)):
                if transcript.is_final and transcript.text.strip():
                    utt_id += 1
                    await _translate_and_tts(transcript.text.strip(), utt_id)

    except KeyboardInterrupt:
        print("\n\nStopped by user.")
    finally:
        await stt.close()
        await translator.close()
        if tts:
            await tts.close()

    # Summary
    print("\n" + "=" * 60)
    print(f"  Utterances processed : {utterance_count}")
    if latencies:
        print(f"  Avg pipeline latency : {sum(latencies)/len(latencies):.0f}ms")
        print(f"  Min latency          : {min(latencies):.0f}ms")
        print(f"  Max latency          : {max(latencies):.0f}ms")
    if not args.no_tts:
        print(f"  Audio saved to       : {output_dir.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_test(args))
