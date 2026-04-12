# TTS Service - Text-to-Speech synthesis for Indian Languages
# Supports: Tamil, English, Telugu, Malayalam, Kannada, Hindi

import os
import sys
import logging
import time
import base64
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Add root to path
root_dir = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(root_dir))

# ============ CONFIGURATION ============

SERVICE_NAME = "tts-service"
SERVICE_PORT = int(os.getenv("TTS_PORT", 5005))
SERVICE_HOST = os.getenv("SERVER_HOST", "0.0.0.0")

# Supported Indian Languages (6 languages)
SUPPORTED_LANGUAGES = {
    'ta': {'name': 'Tamil', 'native': 'தமிழ்'},
    'en': {'name': 'English', 'native': 'English'},
    'te': {'name': 'Telugu', 'native': 'తెలుగు'},
    'ml': {'name': 'Malayalam', 'native': 'മലയാളം'},
    'kn': {'name': 'Kannada', 'native': 'ಕನ್ನಡ'},
    'hi': {'name': 'Hindi', 'native': 'हिंदी'}
}

# Default voices for each language
VOICE_MAPPING = {
    'ta': {'voice_id': 'tamil-female-1', 'name': 'Priya', 'gender': 'female'},
    'en': {'voice_id': 'english-female-1', 'name': 'Aria', 'gender': 'female'},
    'te': {'voice_id': 'telugu-female-1', 'name': 'Divya', 'gender': 'female'},
    'ml': {'voice_id': 'malayalam-female-1', 'name': 'Anitha', 'gender': 'female'},
    'kn': {'voice_id': 'kannada-female-1', 'name': 'Aadhya', 'gender': 'female'},
    'hi': {'voice_id': 'hindi-female-1', 'name': 'Anjali', 'gender': 'female'}
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(SERVICE_NAME)

# ============ MODELS ============

class Voice(BaseModel):
    id: str
    name: str
    language: str
    native_language: str
    gender: str
    age_bracket: str

class SynthesizeRequest(BaseModel):
    stream_id: str
    text: str
    language: str
    voice_id: Optional[str] = None
    speed: Optional[float] = 1.0
    pitch: Optional[float] = 0.0

class SynthesizeResponse(BaseModel):
    stream_id: str
    audio_bytes: str  # Base64 encoded
    language: str
    voice_id: str
    duration_ms: int
    model: str
    timestamp: str

class HealthResponse(BaseModel):
    status: str
    service: str
    model: str
    supported_languages: int
    languages: List[str]

# ============ FASTAPI APP ============

app = FastAPI(
    title="TTS Service - Indian Languages",
    description="Text-to-speech synthesis for 6 Indian languages using ElevenLabs",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ TTS ENGINE ============

class ElevenLabsTTSEngine:
    """ElevenLabs TTS engine for Indian language audio synthesis"""
    
    def __init__(self):
        """Initialize TTS engine"""
        self.api_key = os.getenv("TTS_ELEVENLABS_API_KEY")
        self.api_url = os.getenv("TTS_ELEVENLABS_API_URL", "https://api.elevenlabs.io/v1")
        self.provider = "elevenlabs"
        self._validate_configuration()
        logger.info("ElevenLabs TTS Engine initialized")
    
    def _validate_configuration(self):
        """Validate that required API credentials are configured"""
        if not self.api_key:
            raise RuntimeError("TTS_ELEVENLABS_API_KEY environment variable not set")
        if not self.api_key.startswith("sk_"):
            raise RuntimeError("Invalid TTS_ELEVENLABS_API_KEY format (should start with 'sk_')")
    
    def synthesize(self, text: str, language: str, voice_id: Optional[str] = None, speed: float = 1.0) -> tuple:
        """
        Synthesize text to speech using ElevenLabs API
        
        Supports:
        - Tamil (ta), English (en), Telugu (te), Malayalam (ml), Kannada (kn), Hindi (hi)
        """
        if not text or not text.strip():
            raise ValueError("Text to synthesize cannot be empty")
        
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}")
        
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Speed must be between 0.5 and 2.0")
        
        try:
            return self._synthesize_elevenlabs(text, language, voice_id, speed)
        except Exception as e:
            logger.error(f"TTS synthesis failed for {language}: {str(e)}")
            raise
    
    def _synthesize_elevenlabs(self, text: str, language: str, voice_id: Optional[str], speed: float) -> tuple:
        """Call ElevenLabs API to synthesize speech"""
        try:
            import requests
            from elevenlabs import ElevenLabs, Voice
        except ImportError:
            raise RuntimeError("elevenlabs package not installed. Install: pip install elevenlabs")
        
        try:
            client = ElevenLabs(api_key=self.api_key)
            voice_mapping = VOICE_MAPPING.get(language)
            if not voice_mapping:
                voice_mapping = VOICE_MAPPING['en']
            
            voice = Voice(
                voice_id=voice_id or voice_mapping['voice_id'],
                settings={"stability": 0.75, "similarity_boost": 0.75}
            )
            
            audio = client.generate(
                text=text,
                voice=voice,
                model="eleven_monolingual_v1",
                stream=False
            )
            
            audio_bytes = b''.join(audio)
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            duration_ms = int((len(text.split()) * 150) / speed)
            
            return audio_base64, duration_ms
        except Exception as e:
            logger.error(f"ElevenLabs API error: {str(e)}")
            raise RuntimeError(f"Failed to synthesize with ElevenLabs: {str(e)}")

# Start TTS engine
tts_engine = ElevenLabsTTSEngine()

# ============ STARTUP/SHUTDOWN ============

@app.on_event("startup")
async def startup_event():
    logger.info(f"\n{'='*60}")
    logger.info(f"{SERVICE_NAME} starting up...")
    logger.info(f"{'='*60}")
    logger.info(f"Provider: ElevenLabs")
    logger.info(f"Supported Languages: {list(SUPPORTED_LANGUAGES.keys())}")
    logger.info(f"Swagger UI: http://{SERVICE_HOST}:{SERVICE_PORT}/api/docs")
    logger.info(f"{'='*60}\n")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"\n{SERVICE_NAME} shutting down...")

# ============ HEALTH CHECK ============

@app.get("/api/v1/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        service="tts-service",
        model="elevenlabs-tts",
        supported_languages=len(SUPPORTED_LANGUAGES),
        languages=list(SUPPORTED_LANGUAGES.keys())
    )

# ============ SYNTHESIS ENDPOINT ============

@app.post("/api/v1/synthesize", response_model=SynthesizeResponse)
async def synthesize(request: SynthesizeRequest) -> SynthesizeResponse:
    """
    Convert text to speech for Indian languages
    
    Supports:
    - Tamil (ta)
    - English (en)
    - Telugu (te)
    - Malayalam (ml)
    - Kannada (kn)
    - Hindi (hi)
    
    Returns:
        Base64-encoded audio data
    """
    
    start_time = time.time()
    
    try:
        # Validate language
        if request.language not in SUPPORTED_LANGUAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported language: {request.language}"
            )
        
        # Get voice
        voice_config = VOICE_MAPPING.get(request.language, VOICE_MAPPING['en'])
        voice_id = request.voice_id or voice_config['voice_id']
        
        logger.info(f"[{request.stream_id}] Synthesizing {len(request.text)} chars in {request.language}")
        
        # Synthesize audio
        audio_base64, duration_ms = tts_engine.synthesize(
            request.text,
            request.language,
            voice_id,
            request.speed
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        logger.info(f"[{request.stream_id}] Audio generated: {duration_ms}ms")
        
        return SynthesizeResponse(
            stream_id=request.stream_id,
            audio_bytes=audio_base64,
            language=request.language,
            voice_id=voice_id,
            duration_ms=duration_ms,
            model="elevenlabs-tts",
            timestamp=datetime.utcnow().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============ VOICE ENDPOINTS ============

@app.get("/api/v1/voices")
async def get_voices(language: Optional[str] = None) -> List[Voice]:
    """Get available voices"""
    
    voices = []
    
    for lang_code, lang_info in SUPPORTED_LANGUAGES.items():
        if language and language != lang_code:
            continue
        
        voice_config = VOICE_MAPPING.get(lang_code, {})
        voices.append(Voice(
            id=voice_config.get('voice_id', f'{lang_code}-voice'),
            name=voice_config.get('name', 'Default'),
            language=lang_code,
            native_language=lang_info['native'],
            gender=voice_config.get('gender', 'female'),
            age_bracket="30s"
        ))
    
    return voices

@app.get("/api/v1/voices/{language_code}")
async def get_language_voices(language_code: str) -> List[Voice]:
    """Get voices for a specific language"""
    
    if language_code not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=404,
            detail=f"Language {language_code} not supported"
        )
    
    lang_info = SUPPORTED_LANGUAGES[language_code]
    voice_config = VOICE_MAPPING.get(language_code, {})
    
    return [
        Voice(
            id=voice_config.get('voice_id', f'{language_code}-voice'),
            name=voice_config.get('name', 'Default'),
            language=language_code,
            native_language=lang_info['native'],
            gender=voice_config.get('gender', 'female'),
            age_bracket="30s"
        )
    ]

# ============ LANGUAGE ENDPOINTS ============

@app.get("/api/v1/languages")
async def get_languages() -> Dict:
    """Get supported languages"""
    
    languages = {}
    for code, info in SUPPORTED_LANGUAGES.items():
        languages[code] = {
            'name': info['name'],
            'native': info['native']
        }
    
    return languages

@app.get("/api/v1/languages/{language_code}")
async def get_language_info(language_code: str) -> Dict:
    """Get information about a specific language"""
    
    if language_code not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=404,
            detail=f"Language {language_code} not supported"
        )
    
    info = SUPPORTED_LANGUAGES[language_code]
    return {
        'code': language_code,
        'name': info['name'],
        'native': info['native']
    }

# ============ STATUS ENDPOINTS ============

@app.get("/api/v1/stats")
async def get_stats():
    """Get service statistics"""
    
    return {
        "service": SERVICE_NAME,
        "provider": "elevenlabs",
        "supported_languages": len(SUPPORTED_LANGUAGES),
        "languages": list(SUPPORTED_LANGUAGES.keys()),
        "uptime_seconds": time.time(),
        "timestamp": datetime.utcnow().isoformat()
    }

# ============ STARTUP ============

if __name__ == "__main__":
    logger.info(f"Starting {SERVICE_NAME} on {SERVICE_HOST}:{SERVICE_PORT}")
    
    uvicorn.run(
        app,
        host=SERVICE_HOST,
        port=SERVICE_PORT,
        log_level="info"
    )
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
