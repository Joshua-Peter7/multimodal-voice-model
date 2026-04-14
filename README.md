# 🌐 AI Multi-Channel Real-Time Speech Translation & Broadcast System

> **Stack:** Soniox STT · Llama 8B (HuggingFace) · ElevenLabs TTS  
> **Pattern:** Streaming WebSocket pipeline with Redis pub/sub channel distribution

---

## Architecture

```
Speaker (mic/browser)
        │
        │  raw PCM (WebSocket /ws/speaker)
        ▼
┌─────────────────────────────────────────────────────┐
│                  FastAPI Server                      │
│                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐  │
│  │ Audio    │    │ VAD      │    │ Soniox STT   │  │
│  │ Ingestion│───▶│ (webrtc) │───▶│ (WebSocket)  │  │
│  │ + Noise  │    │          │    │ partial+final│  │
│  │ Suppress │    └──────────┘    └──────┬───────┘  │
│  └──────────┘                           │           │
│                                         ▼           │
│                               ┌──────────────────┐  │
│                               │ LLM Translator   │  │
│                               │ Llama 8B (HF)    │  │
│                               │ 1-call → N langs │  │
│                               └────────┬─────────┘  │
│                                        │             │
│                               ┌────────▼─────────┐  │
│                               │ Content Moderator│  │
│                               └────────┬─────────┘  │
│                                        │             │
│                               ┌────────▼─────────┐  │
│                               │ ElevenLabs TTS   │  │
│                               │ Parallel per lang│  │
│                               └────────┬─────────┘  │
│                                        │             │
│                               ┌────────▼─────────┐  │
│                               │ Redis Pub/Sub    │  │
│                               │ Channel Manager  │  │
│                               └────────┬─────────┘  │
└────────────────────────────────────────┼─────────────┘
                                         │
          ┌──────────┬──────────┬────────┘
          ▼          ▼          ▼
    /ws/listener  /ws/listener  /ws/listener
       /hi           /te           /ta
    (Hindi)       (Telugu)      (Tamil)
    listeners     listeners     listeners
```

---

## Project Structure

```
realtime-translation/
├── config/
│   └── config.yaml          ← ALL settings live here
├── src/
│   ├── config_loader.py     ← Loads config + env vars
│   ├── logger.py            ← Structured JSON/text logging
│   ├── metrics.py           ← Prometheus metrics
│   ├── audio/
│   │   ├── ingestion.py     ← PCM capture, noise suppression
│   │   └── vad.py           ← Voice Activity Detection
│   ├── stt/
│   │   └── soniox_client.py ← Streaming Soniox WebSocket STT
│   ├── translation/
│   │   └── llm_translator.py← One-to-many Llama translation
│   ├── moderation/
│   │   └── content_moderator.py
│   ├── tts/
│   │   └── elevenlabs_client.py ← Parallel streaming TTS
│   ├── streaming/
│   │   └── channel_manager.py   ← Redis pub/sub + WS fan-out
│   ├── pipeline/
│   │   └── orchestrator.py  ← Full pipeline coordinator
│   └── api/
│       └── server.py        ← FastAPI + WebSocket endpoints
├── frontend/
│   └── index.html           ← Speaker + Listener web UI
├── scripts/
│   ├── test_mic.py          ← Local mic test (no server needed)
│   └── benchmark_latency.py ← Per-stage latency profiler
├── tests/
│   ├── test_pipeline.py
│   ├── test_stt.py
│   └── test_translation.py
├── .env.example
├── config/config.yaml
├── Dockerfile
├── docker-compose.yml
├── main.py
└── requirements.txt
```

---

## Quick Start

### 1. Clone & Configure

```bash
git clone <your-repo>
cd realtime-translation

cp .env.example .env
# Fill in your API keys in .env
```

### 2. Edit `config/config.yaml`

The **single config file** controls everything:

| Section | What to edit |
|---|---|
| `apis.soniox` | STT model, sample rate |
| `apis.huggingface` | Llama model ID, endpoint URL, token limits |
| `apis.elevenlabs` | TTS model, output format, streaming latency |
| `languages` | Add/remove target languages, toggle `enabled`, set `voice_id` |
| `audio.vad` | Silence detection aggressiveness |
| `pipeline` | Speculative translation, concurrency limits |
| `moderation` | Block/filter/flag strategy, custom word list |
| `server` | Host, port, CORS |

### 3A. Run with Docker (recommended)

```bash
docker compose up --build
```

### 3B. Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### 4. Open the UI

Visit `http://localhost:8000` in your browser.

- **Speaker**: Click "Start Broadcasting", speak into your mic
- **Listener**: Click "Listen" on any language card to receive translated audio

---

## API Reference

### WebSocket — Speaker
```
WS /ws/speaker
```
Send raw **PCM audio** (16kHz, 16-bit, mono) as binary frames.

Control messages (JSON text frames):
```json
{ "type": "ping" }          → { "type": "pong" }
{ "type": "end" }           → graceful close
```

### WebSocket — Listener
```
WS /ws/listener/{lang_code}
```
Receives binary JSON frames:
```json
{
  "lang_code": "hi",
  "lang_name": "Hindi",
  "source_text": "Hello, how are you?",
  "translated_text": "नमस्ते, आप कैसे हैं?",
  "audio_b64": "<base64-encoded PCM/MP3>",
  "is_final": true,
  "latency_ms": 1240.5,
  "moderation_flag": false,
  "timestamp": 1719000000.0
}
```

Switch language without reconnecting:
```json
{ "type": "switch_language", "lang_code": "te" }
```

### REST
| Endpoint | Description |
|---|---|
| `GET /health` | Server health + active connections |
| `GET /languages` | Available language channels |
| `GET /stats` | Listener counts per channel |
| `GET /metrics` | Prometheus metrics (port 9090) |

---

## Latency Notes

> **⚠ Realistic latency expectations with external API calls:**

| Stage | Target | Realistic |
|---|---|---|
| Soniox STT (partial) | ~100ms | 100–300ms |
| Soniox STT (final) | ~200ms | 200–600ms |
| LLM Translation (shared HF) | — | 800ms–3s |
| LLM Translation (dedicated endpoint) | ~300ms | 300–800ms |
| ElevenLabs TTS (turbo, streaming) | ~200ms | 200–500ms |
| **Total (dedicated HF endpoint)** | — | **~1–2s** |
| **Total (shared HF API)** | — | **~2–5s** |

The system minimizes *perceived* latency through:

1. **Speculative translation** — translates partial STT results (configurable via `pipeline.speculative_translation`)
2. **Parallel TTS** — all languages synthesized simultaneously with `asyncio.gather`
3. **Streaming TTS** — ElevenLabs audio chunks streamed as they generate
4. **Connection pooling** — persistent HTTP sessions with keep-alive for all APIs
5. **uvloop + httptools** — fast async event loop and HTTP parser

**To get closest to 100ms total**, you need:
- A **dedicated HuggingFace Inference Endpoint** (set `HF_ENDPOINT_URL` in `.env`)
- ElevenLabs **Turbo v2.5** model (already set in config)
- `optimize_streaming_latency: 4` (already set)
- Co-located server (same cloud region as your API endpoints)

---

## Adding a New Language

In `config/config.yaml`, add an entry under `languages`:

```yaml
- code: "ja"
  name: "Japanese"
  voice_id: "${EL_VOICE_JA}"       # Add EL_VOICE_JA=xxx to .env
  stability: 0.5
  similarity_boost: 0.75
  enabled: true
```

No code changes needed. Restart the server.

---

## Running Tests

```bash
pytest tests/ -v
```

## Benchmarking

```bash
# Test with a WAV file
python scripts/benchmark_latency.py --audio sample.wav --rounds 5

# Test translation + TTS only (no audio file)
python scripts/benchmark_latency.py --text "Good morning, welcome to our broadcast" --rounds 3
```

## Local Mic Test (no server required)

```bash
python scripts/test_mic.py --duration 20 --lang hi,te
```

---

## Scaling

The app is designed as a **single-process** server because WebSocket state is local.  
To scale horizontally:

1. All language channel data flows through **Redis pub/sub** — multiple app instances share the same channels
2. Run multiple app containers behind a **WebSocket-aware load balancer** (nginx with `proxy_read_timeout` / Caddy)
3. Speaker session stickiness: ensure one speaker's WebSocket stays on one instance (cookie/IP affinity)

---

## Environment Variables

| Variable | Description |
|---|---|
| `SONIOX_API_KEY` | Soniox API key |
| `HUGGINGFACE_API_KEY` | HuggingFace API key (`hf_...`) |
| `HF_ENDPOINT_URL` | Optional: Dedicated HF Inference Endpoint URL |
| `ELEVENLABS_API_KEY` | ElevenLabs API key |
| `EL_VOICE_HI/TE/TA/ES/FR/DE` | ElevenLabs voice IDs per language |
| `REDIS_HOST` | Redis hostname (default: `redis`) |
| `REDIS_PASSWORD` | Redis password (optional) |
