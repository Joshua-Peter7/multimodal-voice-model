"""
api/server.py — FastAPI application with WebSocket endpoints.

Endpoints:
  WS  /ws/speaker            — Speaker sends raw PCM audio here
  WS  /ws/listener/{lang}    — Listeners receive audio + metadata for their language
  GET /health                — Health check
  GET /stats                 — Pipeline metrics
  GET /languages             — Available language channels
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config_loader import cfg
from src.logger import get_logger
from src.pipeline.orchestrator import TranslationPipeline
from src.streaming.channel_manager import ChannelManager

log = get_logger(__name__)

# ── Globals ──────────────────────────────────────────────────
_channel_manager: Optional[ChannelManager] = None
_active_speaker: Optional[str] = None  # Session ID of current speaker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global _channel_manager
    log.info("server_starting")

    _channel_manager = ChannelManager()
    await _channel_manager.startup()

    log.info(
        "server_ready",
        host=cfg.server.host,
        port=cfg.server.port,
        languages=[l.code for l in cfg.enabled_languages],
    )

    yield

    log.info("server_shutting_down")
    await _channel_manager.shutdown()


# ── App Setup ────────────────────────────────────────────────
app = FastAPI(
    title="Real-Time Translation Broadcast",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST Endpoints ─── (MUST be before StaticFiles mount)

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "timestamp": time.time(),
        "active_speaker": _active_speaker,
        "channels": _channel_manager.all_subscriber_counts() if _channel_manager else {},
    })


@app.get("/languages")
async def languages() -> JSONResponse:
    return JSONResponse({
        "source": {"code": cfg.source.language_code, "name": cfg.source.language_name},
        "targets": [
            {
                "code": lang.code,
                "name": lang.name,
                "listeners": _channel_manager.subscriber_count(lang.code) if _channel_manager else 0,
            }
            for lang in cfg.enabled_languages
        ],
    })


@app.get("/stats")
async def stats() -> JSONResponse:
    channels = _channel_manager.all_subscriber_counts() if _channel_manager else {}
    return JSONResponse({
        "channels": channels,
        "total_listeners": sum(channels.values()),
    })


# ── Serve frontend static files (MUST be after REST + WebSocket endpoints)
from pathlib import Path
from fastapi.responses import FileResponse

# Custom route to serve index.html (before static files)
@app.get("/", include_in_schema=False)
async def root():
    frontend_path = Path(__file__).parent.parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return FileResponse(frontend_path, media_type="text/html")
    return JSONResponse({"error": "Frontend not found"}, status_code=404)

# Mount remaining static assets (CSS, JS, etc.) but not at root
try:
    frontend_path = Path(__file__).parent.parent.parent / "frontend"
    if frontend_path.exists():
        app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")
except Exception as e:
    log.warning(f"static_assets_mount_error", error=str(e))


# ── Speaker WebSocket ────────────────────────────────────────

@app.websocket("/ws/speaker")
async def speaker_ws(websocket: WebSocket):
    """
    Speaker connects here and streams raw PCM audio (16kHz, 16-bit, mono).
    Each binary message should be a chunk of raw PCM bytes.
    """
    global _active_speaker
    session_id = str(uuid.uuid4())[:8]
    
    try:
        # Validate channel manager is available
        if _channel_manager is None:
            log.error("channel_manager_not_initialized", session=session_id)
            await websocket.close(code=1011, reason="Server not ready")
            return
        
        await websocket.accept()
    except Exception as e:
        log.error("ws_acceptance_error", session=session_id, error=str(e))
        try:
            await websocket.close(code=1011, reason=f"Connection error: {str(e)}")
        except:
            pass
        return

    _active_speaker = session_id

    log.info("speaker_connected", session=session_id)
    
    try:
        await websocket.send_text(json.dumps({
            "type": "connected",
            "session_id": session_id,
            "config": {
                "sample_rate": cfg.audio.sample_rate,
                "channels": cfg.audio.channels,
                "bit_depth": cfg.audio.bit_depth,
            },
        }))
    except Exception as e:
        log.error("ws_send_error", session=session_id, error=str(e))
        return

    # Audio queue fed from WebSocket messages
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)
    audio_chunk_count = 0
    total_audio_bytes = 0

    async def _ws_audio_source():
        while True:
            chunk = await audio_queue.get()
            if chunk == b"__END__":
                log.info(
                    "audio_stream_ended",
                    session=session_id,
                    total_chunks=audio_chunk_count,
                    total_bytes=total_audio_bytes,
                )
                return
            yield chunk

    try:
        pipeline = TranslationPipeline(_channel_manager)
    except Exception as e:
        log.error("pipeline_init_error", session=session_id, error=str(e))
        await websocket.close(code=1011, reason="Pipeline initialization failed")
        return

    async def _pipeline_task():
        try:
            log.info("pipeline_task_starting", session=session_id)
            async for transcript in pipeline.run(_ws_audio_source()):
                log.info("transcript_received", session=session_id, text=transcript.text[:50])
                try:
                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "text": transcript.text,
                        "is_final": transcript.is_final
                    }))
                except Exception as e:
                    log.error("transcript_send_error", error=str(e))
            log.info("pipeline_task_completed", session=session_id)
        except asyncio.CancelledError:
            log.info("pipeline_task_cancelled", session=session_id)
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {str(exc)}"
            log.error("pipeline_error", session=session_id, error=error_msg, traceback=str(exc))
            # Send error to frontend
            try:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Pipeline error: {error_msg}"
                }))
            except:
                pass

    pipe_task = asyncio.create_task(_pipeline_task())

    try:
        while True:
            msg = await asyncio.wait_for(
                websocket.receive(),
                timeout=cfg.server.ping_timeout_seconds,
            )

            if "bytes" in msg and msg["bytes"]:
                chunk_size = len(msg["bytes"])
                audio_chunk_count += 1
                total_audio_bytes += chunk_size
                
                if audio_chunk_count == 1:
                    log.info("first_audio_chunk", session=session_id, bytes=chunk_size)
                elif audio_chunk_count % 100 == 0:
                    log.info(
                        "audio_stream_progress",
                        session=session_id,
                        chunks=audio_chunk_count,
                        total_bytes=total_audio_bytes,
                    )
                
                await audio_queue.put(msg["bytes"])
            elif "text" in msg:
                try:
                    data = json.loads(msg["text"])
                    if data.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                    elif data.get("type") == "end":
                        log.info("client_end_signal", session=session_id)
                        break
                except json.JSONDecodeError:
                    pass

    except (WebSocketDisconnect, asyncio.TimeoutError):
        log.info("speaker_disconnected", session=session_id)
    finally:
        await audio_queue.put(b"__END__")
        pipe_task.cancel()
        await pipeline.close()
        _active_speaker = None

        # Send final stats back
        try:
            s = pipeline.stats
            await websocket.send_text(json.dumps({
                "type": "session_end",
                "stats": {
                    "utterances": s.total_utterances,
                    "avg_latency_ms": round(s.avg_latency_ms, 1),
                    "errors": s.errors,
                },
            }))
        except Exception:
            pass

        log.info("speaker_session_closed", session=session_id)


# ── Listener WebSocket ───────────────────────────────────────

@app.websocket("/ws/listener/{lang_code}")
async def listener_ws(
    websocket: WebSocket,
    lang_code: str,
    metadata_only: bool = Query(False, description="Receive JSON metadata, not audio"),
):
    """
    Listener connects here, specifying their preferred language code.
    Receives binary frames: JSON-encoded BroadcastPayload (with base64 audio).
    Set metadata_only=true to receive translations without audio.
    """
    listener_id = str(uuid.uuid4())[:8]
    
    try:
        # Validate language
        valid_codes = {lang.code for lang in cfg.enabled_languages}
        if lang_code not in valid_codes:
            await websocket.close(code=4004, reason=f"Unknown language: {lang_code}")
            return

        # Validate channel manager is available
        if _channel_manager is None:
            log.error("channel_manager_not_initialized", listener=listener_id, lang=lang_code)
            await websocket.close(code=1011, reason="Server not ready")
            return

        await websocket.accept()
    except Exception as e:
        log.error("listener_ws_acceptance_error", listener=listener_id, error=str(e))
        try:
            await websocket.close(code=1011)
        except:
            pass
        return

    log.info("listener_connected", lang=lang_code, listener=listener_id)
    
    try:
        await websocket.send_text(json.dumps({
            "type": "subscribed",
            "lang_code": lang_code,
            "listener_id": listener_id,
        }))
    except Exception as e:
        log.error("listener_send_error", listener=listener_id, error=str(e))
        return

    try:
        await _channel_manager.subscribe(websocket, lang_code)
    except Exception as e:
        log.error("listener_subscribe_error", listener=listener_id, lang=lang_code, error=str(e))
        await websocket.close(code=1011, reason="Subscription failed")
        return

    try:
        # Keep connection alive, send pongs
        while True:
            try:
                msg = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=cfg.server.ping_interval_seconds,
                )
                if "text" in msg:
                    data = json.loads(msg.get("text", "{}"))
                    if data.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                    elif data.get("type") == "switch_language":
                        # Allow hot-switch to another language
                        new_lang = data.get("lang_code", lang_code)
                        if new_lang in valid_codes and new_lang != lang_code:
                            await _channel_manager.unsubscribe(websocket, lang_code)
                            lang_code = new_lang
                            await _channel_manager.subscribe(websocket, lang_code)
                            await websocket.send_text(json.dumps({
                                "type": "switched",
                                "lang_code": lang_code,
                            }))
            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        await _channel_manager.unsubscribe(websocket, lang_code)
        log.info("listener_disconnected", lang=lang_code, listener=listener_id)
