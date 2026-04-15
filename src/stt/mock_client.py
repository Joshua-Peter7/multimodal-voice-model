"""
stt/mock_client.py — Mock STT client for testing when Soniox isn't available.
Returns demo transcripts to verify the pipeline works end-to-end.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncGenerator

from src.logger import get_logger

log = get_logger(__name__)


@dataclass
class Transcript:
    text: str
    is_final: bool
    confidence: float
    latency_ms: float
    words: list[dict]


DEMO_PHRASES = [
    "Hello, how are you?",
    "This is a test of the speech recognition system.",
    "The quick brown fox jumps over the lazy dog.",
    "I am speaking in English for real-time translation.",
    "This message will be translated to multiple languages.",
    "Thank you for testing this application.",
]


class MockSTTClient:
    """
    Mock STT client that simulates Soniox by generating demo transcripts.
    Useful for testing the full pipeline without external dependencies.
    """

    def __init__(self) -> None:
        self._current_phrase_idx = 0

    async def transcribe_stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
    ) -> AsyncGenerator[Transcript, None]:
        """
        Consumes audio chunks and yields demo transcripts.
        """
        chunk_count = 0
        start_time = time.perf_counter()
        try:
            async for chunk in audio_chunks:
                chunk_count += 1
                
                # Every ~50 chunks (about 1.5 seconds at 16kHz/512-sample frames), emit a transcript
                if chunk_count % 50 == 0:
                    phrase = DEMO_PHRASES[self._current_phrase_idx % len(DEMO_PHRASES)]
                    self._current_phrase_idx += 1
                    
                    latency = (time.perf_counter() - start_time) * 1000
                    
                    async for partial in self._emit_partial_transcripts(phrase, latency):
                        yield partial
                    
                    # Emit final transcript
                    log.info("mock_stt_final", text=phrase[:50])
                    yield Transcript(
                        text=phrase,
                        is_final=True,
                        confidence=0.95,
                        latency_ms=latency,
                        words=[],
                    )
        except asyncio.CancelledError:
            log.info("mock_stt_cancelled")
        except Exception as e:
            log.error("mock_stt_error", error=str(e))

    async def _emit_partial_transcripts(self, text: str, base_latency: float) -> AsyncGenerator[Transcript, None]:
        """Emit partial transcripts for streaming effect."""
        words = text.split()
        for i in range(1, len(words)):
            partial_text = " ".join(words[:i])
            await asyncio.sleep(0.05)  # 50ms between partials
            yield Transcript(
                text=partial_text,
                is_final=False,
                confidence=0.85,
                latency_ms=base_latency + (i * 50),
                words=[],
            )

    async def close(self) -> None:
        log.info("mock_stt_client_closed")
