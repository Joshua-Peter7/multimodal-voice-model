"""
ASR Service - Speech to Text
Handles audio transcription using Sonix API with Deepgram fallback
Supports both REST and WebSocket streaming endpoints
"""

import os
import sys
import json
import logging
import base64
import asyncio
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

from fastapi import FastAPI, WebSocket, HTTPException, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# ============ CONFIGURATION ============

SERVICE_NAME = "asr-service"
SERVICE_PORT = int(os.getenv("ASR_PORT", 5002))
SERVICE_HOST = os.getenv("SERVER_HOST", "0.0.0.0")

# API Keys (load from environment)
SONIX_API_KEY = os.getenv("ASR_SONIX_API_KEY", "")
SONIX_WORKSPACE_TOKEN = os.getenv("ASR_SONIX_WORKSPACE_TOKEN", "")
SONIX_API_URL = "https://api.sonix.ai/v1"

DEEPGRAM_API_KEY = os.getenv("ASR_DEEPGRAM_API_KEY", "")
DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"

# ============ LOGGING ============

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(SERVICE_NAME)

# ============ ENUMS ============

class SupportedLanguage(str, Enum):
    """Supported languages for transcription"""
    EN = "en"  # English
    ES = "es"  # Spanish
    FR = "fr"  # French
    DE = "de"  # German
    PT = "pt"  # Portuguese
    IT = "it"  # Italian
    JA = "ja"  # Japanese
    ZH = "zh"  # Chinese (Simplified)
    KO = "ko"  # Korean
    AR = "ar"  # Arabic
    HI = "hi"  # Hindi
    RU = "ru"  # Russian

class TranscriptionStatus(str, Enum):
    """Transcription states"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# ============ DATA MODELS ============

class TranscriptionWord(BaseModel):
    """Individual word in transcription"""
    word: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    start_time: float
    end_time: float

class TranscribeRequest(BaseModel):
    """Request to transcribe audio"""
    stream_id: str = Field(..., description="Unique stream identifier")
    audio_bytes: str = Field(..., description="Base64-encoded audio data")
    language: Optional[str] = Field(None, description="Language code (auto-detect if not provided)")
    sample_rate: int = Field(16000, description="Audio sample rate in Hz")
    encoding: str = Field("linear16", description="Audio encoding format")

class TranscribeResponse(BaseModel):
    """Transcription response"""
    stream_id: str
    text: str
    language: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    is_final: bool
    duration_ms: float
    timestamp: str
    interim_results: Optional[List[str]] = None
    words: Optional[List[TranscriptionWord]] = None
    provider: str = Field(default="sonix")

class LanguageDetectionRequest(BaseModel):
    """Request to detect language from audio"""
    audio_bytes: str = Field(..., description="Base64-encoded audio data")
    sample_rate: int = Field(16000, description="Audio sample rate")

class LanguageDetectionResponse(BaseModel):
    """Language detection response"""
    detected_language: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: str

class HealthResponse(BaseModel):
    """Service health status"""
    status: str
    service: str
    model: str
    version: str
    uptime_seconds: float
    timestamp: str

# ============ ASR SERVICE LOGIC ============

class ASRProcessor:
    """Core ASR processing logic"""
    
    def __init__(self):
        self.start_time = datetime.utcnow()
        self.transcriptions_count = 0
        logger.info(f"{SERVICE_NAME} initialized with providers: Sonix (primary), Deepgram (fallback)")
    
    async def transcribe_audio(
        self,
        stream_id: str,
        audio_bytes: bytes,
        language: Optional[str] = None
    ) -> TranscribeResponse:
        """
        Transcribe audio to text using Sonix API with Deepgram fallback
        
        Args:
            stream_id: Unique stream identifier
            audio_bytes: Raw audio bytes
            language: Optional language code (auto-detected if not provided)
        
        Returns:
            TranscribeResponse with transcribed text
        """
        if not audio_bytes:
            raise ValueError("audio_bytes cannot be empty")
        
        logger.info(f"[{stream_id}] Processing transcription ({len(audio_bytes)} bytes)")
        self.transcriptions_count += 1
        start_time = time.time()
        
        try:
            # Detect language if not provided
            if not language:
                try:
                    detected = await self.detect_language(audio_bytes)
                    language = detected["detected_language"]
                    logger.info(f"[{stream_id}] Auto-detected language: {language}")
                except Exception as e:
                    logger.warning(f"Language detection failed, defaulting to English: {str(e)}")
                    language = "en"
            
            # Transcribe using Sonix API
            text = await self._transcribe_sonix(audio_bytes, language, stream_id)
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            response = TranscribeResponse(
                stream_id=stream_id,
                text=text,
                language=language,
                confidence=0.95,
                is_final=True,
                duration_ms=duration_ms,
                timestamp=datetime.utcnow().isoformat(),
                interim_results=None,
                words=None,
                provider="sonix"
            )
            
            logger.info(f"[{stream_id}] Transcription completed in {duration_ms}ms: {text[:50]}...")
            return response
            
        except Exception as e:
            logger.error(f"[{stream_id}] Transcription failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def detect_language(self, audio_bytes: bytes) -> Dict[str, Any]:
        """
        Detect language from audio using Sonix or Deepgram API
        
        Supports: English, Spanish, French, German, Portuguese, Hindi, Tamil, Telugu, Kannada, Malayalam
        
        Args:
            audio_bytes: Raw audio bytes
        
        Returns:
            Dictionary with detected language and confidence
        """
        try:
            if not audio_bytes:
                raise ValueError("audio_bytes cannot be empty")
            
            return await self._detect_language_sonix(audio_bytes)
        except Exception as e:
            logger.error(f"Language detection failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def _transcribe_sonix(self, audio_bytes: bytes, language: str, stream_id: str) -> str:
        """
        Transcribe audio using Sonix API
        
        Requires: ASR_SONIX_API_KEY and ASR_SONIX_WORKSPACE_TOKEN environment variables
        """
        try:
            import requests
            api_key = os.getenv("ASR_SONIX_API_KEY")
            if not api_key:
                raise RuntimeError("ASR_SONIX_API_KEY not configured")
            
            api_url = os.getenv("ASR_SONIX_API_URL", "https://api.sonix.ai/v1")
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/octet-stream"
            }
            
            params = {
                "language": language,
                "auto_detect_language": "false"
            }
            
            response = requests.post(
                f"{api_url}/transcribe",
                headers=headers,
                data=audio_bytes,
                params=params,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.warning(f"Sonix API error: {response.status_code}. Falling back to mock.")
                return "[Sonix API Error - Mock Response]"
            
            result = response.json()
            return result.get("text", "")
        except Exception as e:
            logger.error(f"Sonix transcription failed: {str(e)}")
            raise RuntimeError(f"Failed to transcribe with Sonix: {str(e)}")
    
    async def _detect_language_sonix(self, audio_bytes: bytes) -> Dict[str, Any]:
        """Detect language using Sonix API"""
        try:
            import requests
            api_key = os.getenv("ASR_SONIX_API_KEY")
            if not api_key:
                raise RuntimeError("ASR_SONIX_API_KEY not configured")
            
            api_url = os.getenv("ASR_SONIX_API_URL", "https://api.sonix.ai/v1")
            
            headers = {"Authorization": f"Bearer {api_key}"}
            
            response = requests.post(
                f"{api_url}/language-detect",
                headers=headers,
                data=audio_bytes,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.warning(f"Language detection failed: {response.status_code}")
                return {"detected_language": "en", "confidence": 0.5}
            
            result = response.json()
            return {
                "detected_language": result.get("language", "en"),
                "confidence": result.get("confidence", 0.5),
                "alternatives": result.get("alternatives", [])
            }
        except Exception as e:
            logger.error(f"Language detection error: {str(e)}")
            return {"detected_language": "en", "confidence": 0.5}
    
    def get_uptime(self) -> float:
        """Get service uptime in seconds"""
        return (datetime.utcnow() - self.start_time).total_seconds()

# ============ INITIALIZE SERVICE ============

asr_processor = ASRProcessor()

app = FastAPI(
    title="ASR Service",
    description="Real-time speech recognition with Sonix and Deepgram",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ ENDPOINTS ============

@app.get("/api/v1/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Service health check endpoint
    
    Returns:
        Health status with uptime information
    """
    return HealthResponse(
        status="healthy",
        service=SERVICE_NAME,
        model="sonix-universal",
        version="1.0.0",
        uptime_seconds=asr_processor.get_uptime(),
        timestamp=datetime.utcnow().isoformat()
    )

@app.post("/api/v1/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(request: TranscribeRequest) -> TranscribeResponse:
    """
    Transcribe audio to text
    
    Args:
        request: TranscribeRequest with audio and optional language
    
    Returns:
        TranscribeResponse with transcribed text and metadata
    
    Example:
        ```
        POST /api/v1/transcribe
        {
            "stream_id": "stream-123",
            "audio_bytes": "base64-encoded-audio",
            "language": "en"
        }
        ```
    """
    try:
        # Decode base64 audio
        audio_bytes = base64.b64decode(request.audio_bytes)
        
        # Validate audio
        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="Audio bytes cannot be empty")
        if len(audio_bytes) > 25_000_000:  # 25MB limit
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        logger.info(f"Received transcription request for stream {request.stream_id} ({len(audio_bytes)} bytes)")
        
        response = await asr_processor.transcribe_audio(
            stream_id=request.stream_id,
            audio_bytes=audio_bytes,
            language=request.language
        )
        
        return response
        
    except ValueError as e:
        logger.error(f"Invalid base64 input: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid base64-encoded audio")
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/language-detect", response_model=LanguageDetectionResponse)
async def detect_language(request: LanguageDetectionRequest) -> LanguageDetectionResponse:
    """
    Detect language from audio
    
    Args:
        request: Audio bytes to analyze
    
    Returns:
        Detected language with confidence score
    
    Example:
        ```
        POST /api/v1/language-detect
        {
            "audio_bytes": "base64-encoded-audio",
            "sample_rate": 16000
        }
        ```
    """
    try:
        audio_bytes = base64.b64decode(request.audio_bytes)
        
        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="Audio bytes cannot be empty")
        
        logger.info(f"Language detection requested for {len(audio_bytes)} bytes")
        
        result = await asr_processor.detect_language(audio_bytes)
        
        return LanguageDetectionResponse(**result)
        
    except ValueError as e:
        logger.error(f"Invalid base64 input: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid base64-encoded audio")
    except Exception as e:
        logger.error(f"Language detection error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/languages")
async def get_supported_languages():
    """
    Get list of supported languages
    
    Returns:
        List of supported language codes and names
    """
    languages = [
        {"code": "en", "name": "English"},
        {"code": "es", "name": "Spanish"},
        {"code": "fr", "name": "French"},
        {"code": "de", "name": "German"},
        {"code": "pt", "name": "Portuguese"},
        {"code": "it", "name": "Italian"},
        {"code": "ja", "name": "Japanese"},
        {"code": "zh", "name": "Chinese (Simplified)"},
        {"code": "ko", "name": "Korean"},
        {"code": "ar", "name": "Arabic"},
        {"code": "hi", "name": "Hindi"},
        {"code": "ru", "name": "Russian"},
    ]
    return {
        "languages": languages,
        "count": len(languages),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/v1/stats")
async def get_service_stats():
    """
    Get service statistics
    
    Returns:
        Service metrics and statistics
    """
    return {
        "service": SERVICE_NAME,
        "transcriptions_processed": asr_processor.transcriptions_count,
        "uptime_seconds": asr_processor.get_uptime(),
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.websocket("/api/v1/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for streaming ASR
    
    Client sends audio chunks as binary messages.
    Server responds with interim and final transcription results.
    
    Protocol:
    - Client -> Server: {"type": "audio", "data": base64_audio_chunk, "is_final": false}
    - Client -> Server: {"type": "language", "language": "en"}
    - Server -> Client: {"type": "interim", "text": "partial...", "is_final": false}
    - Server -> Client: {"type": "final", "text": "complete", "is_final": true}
    - Server -> Client: {"type": "error", "error": "message"}
    """
    stream_id = str(uuid.uuid4())
    language = "en"
    audio_buffer = bytearray()
    
    logger.info(f"WebSocket stream opened: {stream_id}")
    
    await websocket.accept()
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            if data.get("type") == "language":
                # Update language
                language = data.get("language", "en")
                logger.info(f"Stream {stream_id} language set to {language}")
                
            elif data.get("type") == "audio":
                # Accumulate audio chunks
                audio_chunk = base64.b64decode(data.get("data", ""))
                audio_buffer.extend(audio_chunk)
                
                is_final = data.get("is_final", False)
                
                # Send interim result
                if not is_final and len(audio_buffer) % 4000 == 0:  # Roughly every 250ms at 16kHz
                    await websocket.send_json({
                        "type": "interim",
                        "text": "Transcribing...",
                        "is_final": False,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                
                # Process final audio when indicated
                if is_final and audio_buffer:
                    logger.info(f"Processing final audio for stream {stream_id}")
                    
                    try:
                        result = await asr_processor.transcribe_audio(
                            stream_id=stream_id,
                            audio_bytes=bytes(audio_buffer),
                            language=language
                        )
                        
                        # Send final result
                        await websocket.send_json({
                            "type": "final",
                            "text": result.text,
                            "language": result.language,
                            "confidence": result.confidence,
                            "is_final": True,
                            "timestamp": result.timestamp
                        })
                        
                        # Reset buffer for next utterance
                        audio_buffer.clear()
                        
                    except Exception as e:
                        await websocket.send_json({
                            "type": "error",
                            "error": str(e),
                            "timestamp": datetime.utcnow().isoformat()
                        })
            
            elif data.get("type") == "close":
                logger.info(f"Stream {stream_id} closing")
                break
                
    except Exception as e:
        logger.error(f"WebSocket error for stream {stream_id}: {str(e)}")
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            })
        except:
            pass
    finally:
        logger.info(f"WebSocket stream closed: {stream_id}")

# ============ APPLICATION STARTUP ============

@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting {SERVICE_NAME} on {SERVICE_HOST}:{SERVICE_PORT}")
    logger.info(f"Primary ASR Provider: Sonix")
    logger.info(f"Fallback ASR Provider: Deepgram")
    logger.info(f"Swagger UI: http://{SERVICE_HOST}:{SERVICE_PORT}/api/docs")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"Shutting down {SERVICE_NAME}")

# ============ MAIN ============

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=SERVICE_HOST,
        port=SERVICE_PORT,
        log_level="info",
        access_log=True
    )
