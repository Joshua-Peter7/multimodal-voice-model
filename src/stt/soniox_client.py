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

SONIOX_WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"


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
        try:
            log.info("soniox_connecting", api_key_set=bool(self._cfg.api_key))
            ws = await session.ws_connect(
                SONIOX_WS_URL,
                heartbeat=20,
                max_msg_size=0,
            )
            log.info("soniox_ws_connected", ws_closed=ws.closed)
            
            # Send config frame - Soniox expects a specific JSON format
            config = {
                "api_key": self._cfg.api_key,
                "model": self._cfg.model,
                "audio_format": "pcm_s16le",
                "sample_rate": self._cfg.sample_rate,
                "num_channels": self._cfg.num_audio_channels,
                "include_nonfinal": self._cfg.include_nonfinal,
                "enable_endpoint_detection": True,
            }
            config_json = json.dumps(config)
            log.info("soniox_config_json", json_str=config_json[:200])
            await ws.send_str(config_json)
            log.info("soniox_config_sent", config_keys=list(config.keys()), model=self._cfg.model)
            
            # Try to read acknowledgment or any immediate response
            try:
                # Wait briefly to see if Soniox closes or sends an ack
                await asyncio.sleep(0.1)
                # Check if connection is still open
                if ws.closed:
                    log.error("soniox_closed_after_config", reason="WebSocket closed after config send")
                else:
                    log.info("soniox_connection_still_open")
            except:
                pass
            
            return ws
        except Exception as e:
            log.error("soniox_connect_error", error=str(e), error_type=type(e).__name__)
            raise

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
        chunks_sent = 0

        async def _send_audio() -> None:
            nonlocal chunks_sent
            try:
                async for chunk in audio_chunks:
                    await ws.send_bytes(chunk)
                    chunks_sent += 1
                    if chunks_sent == 1:
                        log.info("soniox_first_chunk_sent", bytes=len(chunk))
                    elif chunks_sent % 100 == 0:
                        log.info("soniox_audio_progress", chunks=chunks_sent)
                # Signal end of stream
                log.info("soniox_sending_eof", total_chunks=chunks_sent)
                await ws.send_str("")
            except Exception as e:
                log.error("soniox_send_error", error=str(e))
                raise

        send_task = asyncio.create_task(_send_audio())

        msg_count = 0
        final_tokens = []
        try:
            log.info("soniox_waiting_for_messages", ws_closed=ws.closed)
            async for msg in ws:
                msg_count += 1
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError as e:
                        log.error("soniox_json_parse_error", error=str(e), raw=str(msg.data)[:200])
                        continue

                    if data.get("error_code") is not None:
                        log.error("soniox_api_error", error_code=data.get("error_code"), error=data.get("error_message"))
                        break

                    non_final_tokens = []
                    for token in data.get("tokens", []):
                        if token.get("text"):
                            if token.get("is_final"):
                                final_tokens.append(token)
                            else:
                                non_final_tokens.append(token)

                    if final_tokens or non_final_tokens:
                        # Reconstruct the current text
                        all_text = "".join(t["text"] for t in final_tokens + non_final_tokens).strip()
                        
                        latency = (time.perf_counter() - send_start) * 1000
                        # Determine if this emit should be considered absolutely final
                        is_final = bool(data.get("finished", False))
                        
                        # But wait, orchestrator treats is_final=True as "phrase complete", so we can also check endpointing
                        # Soniox doesn't explicitly flag utterance endpoints except by finishing or by logic in the tokens.
                        # For now, we'll stream identically to the mock.
                        
                        transcript = Transcript(
                            text=all_text,
                            is_final=is_final,
                            confidence=1.0,
                            latency_ms=latency,
                            words=final_tokens + non_final_tokens,
                        )

                        yield transcript

                    if data.get("finished"):
                        log.info("soniox_stream_finished")
                        # Emitting a final empty text transcript can signal true pipeline flush if needed
                        break

                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    log.warning("soniox_ws_close_received", code=msg.data, message=msg.extra)
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    log.warning("soniox_ws_closed", msg_type=str(msg.type), msg=str(msg))
                    break
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    log.debug("soniox_binary_message", size=len(msg.data))
        except asyncio.CancelledError:
            log.info("soniox_cancelled")
        except Exception as e:
            log.error("soniox_receive_error", error=str(e), error_type=type(e).__name__)
        finally:
            log.info("soniox_session_end", messages_received=msg_count, chunks_sent=chunks_sent)
            try:
                send_task.cancel()
            except:
                pass
            await ws.close()

    async def close(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        log.info("soniox_client_closed")
