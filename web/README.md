# 🎤 Multimodal Voice Cloning - Frontend

A modern, interactive web interface for the multimodal voice translation system. Record audio, transcribe, translate, and synthesize speech in real-time.

## 🚀 Quick Start

### Option 1: Python HTTP Server (Recommended)

```powershell
cd web
python -m http.server 3000
```

Then visit: **http://localhost:3000**

### Option 2: Node.js (if installed)

```powershell
cd web
npm install
npm run serve
```

Visit: **http://localhost:3000**

### Option 3: Use Live Server Extension (VS Code)

Right-click `index.html` → "Open with Live Server"

## 📋 Features

### 1. **Voice Recording & Transcription** 🎙️
- Record audio directly from your microphone
- Real-time audio level meter
- Transcribe to text using Sonix API
- Support for 8 languages

### 2. **Multi-Language Translation** 🌐
- Translate transcribed text to multiple languages (Spanish, French, German, Japanese, Portuguese)
- Real-time translation results display
- Powered by Claude AI

### 3. **Text-to-Speech** 🔊
- Generate natural speech from any text
- Support for 5 languages
- Download or play generated audio
- Powered by ElevenLabs

### 4. **Real-Time Streaming** ⚡
- End-to-end pipeline simulation
- Audio → Transcription → Translation → Speech → Broadcast
- Live activity logs

### 5. **Service Status Dashboard** 📊
- Real-time health checks for all services
- Visual indicators for service availability
- Automatic periodic status updates

## 🏗️ Architecture

```
Frontend (index.html + CSS + JS)
        ↓
    ┌───┴────────────────────────┐
    ↓                            ↓
API Gateway (5000)          Audio Ingestion (5001)
    ↓                            ↓
    ├─→ ASR Service (5002)
    ├─→ Translation (5003)
    ├─→ Moderation (5004)
    ├─→ TTS Service (5005)
    └─→ Channels (5006)
```

## 🎯 Usage

### Record and Transcribe

1. Click **"Start Recording"** button
2. Speak into the microphone
3. Click **"Stop Recording"** when done
4. Click **"Transcribe"** to convert speech to text
5. Text appears in the "Transcription" panel

### Translate

1. After transcription, select target languages (checkboxes)
2. Click **"Translate"**
3. See translations in the middle panel

### Generate Speech

1. Enter text in the "Text to Speak" field
2. Select target language
3. Click **"Generate Speech"**
4. Audio player appears with your generated speech

### Monitor Streams

1. Click **"Start Streaming"** to see the full pipeline
2. Watch the logs as audio flows through all services
3. Click **"Stop Streaming"** to halt

## 🔧 Configuration

Services must be running before using the frontend:

```powershell
# From project root, in separate terminals:

# Terminal 1: API Gateway (5000)
.venv\Scripts\python -m uvicorn services.api-gateway.src.main:app --port 5000

# Terminal 2: Audio Ingestion (5001)
.venv\Scripts\python -m uvicorn services.audio-ingestion-service.src.main:app --port 5001

# Terminal 3: ASR (5002)
.venv\Scripts\python -m uvicorn services.asr-service.src.main:app --port 5002

# Terminal 4: Translation (5003)
.venv\Scripts\python -m uvicorn services.translation-service.src.main:app --port 5003

# Terminal 5: TTS (5005)
.venv\Scripts\python -m uvicorn services.tts-service.src.main:app --port 5005
```

Or use the automated startup:
```powershell
scripts/start-all.bat
```

## 📡 API Endpoints Used

| Endpoint | Service | Purpose |
|----------|---------|---------|
| `POST /api/v1/transcribe` | ASR (5002) | Convert audio to text |
| `POST /api/v1/translate` | Translation (5003) | Translate text |
| `POST /api/v1/synthesize` | TTS (5005) | Generate speech from text |
| `GET /api/v1/health` | All Services | Health check |

## 🎨 UI Components

### Layout
- **Left Panel**: Voice input & transcription
- **Middle Panel**: Translation settings & results
- **Right Panel**: Text-to-speech controls
- **Bottom Panel**: Streaming pipeline logs

### Status Indicators
- 🟢 Green = Service online
- 🟡 Yellow = Unknown
- 🔴 Red = Service offline

### Buttons
- **Primary** (Blue): Main actions (Record, Transcribe)
- **Secondary** (Purple): Secondary actions (Translate, Synthesize)
- **Success** (Green): Start/streaming actions

## 🐛 Troubleshooting

### "Services Offline" Warning
- Ensure all services are running on ports 5000-5006
- Check service status at bottom of page
- Open browser console (F12) for error details

### Audio Recording Not Working
- Allow microphone permission when browser asks
- Check if microphone appears in browser settings
- Refresh page and try again

### No Transcription Result
- Ensure ASR service is running on port 5002
- Verify audio was recorded (check audio meter)
- Check browser console for error messages

### Translation/TTS Not Working
- Verify all services are started
- Check that API keys are configured in `.env`
- Look for CORS errors in browser console

## 📝 Browser Support

- ✅ Chrome/Chromium (Latest)
- ✅ Firefox (Latest)
- ✅ Safari (Latest)
- ✅ Edge (Latest)

**Required Features:**
- Web Audio API
- MediaRecorder API
- Fetch API
- ES6+ JavaScript

## 🔐 Security Notes

- Frontend communicates directly with services via CORS
- API credentials NOT stored in frontend (backend only)
- Audio files sent as base64 over HTTPS (in production)
- WebSocket for real-time streaming (upgrade to WSS in production)

## 📚 Additional Resources

- [SERVICES_STARTUP_GUIDE.md](../SERVICES_STARTUP_GUIDE.md) - How to run services
- [QUICKSTART.md](../QUICKSTART.md) - Project setup guide
- [Swagger UI](http://localhost:5000/api/docs) - Interactive API documentation
- [Architecture](../ARCHITECTURE.md) - System design details

## 🚀 Deployment

### Development
```bash
python -m http.server 3000
```

### Production
```bash
# Use a production HTTP server
npm install -g http-server
http-server --cors --port 3000
```

Or serve from your backend:
```bash
# Add to FastAPI app
app = FastAPI(static_files={"/": "web"})
```

## 📊 Performance Tips

1. **Reduce audio quality** for faster transcription
2. **Batch translations** instead of translating each message
3. **Cache translations** to avoid duplicate requests
4. **Optimize audio format** (use compressed formats)

## 🎓 Learning Resources

- [Web Audio API Docs](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API)
- [MediaRecorder API](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)
- [WebSocket Guide](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [CORS Explanation](https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS)

## 📄 File Structure

```
web/
├── index.html          # Main HTML page
├── style.css           # Styling
├── app.js              # JavaScript logic
├── package.json        # Dependencies & scripts
└── README.md           # This file
```

## ✅ Next Steps

1. ✅ Start all backend services
2. ✅ Run the frontend HTTP server
3. ✅ Open http://localhost:3000
4. ✅ Grant microphone permission
5. ✅ Start recording and translating!

---

**Status**: 🟢 Ready for use!

Built with ❤️ for real-time voice translation
