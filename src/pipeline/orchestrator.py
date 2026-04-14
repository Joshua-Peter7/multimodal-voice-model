"""
pipeline/orchestrator.py — Ultra-low-latency streaming pipeline.

Architecture for ~60ms perceived latency:
1. Audio streams directly to Soniox (bypass VAD)
2. Partial transcripts trigger speculative translation via Groq (~40ms)
3. Translations stream to ElevenLabs WebSocket TTS (~30ms first chunk)
4. Audio chunks broadcast to listeners as they arrive

Key optimizations:
- Bypass VAD → Soniox handles endpointing natively
- Groq API → 30-60ms vs 2-15s on HuggingFace
- ElevenLabs WebSocket → 30ms first chunk vs 300ms HTTP
- Pipeline overlap → translation + TTS start on partial transcripts
- Request deduplication → avoid redundant API calls on overlapping partials
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Dict, Optional

from src.audio.ingestion import AudioIngestion
from src.audio.vad import VADProcessor
from src.config_loader import cfg
from src.logger import get_logger
from src.moderation.content_moderator import ContentModerator
from src.stt.soniox_client import SonioxSTTClient, Transcript
from src.streaming.channel_manager import ChannelManager
from src.translation.llm_translator import LLMTranslator, TranslationResult
from src.tts.elevenlabs_client import ElevenLabsTTSClient, TTSChunk

log = get_logger(__name__)


@dataclass
class PipelineStats:
    total_utterances: int = 0
    total_latency_ms: float = 0.0
    stt_latency_ms: float = 0.0
    translation_latency_ms: float = 0.0
    tts_latency_ms: float = 0.0
    tts_first_chunk_ms: float = 0.0
    moderation_flags: int = 0
    errors: int = 0
    speculative_hits: int = 0

    @property
    def avg_latency_ms(self) -> float:
        if self.total_utterances == 0:
            return 0.0
        return self.total_latency_ms / self.total_utterances


@dataclass
class UtteranceContext:
    """Tracks state for one utterance through the pipeline."""
    utterance_id: str
    started_at: float = field(default_factory=time.perf_counter)
    last_partial: str = ""
    last_translated: Dict[str, str] = field(default_factory=dict)
    speculative_task: Optional[asyncio.Task] = None
    final_processed: bool = False


class TranslationPipeline:
    """
    Full end-to-end streaming pipeline orchestrator.
    One instance per speaker WebSocket session.

    Pipeline flow:
      Audio → [optional VAD] → Soniox STT → Groq Translation → ElevenLabs TTS → Broadcast
                                     ↓ (partials)
                               Speculative Translation → Pre-warm TTS
    """

    def __init__(self, channel_manager: ChannelManager) -> None:
        self._cfg_p = cfg.pipeline
        self._ingestion = AudioIngestion()
        self._vad = VADProcessor()
        self._stt = SonioxSTTClient()
        self._translator = LLMTranslator()
        self._moderator = ContentModerator()
        self._tts = ElevenLabsTTSClient()
        self._channels = channel_manager
        self._stats = PipelineStats()
        self._utterance_counter = 0
        self._active_context: Optional[UtteranceContext] = None

    # ── Public API ──────────────────────────────────────────────

    async def run(self, audio_source: AsyncGenerator[bytes, None]) -> None:
        """
        Main run loop — consumes streaming audio and drives the entire pipeline.
        Call this as a background task for each speaker session.
        """
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)

        async def _audio_producer() -> None:
            async for chunk in audio_source:
                if cfg.audio.bypass_vad:
                    # Direct pass-through — no noise suppression, no chunking
                    # Minimizes latency by streaming raw audio to STT
                    await self._audio_queue.put(chunk)
                else:
                    # Process through ingestion (noise suppression + chunking)
                    processed = self._ingestion.ingest(chunk)
                    for c in processed:
                        await self._audio_queue.put(c)
            # Signal end
            await self._audio_queue.put(b"")

        producer_task = asyncio.create_task(_audio_producer())

        async def _queue_reader() -> AsyncGenerator[bytes, None]:
            while True:
                chunk = await self._audio_queue.get()
                if chunk == b"":
                    return
                yield chunk

        if cfg.audio.bypass_vad:
            # Stream directly to STT — Soniox handles endpointing
            await self._run_stt_direct(_queue_reader())
        else:
            # Run VAD on the queue stream, then STT on VAD output
            await self._run_stt_with_vad(_queue_reader())

        producer_task.cancel()

    async def _run_stt_direct(
        self, audio_gen: AsyncGenerator[bytes, None]
    ) -> None:
        """Stream audio directly to Soniox STT (bypass VAD for lowest latency)."""
        self._utterance_counter += 1
        ctx = UtteranceContext(utterance_id=f"utt-{self._utterance_counter}")
        self._active_context = ctx

        async for transcript in self._stt.transcribe_stream(audio_gen):
            await self._on_transcript(transcript, ctx)

            # Start new context on final transcript (new utterance)
            if transcript.is_final:
                self._utterance_counter += 1
                ctx = UtteranceContext(utterance_id=f"utt-{self._utterance_counter}")
                self._active_context = ctx

    async def _run_stt_with_vad(
        self, audio_gen: AsyncGenerator[bytes, None]
    ) -> None:
        """Run audio through VAD → Soniox STT → translation pipeline."""

        async def _vad_output() -> AsyncGenerator[bytes, None]:
            async for utterance in self._vad.process_stream(audio_gen):
                yield utterance

        self._utterance_counter += 1
        ctx = UtteranceContext(utterance_id=f"utt-{self._utterance_counter}")
        self._active_context = ctx

        async for transcript in self._stt.transcribe_stream(_vad_output()):
            await self._on_transcript(transcript, ctx)

    async def _on_transcript(
        self, transcript: Transcript, ctx: UtteranceContext
    ) -> None:
        """
        Called for every partial/final transcript from Soniox.
        Implements aggressive speculative translation on partials.
        """
        text = transcript.text.strip()
        if not text:
            return

        # Screen source text
        try:
            mod_result = self._moderator.screen(text)
            text = mod_result.text
        except ValueError:
            log.warning("source_content_blocked", utt=ctx.utterance_id)
            return

        if transcript.is_final:
            # Cancel any pending speculative task
            if ctx.speculative_task and not ctx.speculative_task.done():
                ctx.speculative_task.cancel()

            log.info(
                "final_transcript",
                text=text,
                stt_latency_ms=round(transcript.latency_ms, 1),
            )
            self._stats.stt_latency_ms = transcript.latency_ms

            # Process final transcript with streaming TTS
            await self._translate_and_stream(text, ctx, is_final=True)
            ctx.final_processed = True

        elif self._cfg_p.speculative_translation:
            # Speculative translation on partials — more aggressive thresholds
            if (
                len(text) >= self._cfg_p.partial_min_chars
                and text != ctx.last_partial
            ):
                ctx.last_partial = text
                # Cancel previous speculative task
                if ctx.speculative_task and not ctx.speculative_task.done():
                    ctx.speculative_task.cancel()
                ctx.speculative_task = asyncio.create_task(
                    self._speculative_translate(text, ctx)
                )

    async def _speculative_translate(
        self, text: str, ctx: UtteranceContext
    ) -> None:
        """
        Translate a partial transcript speculatively.
        Shorter delay than before since Groq is fast enough to handle
        more frequent speculative calls.
        """
        await asyncio.sleep(self._cfg_p.speculative_interval_ms / 1000)
        if ctx.final_processed:
            return  # Final already handled, skip stale speculative
        log.debug("speculative_translate", text=text[:50])
        await self._translate_and_stream(text, ctx, is_final=False)

    async def _translate_and_stream(
        self, text: str, ctx: UtteranceContext, is_final: bool
    ) -> None:
        """
        Core pipeline: text → Groq translation → moderation → streaming TTS → broadcast.

        For streaming mode:
        1. Translate all languages at once via Groq (~40ms)
        2. Start TTS for ALL languages in parallel
        3. As each audio chunk arrives, broadcast it immediately to listeners
        """
        pipeline_start = time.perf_counter()

        # ── 1. Groq Translation (~30-60ms) ──────────────────────
        t0 = time.perf_counter()
        try:
            result: TranslationResult = await self._translator.translate(text)
        except Exception as exc:
            log.error("translation_failed", error=str(exc))
            self._stats.errors += 1
            return
        translation_latency = (time.perf_counter() - t0) * 1000
        self._stats.translation_latency_ms = translation_latency

        # ── 2. Content Moderation (translations) ────────────────
        translations, moderation_flag = self._moderator.screen_translations(
            result.translations
        )
        if moderation_flag:
            self._stats.moderation_flags += 1

        ctx.last_translated = translations

        # ── 3. Streaming TTS + Real-time Broadcast ──────────────
        t1 = time.perf_counter()

        if self._cfg_p.stream_tts_chunks:
            # STREAMING MODE: broadcast audio chunks as they arrive
            await self._stream_tts_to_listeners(
                translations=translations,
                source_text=text,
                is_final=is_final,
                moderation_flag=moderation_flag,
                pipeline_start=pipeline_start,
            )
        else:
            # BATCH MODE: collect full audio, then broadcast (higher latency)
            try:
                tts_results = await self._tts.synthesize_all(translations)
            except Exception as exc:
                log.error("tts_failed", error=str(exc))
                self._stats.errors += 1
                return

            await self._channels.publish_results(
                source_text=text,
                tts_results=tts_results,
                is_final=is_final,
                moderation_flag=moderation_flag,
                translated_texts=translations,
                pipeline_latency_ms=(time.perf_counter() - pipeline_start) * 1000,
            )

        self._stats.tts_latency_ms = (time.perf_counter() - t1) * 1000

        # ── 4. Update Stats ──────────────────────────────────────
        total_latency = (time.perf_counter() - pipeline_start) * 1000

        if is_final:
            self._stats.total_utterances += 1
            self._stats.total_latency_ms += total_latency

        log.info(
            "pipeline_complete",
            utterance_id=ctx.utterance_id,
            is_final=is_final,
            total_latency_ms=round(total_latency, 1),
            translation_latency_ms=round(translation_latency, 1),
            tts_latency_ms=round(self._stats.tts_latency_ms, 1),
            moderation_flag=moderation_flag,
        )

    async def _stream_tts_to_listeners(
        self,
        translations: Dict[str, str],
        source_text: str,
        is_final: bool,
        moderation_flag: bool,
        pipeline_start: float,
    ) -> None:
        """
        Stream TTS audio chunks to listeners in real-time.
        Each language streams independently and in parallel.
        Audio chunks are broadcast the moment they arrive from ElevenLabs.
        """

        async def _on_tts_chunk(chunk: TTSChunk) -> None:
            """Called for each audio chunk from any language — broadcast immediately."""
            if chunk.is_final or not chunk.audio_chunk:
                return

            latency = (time.perf_counter() - pipeline_start) * 1000

            if chunk.chunk_index == 0:
                self._stats.tts_first_chunk_ms = latency
                log.info(
                    "first_audio_to_listener",
                    lang=chunk.lang_code,
                    pipeline_latency_ms=round(latency, 1),
                )

            await self._channels.publish_audio_chunk(
                lang_code=chunk.lang_code,
                audio_chunk=chunk.audio_chunk,
                chunk_index=chunk.chunk_index,
                source_text=source_text,
                translated_text=translations.get(chunk.lang_code, ""),
                is_final=is_final and chunk.is_final,
                pipeline_latency_ms=latency,
                moderation_flag=moderation_flag,
            )

        # Stream all languages in parallel
        await self._tts.stream_all_chunked(
            translations=translations,
            chunk_callback=_on_tts_chunk,
        )

        # Send a final "complete" message to all languages
        total_latency = (time.perf_counter() - pipeline_start) * 1000
        for lang_code, translated_text in translations.items():
            if translated_text:
                await self._channels.publish_stream_complete(
                    lang_code=lang_code,
                    source_text=source_text,
                    translated_text=translated_text,
                    is_final=is_final,
                    pipeline_latency_ms=total_latency,
                    moderation_flag=moderation_flag,
                )

    async def close(self) -> None:
        await self._stt.close()
        await self._translator.close()
        await self._tts.close()

    @property
    def stats(self) -> PipelineStats:
        return self._stats
