"""
pipeline/orchestrator.py - Ultra-low-latency streaming pipeline.

Architecture for low perceived latency:
1. Audio streams directly to Soniox (optionally bypassing VAD)
2. Partial transcripts can trigger speculative translation
3. Translations stream to ElevenLabs TTS
4. Audio chunks broadcast to listeners as they arrive

Key optimizations:
- Bypass VAD so Soniox handles endpointing natively
- Pipeline overlap so translation and TTS can begin on partials
- Request deduplication to avoid redundant work on overlapping partials
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Dict, Optional

from src.audio.ingestion import AudioIngestion
from src.audio.vad import VADProcessor
from src.config_loader import cfg
from src.logger import get_logger
from src.metrics import pipeline_errors_total, record_pipeline
from src.moderation.content_moderator import ContentModerator
from src.stt.soniox_client import SonioxSTTClient, Transcript
from src.streaming.channel_manager import ChannelManager
from src.translation.llm_translator import LLMTranslator
from src.tts.elevenlabs_client import ElevenLabsTTSClient

log = get_logger(__name__)

_MIN_PARTIAL_ADVANCE_CHARS = 12


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
    source_lang: Optional[str] = None


def _normalize_source_text(text: str) -> str:
    """Normalize Soniox transcript text before dedup and translation."""
    text = re.sub(r"<\w+>?", ". ", text).strip()
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class TranslationPipeline:
    """
    Full end-to-end streaming pipeline orchestrator.
    One instance per speaker WebSocket session.
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

    async def run(
        self,
        audio_source: AsyncGenerator[bytes, None],
        source_lang: Optional[str] = None,
    ) -> AsyncGenerator[Transcript, None]:
        """
        Main run loop. Consumes streaming audio and drives the entire pipeline.
        """
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)

        async def _audio_producer() -> None:
            async for chunk in audio_source:
                if cfg.audio.bypass_vad:
                    await self._audio_queue.put(chunk)
                else:
                    processed = self._ingestion.ingest(chunk)
                    for processed_chunk in processed:
                        await self._audio_queue.put(processed_chunk)
            await self._audio_queue.put(b"")

        producer_task = asyncio.create_task(_audio_producer())

        async def _queue_reader() -> AsyncGenerator[bytes, None]:
            while True:
                chunk = await self._audio_queue.get()
                if chunk == b"":
                    return
                yield chunk

        if cfg.audio.bypass_vad:
            async for transcript in self._run_stt_direct(_queue_reader(), source_lang):
                yield transcript
        else:
            async for transcript in self._run_stt_with_vad(_queue_reader(), source_lang):
                yield transcript

        producer_task.cancel()

    async def _run_stt_direct(
        self,
        audio_gen: AsyncGenerator[bytes, None],
        source_lang: Optional[str] = None,
    ) -> AsyncGenerator[Transcript, None]:
        """Stream audio directly to Soniox STT."""
        self._utterance_counter += 1
        ctx = UtteranceContext(utterance_id=f"utt-{self._utterance_counter}")
        ctx.source_lang = source_lang
        self._active_context = ctx

        async for transcript in self._stt.transcribe_stream(audio_gen, source_lang):
            await self._on_transcript(transcript, ctx)

            if transcript.is_final:
                self._utterance_counter += 1
                ctx = UtteranceContext(utterance_id=f"utt-{self._utterance_counter}")
                self._active_context = ctx

            yield transcript

    async def _run_stt_with_vad(
        self,
        audio_gen: AsyncGenerator[bytes, None],
        source_lang: Optional[str] = None,
    ) -> AsyncGenerator[Transcript, None]:
        """Run audio through VAD, then STT, then the translation pipeline."""

        async def _vad_output() -> AsyncGenerator[bytes, None]:
            async for utterance in self._vad.process_stream(audio_gen):
                yield utterance

        self._utterance_counter += 1
        ctx = UtteranceContext(utterance_id=f"utt-{self._utterance_counter}")
        ctx.source_lang = source_lang
        self._active_context = ctx

        async for transcript in self._stt.transcribe_stream(_vad_output(), source_lang):
            await self._on_transcript(transcript, ctx)
            yield transcript

    async def _on_transcript(self, transcript: Transcript, ctx: UtteranceContext) -> None:
        """
        Called for every partial/final transcript from Soniox.
        """
        if transcript.language_code:
            ctx.source_lang = transcript.language_code

        text = transcript.text.strip()
        if not text:
            return

        try:
            mod_result = self._moderator.screen(text)
            text = mod_result.text
        except ValueError:
            log.warning("source_content_blocked", utt=ctx.utterance_id)
            return

        text = _normalize_source_text(text)
        if not text:
            return

        if transcript.is_final:
            if ctx.speculative_task and not ctx.speculative_task.done():
                ctx.speculative_task.cancel()

            log.info(
                "final_transcript",
                text=text if cfg.logging.log_transcripts else "[REDACTED]",
                stt_latency_ms=round(transcript.latency_ms, 1),
            )
            self._stats.stt_latency_ms = transcript.latency_ms

            if self._cfg_p.final_confirm_delay_ms > 0:
                await asyncio.sleep(self._cfg_p.final_confirm_delay_ms / 1000)

            await self._translate_and_stream(text, ctx, is_final=True)
            ctx.final_processed = True
            return

        if not self._cfg_p.speculative_translation:
            return
        if len(text) < self._cfg_p.partial_min_chars:
            return
        if text == ctx.last_partial:
            return
        if (
            ctx.last_partial
            and text.startswith(ctx.last_partial)
            and (len(text) - len(ctx.last_partial)) < _MIN_PARTIAL_ADVANCE_CHARS
        ):
            log.debug(
                "speculative_skip_small_increment",
                utterance=ctx.utterance_id,
                prev_len=len(ctx.last_partial),
                new_len=len(text),
            )
            return

        ctx.last_partial = text
        if ctx.speculative_task and not ctx.speculative_task.done():
            ctx.speculative_task.cancel()
        ctx.speculative_task = asyncio.create_task(self._speculative_translate(text, ctx))

    async def _speculative_translate(self, text: str, ctx: UtteranceContext) -> None:
        """Translate a partial transcript speculatively."""
        log.info("speculative_task_trigger", text=text[:30])
        try:
            await asyncio.sleep(self._cfg_p.speculative_interval_ms / 1000)
            if ctx.final_processed:
                log.debug("speculative_task_skipped_final_exists")
                return
            await self._translate_and_stream(text, ctx, is_final=False)
        except asyncio.CancelledError:
            log.debug("speculative_task_cancelled", utterance=ctx.utterance_id)
            raise

    async def _translate_and_stream(
        self, text: str, ctx: UtteranceContext, is_final: bool
    ) -> None:
        """
        Core pipeline: text -> translation -> parallel TTS streaming -> broadcast.
        """
        pipeline_start = time.perf_counter()
        moderation_flag = False

        text = _normalize_source_text(text)
        if not text:
            return

        try:
            log.info("translation_starting", text_len=len(text), is_final=is_final)
            res = await self._translator.translate(text, source_lang=ctx.source_lang)
            translations = res.translations
            log.info("translation_received", count=len(translations), latency_ms=res.latency_ms)
            if cfg.moderation.moderate_translations:
                translations, moderation_flag = self._moderator.screen_translations(translations)
            if not is_final and translations == ctx.last_translated:
                log.debug("skip_duplicate_partial_translation", utterance=ctx.utterance_id)
                return
        except Exception as exc:
            pipeline_errors_total.labels(stage="translation").inc()
            log.error("translation_error", error=str(exc))
            return

        async def _process_language(lang) -> None:
            log.debug("language_pipeline_start", lang=lang.code, utterance=ctx.utterance_id)
            try:
                translated_text = translations.get(lang.code, "")
                if not translated_text:
                    return

                await self._channels.publish_translation_update(
                    lang_code=lang.code,
                    source_text=text,
                    translated_text=translated_text,
                    is_final=is_final,
                    pipeline_latency_ms=(time.perf_counter() - pipeline_start) * 1000,
                )

                chunk_counter = 0
                async for chunk in self._tts.stream_one_chunked(translated_text, lang):
                    if not chunk.audio_chunk:
                        continue

                    latency = (time.perf_counter() - pipeline_start) * 1000
                    if chunk_counter == 0:
                        self._stats.tts_first_chunk_ms = latency

                    await self._channels.publish_audio_chunk(
                        lang_code=chunk.lang_code,
                        audio_chunk=chunk.audio_chunk,
                        chunk_index=chunk_counter,
                        source_text=text,
                        translated_text=translated_text,
                        is_final=is_final,
                        pipeline_latency_ms=latency,
                        moderation_flag=moderation_flag,
                    )
                    chunk_counter += 1

                await self._channels.publish_stream_complete(
                    lang_code=lang.code,
                    source_text=text,
                    translated_text=translated_text,
                    is_final=is_final,
                    pipeline_latency_ms=(time.perf_counter() - pipeline_start) * 1000,
                    moderation_flag=moderation_flag,
                )
                log.debug("language_pipeline_complete", lang=lang.code, utterance=ctx.utterance_id)

            except Exception as exc:
                pipeline_errors_total.labels(stage="tts").inc()
                await self._channels.publish_error(
                    lang.code,
                    f"TTS unavailable for {lang.name}: {str(exc)}",
                )
                log.error("language_pipeline_error", lang=lang.code, error=str(exc))

        target_langs = cfg.enabled_languages
        if self._cfg_p.parallel_lang_processing:
            await asyncio.gather(*[_process_language(lang) for lang in target_langs])
        else:
            for lang in target_langs:
                await _process_language(lang)

        ctx.last_translated = dict(translations)

        total_latency = (time.perf_counter() - pipeline_start) * 1000
        if is_final:
            self._stats.total_utterances += 1
            self._stats.total_latency_ms += total_latency

        record_pipeline(
            total_ms=total_latency,
            stt_ms=self._stats.stt_latency_ms,
            translation_ms=0.0,
            tts_ms=self._stats.tts_first_chunk_ms,
            flagged=False,
        )

        log.info(
            "pipeline_complete",
            utterance_id=ctx.utterance_id,
            is_final=is_final,
            total_latency_ms=round(total_latency, 1),
            tts_first_chunk_ms=round(self._stats.tts_first_chunk_ms, 1),
        )

        if total_latency > self._cfg_p.target_latency_ms:
            log.warning(
                "latency_target_exceeded",
                target_ms=self._cfg_p.target_latency_ms,
                actual_ms=round(total_latency, 1),
                utterance=ctx.utterance_id,
            )

    async def close(self) -> None:
        """Clean up resources."""
        try:
            await self._stt.close()
        except Exception:
            pass
        try:
            await self._translator.close()
        except Exception:
            pass
        try:
            await self._tts.close()
        except Exception:
            pass

    @property
    def stats(self) -> PipelineStats:
        return self._stats
