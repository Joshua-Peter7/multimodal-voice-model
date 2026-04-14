"""
tts/elevenlabs_client.py — ElevenLabs streaming TTS with WebSocket + HTTP fallback.

Uses the WebSocket stream-input endpoint for lowest possible latency:
- First audio chunk arrives in ~30ms (vs ~300ms with HTTP streaming)
- Audio chunks are yielded immediately as they arrive from ElevenLabs
- Parallel generation across all target languages
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Callable, Dict, List, Optional

import aiohttp

from src.config_loader import cfg, LanguageConfig
from src.logger import get_logger

log = get_logger(__name__)

_EL_BASE_URL = "https://api.elevenlabs.io/v1"


@dataclass
class TTSResult:
    lang_code: str
    lang_name: str
    audio_bytes: bytes
    latency_ms: float
    text: str


@dataclass
class TTSChunk:
    """A single chunk of streaming TTS audio."""
    lang_code: str
    lang_name: str
    audio_chunk: bytes
    chunk_index: int
    is_final: bool
    latency_ms: float  # Time since TTS request started


class ElevenLabsTTSClient:
    """
    Ultra-low-latency TTS client for ElevenLabs.
    Supports two modes:
    1. WebSocket streaming (default) — lowest latency, ~30ms first chunk
    2. HTTP streaming — fallback, ~300ms first chunk

    For real-time pipeline: use stream_one_chunked() to get audio chunks
    as they arrive and forward them immediately to listeners.
    """

    def __init__(self) -> None:
        self._cfg = cfg.apis.elevenlabs
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(cfg.pipeline.max_tts_concurrency)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=120,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={
                    "xi-api-key": self._cfg.api_key,
                    "Content-Type": "application/json",
                },
            )
        return self._session

    # ── WebSocket Streaming (Lowest Latency) ─────────────────────

    async def stream_one_ws(
        self,
        text: str,
        language: LanguageConfig,
        on_chunk: Optional[Callable[[TTSChunk], None]] = None,
    ) -> AsyncGenerator[TTSChunk, None]:
        """
        Stream audio via ElevenLabs WebSocket API.
        Yields TTSChunk objects as audio arrives (~30ms first chunk).
        Optionally calls on_chunk callback for each chunk.
        """
        ws_url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{language.voice_id}"
            f"/stream-input?model_id={self._cfg.model_id}"
            f"&output_format={self._cfg.output_format}"
            f"&optimize_streaming_latency={self._cfg.optimize_streaming_latency}"
        )

        start = time.perf_counter()
        chunk_index = 0
        session = await self._ensure_session()

        async with self._semaphore:
            try:
                async with session.ws_connect(
                    ws_url,
                    headers={"xi-api-key": self._cfg.api_key},
                    heartbeat=20,
                    max_msg_size=0,
                ) as ws:
                    # Send BOS (beginning of stream) message
                    bos_msg = {
                        "text": " ",
                        "voice_settings": {
                            "stability": language.stability,
                            "similarity_boost": language.similarity_boost,
                            "use_speaker_boost": True,
                        },
                        "xi_api_key": self._cfg.api_key,
                    }
                    await ws.send_str(json.dumps(bos_msg))

                    # Send the actual text
                    text_msg = {
                        "text": text,
                        "try_trigger_generation": True,
                        "flush": True,
                    }
                    await ws.send_str(json.dumps(text_msg))

                    # Send EOS (end of stream) to trigger final generation
                    eos_msg = {"text": ""}
                    await ws.send_str(json.dumps(eos_msg))

                    # Receive audio chunks
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)

                            if "audio" in data and data["audio"]:
                                import base64
                                audio_bytes = base64.b64decode(data["audio"])
                                latency = (time.perf_counter() - start) * 1000

                                chunk = TTSChunk(
                                    lang_code=language.code,
                                    lang_name=language.name,
                                    audio_chunk=audio_bytes,
                                    chunk_index=chunk_index,
                                    is_final=False,
                                    latency_ms=latency,
                                )

                                if chunk_index == 0:
                                    log.info(
                                        "tts_first_chunk_ws",
                                        lang=language.code,
                                        latency_ms=round(latency, 1),
                                    )

                                chunk_index += 1
                                if on_chunk:
                                    on_chunk(chunk)
                                yield chunk

                            if data.get("isFinal"):
                                break

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break

                # Yield final marker
                final_latency = (time.perf_counter() - start) * 1000
                yield TTSChunk(
                    lang_code=language.code,
                    lang_name=language.name,
                    audio_chunk=b"",
                    chunk_index=chunk_index,
                    is_final=True,
                    latency_ms=final_latency,
                )

                log.info(
                    "tts_ws_complete",
                    lang=language.code,
                    chunks=chunk_index,
                    total_latency_ms=round(final_latency, 1),
                )

            except Exception as exc:
                log.warning(
                    "tts_ws_error",
                    lang=language.code,
                    error=str(exc),
                    fallback="http",
                )
                # Fall back to HTTP streaming
                async for chunk in self.stream_one_http(text, language):
                    yield chunk

    # ── HTTP Streaming (Fallback) ────────────────────────────────

    async def stream_one_http(
        self,
        text: str,
        language: LanguageConfig,
    ) -> AsyncGenerator[TTSChunk, None]:
        """
        Stream audio via HTTP streaming endpoint.
        Higher latency than WebSocket (~300ms first chunk) but more reliable.
        """
        start = time.perf_counter()
        url = (
            f"{_EL_BASE_URL}/text-to-speech/{language.voice_id}/stream"
            f"?output_format={self._cfg.output_format}"
            f"&optimize_streaming_latency={self._cfg.optimize_streaming_latency}"
        )

        payload = {
            "text": text,
            "model_id": self._cfg.model_id,
            "voice_settings": {
                "stability": language.stability,
                "similarity_boost": language.similarity_boost,
                "use_speaker_boost": True,
            },
        }

        session = await self._ensure_session()
        chunk_index = 0

        async with self._semaphore:
            try:
                async with session.post(url, json=payload) as resp:
                    resp.raise_for_status()
                    async for audio_bytes in resp.content.iter_chunked(
                        self._cfg.stream_chunk_size
                    ):
                        if audio_bytes:
                            latency = (time.perf_counter() - start) * 1000
                            chunk = TTSChunk(
                                lang_code=language.code,
                                lang_name=language.name,
                                audio_chunk=audio_bytes,
                                chunk_index=chunk_index,
                                is_final=False,
                                latency_ms=latency,
                            )

                            if chunk_index == 0:
                                log.info(
                                    "tts_first_chunk_http",
                                    lang=language.code,
                                    latency_ms=round(latency, 1),
                                )

                            chunk_index += 1
                            yield chunk

            except Exception as exc:
                log.error("tts_http_error", lang=language.code, error=str(exc))

        # Final marker
        yield TTSChunk(
            lang_code=language.code,
            lang_name=language.name,
            audio_chunk=b"",
            chunk_index=chunk_index,
            is_final=True,
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    # ── High-level: stream for one language ──────────────────────

    async def stream_one_chunked(
        self,
        text: str,
        language: LanguageConfig,
    ) -> AsyncGenerator[TTSChunk, None]:
        """
        Auto-select best streaming method (WebSocket or HTTP).
        Yields TTSChunk objects as audio arrives.
        """
        if self._cfg.use_websocket:
            async for chunk in self.stream_one_ws(text, language):
                yield chunk
        else:
            async for chunk in self.stream_one_http(text, language):
                yield chunk

    # ── Batch: collect full audio for one language ───────────────

    async def _synthesize_one(
        self,
        text: str,
        language: LanguageConfig,
    ) -> TTSResult:
        """
        Synthesize speech for a single language.
        Returns TTSResult with complete audio bytes collected from stream.
        """
        start = time.perf_counter()
        audio_chunks: list[bytes] = []

        async for chunk in self.stream_one_chunked(text, language):
            if chunk.audio_chunk:
                audio_chunks.append(chunk.audio_chunk)

        audio = b"".join(audio_chunks)
        latency_ms = (time.perf_counter() - start) * 1000

        return TTSResult(
            lang_code=language.code,
            lang_name=language.name,
            audio_bytes=audio,
            latency_ms=latency_ms,
            text=text,
        )

    async def synthesize_all(
        self,
        translations: Dict[str, str],
        languages: Optional[List[LanguageConfig]] = None,
    ) -> List[TTSResult]:
        """
        Generate speech for all languages in PARALLEL.
        Returns list of TTSResult in the order of languages.
        """
        target_langs = languages or cfg.enabled_languages
        tasks = []

        for lang in target_langs:
            text = translations.get(lang.code, "")
            if not text:
                log.debug("tts_skip_empty", lang=lang.code)
                continue
            tasks.append(self._synthesize_one(text, lang))

        if not tasks:
            return []

        results: list[TTSResult] = await asyncio.gather(*tasks, return_exceptions=False)
        return [r for r in results if r.audio_bytes]

    # ── Streaming broadcast helper ───────────────────────────────

    async def stream_all_chunked(
        self,
        translations: Dict[str, str],
        chunk_callback: Callable,
        languages: Optional[List[LanguageConfig]] = None,
    ) -> None:
        """
        Stream TTS for ALL languages in parallel, calling chunk_callback
        for each audio chunk as it arrives from any language.
        This is the lowest-latency path for real-time broadcasting.
        """
        target_langs = languages or cfg.enabled_languages
        tasks = []

        for lang in target_langs:
            text = translations.get(lang.code, "")
            if not text:
                continue
            tasks.append(self._stream_with_callback(text, lang, chunk_callback))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _stream_with_callback(
        self,
        text: str,
        language: LanguageConfig,
        callback: Callable,
    ) -> None:
        """Stream one language and call the callback for each chunk."""
        try:
            async for chunk in self.stream_one_chunked(text, language):
                await callback(chunk)
        except Exception as exc:
            log.error("tts_stream_callback_error", lang=language.code, error=str(exc))

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
