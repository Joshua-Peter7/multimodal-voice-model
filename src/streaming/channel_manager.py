"""
streaming/channel_manager.py — Real-time audio chunk streaming channel manager.

Supports two broadcast modes:
1. Chunk streaming (low latency) — individual audio chunks sent as they arrive
2. Batch publishing (higher latency) — complete audio sent after TTS finishes

Each language gets its own channel. Listeners subscribe to their preferred language.
WebSocket connections are tracked per channel.
Redis pub/sub is optional for horizontal scaling.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Dict, Optional, Set

from src.redis_client import get_redis
from fastapi import WebSocket

from src.config_loader import cfg
from src.logger import get_logger
from src.metrics import active_listeners

log = get_logger(__name__)


@dataclass
class BroadcastPayload:
    lang_code: str
    lang_name: str
    source_text: str
    translated_text: str
    audio_b64: str          # Base64-encoded audio bytes
    is_final: bool
    latency_ms: float
    moderation_flag: bool
    timestamp: float


@dataclass
class StreamChunkPayload:
    """Payload for a single streaming audio chunk."""
    type: str               # "audio_chunk" or "stream_complete"
    lang_code: str
    source_text: str
    translated_text: str
    audio_b64: str          # Base64-encoded audio chunk
    chunk_index: int
    is_final: bool
    latency_ms: float
    moderation_flag: bool
    timestamp: float


@dataclass
class ErrorPayload:
    type: str
    lang_code: str
    message: str
    timestamp: float


class ChannelManager:
    """
    Manages WebSocket subscriber connections per language channel.
    Supports both streaming chunks and batch audio broadcasting.
    All listeners connected to a language channel receive the broadcast.
    """

    def __init__(self) -> None:
        self._cfg = cfg.redis
        self._prefix = self._cfg.channel_prefix
        # Local subscriber map: lang_code -> set of WebSocket connections
        self._subscribers: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._redis_enabled = False
        # Pre-encode common payloads to avoid repeated serialization
        self._send_lock = asyncio.Lock()

    async def startup(self) -> None:
        """Initialize Redis pubsub connection for cross-node broadcasting."""
        channels = [f"{self._prefix}:{lang.code}" for lang in cfg.enabled_languages]
        
        self._redis = await get_redis()
        if self._redis:
            try:
                self._pubsub = self._redis.pubsub()
                if channels:
                    await self._pubsub.subscribe(*channels)
                
                self._listener_task = asyncio.create_task(self._redis_listener())
                self._redis_enabled = True
                log.info("channel_manager_redis_subscribed", channels=channels)
            except Exception as exc:
                log.warning("channel_manager_redis_init_failed", error=str(exc))
                self._redis_enabled = False
        else:
            log.warning("channel_manager_memory_mode_only")

    async def shutdown(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        # Redis connection is shared and closed by the app lifespan
        log.info("channel_manager_stopped")

    async def subscribe(self, ws: WebSocket, lang_code: str) -> None:
        """Register a WebSocket as a listener on a language channel."""
        self._subscribers[lang_code].add(ws)
        active_listeners.labels(lang_code=lang_code).set(len(self._subscribers[lang_code]))
        log.info("listener_subscribed", lang=lang_code, count=len(self._subscribers[lang_code]))

    async def unsubscribe(self, ws: WebSocket, lang_code: str) -> None:
        """Remove a WebSocket from a language channel."""
        self._subscribers[lang_code].discard(ws)
        active_listeners.labels(lang_code=lang_code).set(len(self._subscribers[lang_code]))
        log.info("listener_unsubscribed", lang=lang_code, count=len(self._subscribers[lang_code]))

    # ── Streaming Chunk Broadcasting (Low Latency) ───────────────

    async def publish_audio_chunk(
        self,
        lang_code: str,
        audio_chunk: bytes,
        chunk_index: int,
        source_text: str,
        translated_text: str,
        is_final: bool,
        pipeline_latency_ms: float,
        moderation_flag: bool,
    ) -> None:
        """
        Broadcast a single audio chunk to all subscribers of a language.
        Called as each chunk arrives from ElevenLabs — minimum latency path.
        """
        payload = StreamChunkPayload(
            type="audio_chunk",
            lang_code=lang_code,
            source_text=source_text,
            translated_text=translated_text,
            audio_b64=base64.b64encode(audio_chunk).decode(),
            chunk_index=chunk_index,
            is_final=is_final,
            latency_ms=pipeline_latency_ms,
            moderation_flag=moderation_flag,
            timestamp=time.time(),
        )
        encoded = json.dumps(asdict(payload)).encode()

        # Fan out to all local subscribers
        ws_set = self._subscribers.get(lang_code, set())
        if ws_set:
            tasks = [self._safe_send(ws, encoded, lang_code) for ws in list(ws_set)]
            await asyncio.gather(*tasks)

        # Publish to Redis for horizontal scaling
        if self._redis_enabled and self._redis:
            channel = f"{self._prefix}:{lang_code}"
            try:
                await self._redis.publish(channel, encoded)
            except Exception:
                pass

    async def publish_translation_update(
        self,
        lang_code: str,
        source_text: str,
        translated_text: str,
        is_final: bool,
        pipeline_latency_ms: float,
    ) -> None:
        """
        Broadcast just the text translation (no audio).
        Allows UI to update instantly after LLM phase.
        """
        payload = StreamChunkPayload(
            type="translation_update",
            lang_code=lang_code,
            source_text=source_text,
            translated_text=translated_text,
            audio_b64="",
            chunk_index=-1,
            is_final=is_final,
            latency_ms=pipeline_latency_ms,
            moderation_flag=False,
            timestamp=time.time(),
        )
        encoded = json.dumps(asdict(payload)).encode()

        ws_set = self._subscribers.get(lang_code, set())
        if ws_set:
            tasks = [self._safe_send(ws, encoded, lang_code) for ws in list(ws_set)]
            await asyncio.gather(*tasks)

        if self._redis_enabled and self._redis:
            try:
                await self._redis.publish(f"{self._prefix}:{lang_code}", encoded)
            except Exception:
                pass

    async def publish_stream_complete(
        self,
        lang_code: str,
        source_text: str,
        translated_text: str,
        is_final: bool,
        pipeline_latency_ms: float,
        moderation_flag: bool,
    ) -> None:
        """
        Send a 'stream_complete' message to signal end of audio chunks.
        Listeners use this to finalize playback buffering.
        """
        payload = StreamChunkPayload(
            type="stream_complete",
            lang_code=lang_code,
            source_text=source_text,
            translated_text=translated_text,
            audio_b64="",
            chunk_index=-1,
            is_final=is_final,
            latency_ms=pipeline_latency_ms,
            moderation_flag=moderation_flag,
            timestamp=time.time(),
        )
        encoded = json.dumps(asdict(payload)).encode()

        ws_set = self._subscribers.get(lang_code, set())
        if ws_set:
            tasks = [self._safe_send(ws, encoded, lang_code) for ws in list(ws_set)]
            await asyncio.gather(*tasks)

    async def publish_error(self, lang_code: str, message: str) -> None:
        """Broadcast a non-audio error to listeners of one language channel."""
        payload = ErrorPayload(
            type="error",
            lang_code=lang_code,
            message=message,
            timestamp=time.time(),
        )
        encoded = json.dumps(asdict(payload)).encode()

        ws_set = self._subscribers.get(lang_code, set())
        if ws_set:
            tasks = [self._safe_send(ws, encoded, lang_code) for ws in list(ws_set)]
            await asyncio.gather(*tasks)

        if self._redis_enabled and self._redis:
            try:
                await self._redis.publish(f"{self._prefix}:{lang_code}", encoded)
            except Exception:
                pass

    # ── Batch Broadcasting (Legacy / Fallback) ───────────────────

    async def publish_results(
        self,
        source_text: str,
        tts_results: list[TTSResult],
        is_final: bool,
        moderation_flag: bool,
        translated_texts: Dict[str, str],
        pipeline_latency_ms: float,
    ) -> None:
        """Publish TTS audio + metadata to local subscribers and optionally Redis."""
        local_tasks = []
        redis_tasks = []
        for result in tts_results:
            payload = BroadcastPayload(
                lang_code=result.lang_code,
                lang_name=result.lang_name,
                source_text=source_text,
                translated_text=translated_texts.get(result.lang_code, ""),
                audio_b64=base64.b64encode(result.audio_bytes).decode(),
                is_final=is_final,
                latency_ms=pipeline_latency_ms,
                moderation_flag=moderation_flag,
                timestamp=time.time(),
            )
            encoded_payload = json.dumps(asdict(payload)).encode()

            for ws in list(self._subscribers.get(result.lang_code, set())):
                local_tasks.append(self._safe_send(ws, encoded_payload, result.lang_code))

            if self._redis_enabled and self._redis:
                channel = f"{self._prefix}:{result.lang_code}"
                redis_tasks.append(self._redis.publish(channel, encoded_payload))

        if local_tasks:
            await asyncio.gather(*local_tasks)
        if redis_tasks:
            await asyncio.gather(*redis_tasks)

    async def _redis_listener(self) -> None:
        """
        Background task: reads from Redis pubsub and fans out
        to all local WebSocket subscribers for that language.
        """
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue
                channel_bytes: bytes = message["channel"]
                channel = channel_bytes.decode()
                lang_code = channel.split(":")[-1]

                data = message["data"]
                ws_set = self._subscribers.get(lang_code, set())
                if not ws_set:
                    continue

                dead: list[WebSocket] = []
                for ws in list(ws_set):
                    try:
                        await ws.send_bytes(data)
                    except Exception:
                        dead.append(ws)

                for ws in dead:
                    ws_set.discard(ws)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.error("redis_listener_error", error=str(exc))

    async def _safe_send(self, ws: WebSocket, payload: bytes, lang_code: str) -> None:
        try:
            await ws.send_bytes(payload)
        except Exception:
            self._subscribers[lang_code].discard(ws)

    def subscriber_count(self, lang_code: str) -> int:
        return len(self._subscribers.get(lang_code, set()))

    def all_subscriber_counts(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self._subscribers.items()}
