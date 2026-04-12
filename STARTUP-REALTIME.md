# Real-Time 6-Language Indian Translation System - Startup Guide

> **Duration**: ~7-12 seconds for complete translation pipeline  
> **Supported Languages**: Tamil • English • Telugu • Malayalam • Kannada • Hindi

## Quick Overview

The system processes audio through 4 concurrent services:

```
User Speech (any language)
         ↓
    Sonix STT
   (2-3 seconds)   ← Transcribes to text
         ↓
    Llama LLM
   (2-4 seconds)   ← Translates to 6 languages in parallel
         ↓
  ElevenLabs TTS
   (3-5 seconds)   ← Generates audio for all 6 languages in parallel
         ↓
  6 Audio Streams
   (Ready to Play)  ← Tamil • English • Telugu • Malayalam • Kannada • Hindi
```

## Prerequisites

### Required Software
- **Python**: 3.11+
- **Node.js**: 18+ (optional, for dev server only)
- **Redis**: (optional, for context caching)

### API Keys Required

You need API keys from these services:

1. **Sonix** (Speech-to-Text)
   - Sign up: https://sonix.ai
   - Get API key from dashboard

2. **Llama Translation** (choose one LLM provider):
   - **Anthropic Claude** (recommended):
     - Sign up: https://console.anthropic.com
     - Create API key
   - OR **OpenAI**:
     - Sign up: https://platform.openai.com
     - Create API key for GPT-4
   - OR **HuggingFace**:
     - Sign up: https://huggingface.co
     - Create API token

3. **ElevenLabs** (Text-to-Speech)
   - Sign up: https://elevenlabs.io
   - Get API key from account settings

## Installation

### 1. Clone Repository

```bash
cd /path/to/workspace
git clone <repo-url>
cd multimodal-voice\ cloning
```

### 2. Create Virtual Environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
# Install all service requirements
pip install -r requirements-all.txt
```

### 4. Configure Environment

```bash
# Copy the realtime configuration template
cp .env.realtime .env

# Edit .env and add your API keys
# (Edit in your text editor)
```

**Edit `.`.env` with your credentials**:

```bash
# ASR (Sonix)
ASR_SONIX_API_KEY=sk_live_your-key-here
ASR_SONIX_WORKSPACE_TOKEN=your-token-here

# Translation (choose one)
# Option 1: Anthropic Claude (recommended)
TRANSLATION_ANTHROPIC_API_KEY=sk-ant-your-key-here

# Option 2: OpenAI GPT-4
# TRANSLATION_OPENAI_API_KEY=sk-proj-your-key-here

# Option 3: HuggingFace
# TRANSLATION_HUGGINGFACE_API_KEY=hf_your-token-here

# TTS (ElevenLabs)
TTS_ELEVENLABS_API_KEY=sk_your-key-here
```

### 5. Create Necessary Directories

```bash
mkdir -p logs
mkdir -p data/cache
mkdir -p data/uploads
```

## Starting the System

### Option A: Start All Services (Automated)

```bash
# Run the complete startup script
python scripts/start_realtime_system.py
```

Expected output:
```
[INFO] Starting real-time translation system...
[INFO] ✓ API Gateway ready (http://localhost:5000)
[INFO] ✓ ASR Service ready (http://localhost:5002)
[INFO] ✓ Translation Service ready (http://localhost:5003)
[INFO] ✓ TTS Service ready (http://localhost:5005)
[INFO] All services healthy and ready!
[INFO] Access frontend at: http://localhost:3000
```

### Option B: Start Services Individually

#### Terminal 1: API Gateway

```bash
cd services/api-gateway
python src/main.py
# Listening on http://localhost:5000
```

#### Terminal 2: ASR Service (Sonix STT)

```bash
cd services/asr-service
python src/main.py
# Listening on http://localhost:5002
```

#### Terminal 3: Translation Service (Llama)

```bash
cd services/translation-service
python src/main.py
# Listening on http://localhost:5003
```

#### Terminal 4: TTS Service (ElevenLabs)

```bash
cd services/tts-service
python src/main.py
# Listening on http://localhost:5005
```

#### Terminal 5: Frontend Server

```bash
# Option A: Using Python
cd web
python -m http.server 3000

# Option B: Using Node.js
npx serve -s . -p 3000

# Option C: Using any static server
# The frontend is pure HTML/CSS/JS, no build needed
```

## Verify Services Are Running

### Check Individual Service Health

```bash
# ASR Service
curl http://localhost:5002/api/v1/health

# Translation Service
curl http://localhost:5003/api/v1/health

# TTS Service
curl http://localhost:5005/api/v1/health

# API Gateway
curl http://localhost:5000/api/v1/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "tts-service",
  "model": "elevenlabs-tts",
  "supported_languages": 6,
  "languages": ["ta", "en", "te", "ml", "kn", "hi"]
}
```

### Check Full Pipeline

```bash
curl http://localhost:5000/api/v1/system/status
```

## Access the Frontend

Open your browser and navigate to:

```
http://localhost:3000
```

You should see:
- Large red **Record** button
- Real-time audio level meter
- **6 Language Cards** (Tamil, English, Telugu, Malayalam, Kannada, Hindi)
- Pipeline visualization showing: 🎤 Audio → 📝 Sonix → 🤖 Llama → 🔊 ElevenLabs
- Activity logs panel

## Testing the System

### Basic Flow Test

1. Click the red **Record** button
2. Speak in any language (English, Hindi, Tamil, etc.)
3. Release to stop recording (or click again)
4. Watch the pipeline:
   - Transcription appears in ~2-3 seconds
   - All 6 translations appear in ~2-4 seconds
   - All 6 audio files ready in ~3-5 seconds
5. Click **Play** on any language card to listen

### Test Translation Quality

Try these phrases:

**English**:
- "Hello, how are you today?"
- "What is the weather like?"

**Hindi**:
- "नमस्ते, आप कैसे हैं?" (Hello, how are you?)
- "मुझे मदद चाहिए" (I need help)

**Tamil**:
- "வணக்கம், நீங்கள் எப்படி இருக்கிறீர்கள்?" (Hello, how are you?)

Expected: All 6 language translations should appear with realistic accents/voices

### Monitor Real-Time Flow

Check the **Activity Log** at the bottom of the frontend:

```
[14:23:45] Recording started...
[14:23:48] Audio captured (2.5 seconds)
[14:23:50] Sonix STT: "Hello, how are you?"
[14:23:52] Translation started (6 languages)...
[14:23:54] ✓ Tamil translation ready
[14:23:54] ✓ English translation ready
[14:23:54] ✓ Telugu translation ready
[14:23:54] ✓ Malayalam translation ready
[14:23:54] ✓ Kannada translation ready
[14:23:54] ✓ Hindi translation ready
[14:23:58] ✓ All 6 audio files ready!
```

## Troubleshooting

### Issue: "Service not responding" Error

**Solution**: Check if service is running on correct port

```bash
# Check if port is in use
netstat -an | find "5003"  # Windows
lsof -i :5003              # macOS/Linux

# Kill process on port if needed
taskkill /PID <PID> /F     # Windows
kill -9 <PID>              # macOS/Linux
```

### Issue: API Key Error

```
Error: Invalid API key for Anthropic
```

**Solution**: Verify API keys in `.env`:

```bash
# Print first 10 chars to verify (safe)
echo "%TRANSLATION_ANTHROPIC_API_KEY:~0,10%"

# Make sure keys don't have quotes
# CORRECT: TRANSLATION_ANTHROPIC_API_KEY=sk-ant-abc123...
# WRONG:   TRANSLATION_ANTHROPIC_API_KEY="sk-ant-abc123..."
```

### Issue: Audio Quality Issues

**Solution**: Check audio settings in `.env`:

```bash
# Verify audio encoding
AUDIO_SAMPLE_RATE=16000        # Don't change
AUDIO_CHANNELS=1               # Don't change
AUDIO_ENCODING=linear16        # Don't change
```

### Issue: Translation Missing Languages

**Solution**: Verify language codes are correct:

```bash
# Check translation service logs
tail -f logs/realtime-system.log | grep -i translation

# Verify all 6 languages in response
curl http://localhost:5003/api/v1/languages
```

Expected response:
```json
{
  "ta": {"name": "Tamil", "native": "தமிழ்"},
  "en": {"name": "English", "native": "English"},
  "te": {"name": "Telugu", "native": "తెలుగు"},
  "ml": {"name": "Malayalam", "native": "മലയാളം"},
  "kn": {"name": "Kannada", "native": "ಕನ್ನಡ"},
  "hi": {"name": "Hindi", "native": "हिंदी"}
}
```

### Issue: Slow Response Times

**Expected Latencies**:
- ASR (Sonix): 2-3 seconds
- Translation (Llama): 2-4 seconds
- TTS (ElevenLabs): 3-5 seconds
- **Total: 7-12 seconds**

If slower than this:
1. Check internet connection
2. Check API rate limits (you may be throttled)
3. Monitor CPU/memory usage
4. Check service logs: `tail -f logs/realtime-system.log`

## Advanced Configuration

### Using Different LLM Provider

By default, the system uses **Anthropic Claude** (recommended). To switch:

**Option 1: OpenAI GPT-4**

```bash
# In .env
TRANSLATION_PROVIDER=llama
TRANSLATION_ANTHROPIC_API_KEY=
TRANSLATION_OPENAI_API_KEY=sk-proj-your-key-here
TRANSLATION_OPENAI_MODEL=gpt-4
```

**Option 2: HuggingFace Llama 2**

```bash
# In .env
TRANSLATION_PROVIDER=llama
TRANSLATION_ANTHROPIC_API_KEY=
TRANSLATION_HUGGINGFACE_API_KEY=hf_your-token-here
TRANSLATION_HUGGINGFACE_MODEL=meta-llama/Llama-2-7b-chat-hf
```

### Enable Context Caching (Redis)

For conversation continuity:

```bash
# Install Redis
# Windows: https://github.com/microsoftarchive/redis/releases
# macOS: brew install redis
# Linux: apt-get install redis-server

# Start Redis
redis-server

# In .env
REDIS_HOST=localhost
REDIS_PORT=6379
```

### Enable Metrics/Monitoring

```bash
# In .env
ENABLE_METRICS=true
ENABLE_HEALTHCHECKS=true

# Access Prometheus metrics
curl http://localhost:9090/metrics
```

## Stopping the System

### Stop All Services

```bash
# If using automated startup script
Ctrl+C  # In the terminal running the script

# OR if running individually
# Press Ctrl+C in each terminal running a service
```

### Clean Shutdown (Graceful)

```bash
# Send SIGTERM signal
kill -TERM <PID>  # macOS/Linux

# Windows: Use Task Manager or
taskkill /PID <PID>
```

## Production Deployment

### Using Docker

```bash
# Build all services
docker-compose build

# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f translation-service

# Stop all
docker-compose down
```

### Load Testing

```bash
# Simulate 10 concurrent streams
python scripts/load_test.py \
  --concurrent_streams 10 \
  --duration_seconds 60 \
  --language_mix random
```

### Performance Monitoring

```bash
# Monitor real-time metrics
watch 'curl -s http://localhost:9090/api/v1/metrics | jq .pipeline'

# Export metrics
prometheus_url="http://localhost:9090"
curl "${prometheus_url}/metrics" > metrics.txt
```

## Next Steps

1. ✅ All 4 services running
2. ✅ Frontend accessible
3. 📝 Try real translations
4. 🔧 Integrate with your app
5. 🚀 Deploy to production

## Support & Documentation

- **Frontend Documentation**: [web/ARCHITECTURE-REALTIME.md](../web/ARCHITECTURE-REALTIME.md)
- **API Specifications**: [config/api-config-realtime.yml](../config/api-config-realtime.yml)
- **Service Ports**: 5000 (Gateway), 5002 (ASR), 5003 (Translation), 5005 (TTS)
- **Frontend URL**: http://localhost:3000

## Key Statistics

| Metric | Value |
|--------|-------|
| Supported Languages | 6 (Tamil, English, Telugu, Malayalam, Kannada, Hindi) |
| Concurrent Streams | Up to 10 |
| Typical Latency | 10-15 seconds |
| Max Timeout | 30 seconds |
| Audio Sample Rate | 16 kHz (mono) |
| Format Support | WAV, MP3, Linear PCM |

---

**System Version**: 1.0.0  
**Last Updated**: 2024  
**Status**: Production Ready
