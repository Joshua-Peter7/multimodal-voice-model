"""
stt/soniox_client.py — Soniox streaming Speech-to-Text client.
Yields partial and final transcripts with minimal latency.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import aiohttp

from src.config_loader import cfg
from src.logger import get_logger, log_latency

log = get_logger(__name__)

SONIOX_WS_URL = "wss://api.soniox.com/transcribe-websocket"


@dataclass
class Transcript:
    text: str
    is_final: bool
    confidence: float
    latency_ms: float
    words: list[dict]


class SonioxSTTClient:
    """
    Maintains a persistent WebSocket connection to Soniox and streams
    audio chunks, emitting Transcript objects as they arrive.
    """

    def __init__(self) -> None:
        self._cfg = cfg.apis.soniox
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=10,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=60,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                headers={"Authorization": f"Bearer {self._cfg.api_key}"},
            )
        return self._session

    async def _connect(self) -> aiohttp.ClientWebSocketResponse:
        """Open a new WebSocket connection to Soniox."""
        session = await self._ensure_session()
        ws = await session.ws_connect(
            SONIOX_WS_URL,
            heartbeat=20,
            max_msg_size=0,
        )
        # Send config frame
        config = {
            "api_key": self._cfg.api_key,
            "model": self._cfg.model,
            "sample_rate": self._cfg.sample_rate,
            "num_audio_channels": self._cfg.num_audio_channels,
            "include_nonfinal": self._cfg.include_nonfinal,
            "max_alternatives": self._cfg.max_alternatives,
        }
        await ws.send_str(json.dumps(config))
        log.info("soniox_connected", model=self._cfg.model)
        return ws

    async def transcribe_stream(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
    ) -> AsyncGenerator[Transcript, None]:
        """
        Feed audio chunks into a Soniox WebSocket session.
        Yields Transcript objects for both partial and final results.
        """
        for attempt in range(cfg.pipeline.retry_attempts + 1):
            try:
                async for transcript in self._run_session(audio_chunks):
                    yield transcript
                return
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                log.warning("soniox_connection_error", attempt=attempt, error=str(exc))
                if attempt >= cfg.pipeline.retry_attempts:
                    raise
                await asyncio.sleep(cfg.pipeline.retry_delay_ms / 1000)

    async def _run_session(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
    ) -> AsyncGenerator[Transcript, None]:
        ws = await self._connect()
        send_start = time.perf_counter()

        async def _send_audio() -> None:
            async for chunk in audio_chunks:
                await ws.send_bytes(chunk)
            # Signal end of stream
            await ws.send_str(json.dumps({"eof": True}))

        send_task = asyncio.create_task(_send_audio())

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)

                    if "error" in data:
                        log.error("soniox_api_error", error=data["error"])
                        break

                    if "final_proc_time_ms" in data or "words" in data:
                        words = data.get("words", [])
                        final_words = [w for w in words if w.get("is_final", True)]
                        nonfinal_words = [w for w in words if not w.get("is_final", True)]

                        all_text = " ".join(w.get("text", "") for w in words).strip()
                        is_final = len(nonfinal_words) == 0 and len(final_words) > 0

                        if not all_text:
                            continue

                        latency = (time.perf_counter() - send_start) * 1000
                        transcript = Transcript(
                            text=all_text,
                            is_final=is_final,
                            confidence=data.get("confidence", 1.0),
                            latency_ms=latency,
                            words=words,
                        )

                        if cfg.logging.log_transcripts:
                            log.info(
                                "transcript",
                                text=all_text,
                                is_final=is_final,
                                latency_ms=round(latency, 1),
                            )

                        yield transcript

                    if data.get("finished"):
                        break

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    log.warning("soniox_ws_closed")
                    break
        finally:
            send_task.cancel()
            await ws.close()

    async def close(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        log.info("soniox_client_closed")
