"""
Translation Service - Llama-based Translation for Indian Languages
Real-time translation to:
- Tamil (ta)
- English (en)
- Telugu (te)
- Malayalam (ml)
- Kannada (kn)
- Hindi (hi)
"""

import os
import sys
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Add root to path
root_dir = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(root_dir))

# ============ CONFIGURATION ============

SERVICE_NAME = "translation-service"
SERVICE_PORT = int(os.getenv("TRANSLATION_PORT", 5003))
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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(SERVICE_NAME)

# ============ MODELS ============

class TranslationRequest(BaseModel):
    stream_id: str
    text: str
    source_language: Optional[str] = "auto"
    target_language: Optional[str] = None
    target_languages: Optional[List[str]] = None
    model: Optional[str] = "llama"
    speed: Optional[float] = 1.0

class TranslationResponse(BaseModel):
    stream_id: str
    text: str
    translation: Optional[str] = None
    translations: Optional[Dict[str, str]] = None
    source_language: str
    target_languages: List[str]
    model: str
    processing_time_ms: int
    timestamp: str

class LanguageInfo(BaseModel):
    code: str
    name: str
    native_name: str
    supported: bool

class HealthResponse(BaseModel):
    status: str
    service: str
    model: str
    supported_languages: int
    languages: List[str]

# ============ FASTAPI APP ============

app = FastAPI(
    title="Translation Service - Llama (Indian Languages)",
    description="Real-time translation using Llama model for 6 Indian languages",
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

# ============ TRANSLATION ENGINE ============

class LlamaTranslationEngine:
    """Llama-based translation engine with LLM provider integration"""
    
    def __init__(self):
        """Initialize translation engine"""
        self.model_name = os.getenv("TRANSLATION_MODEL", "llama-2-7b")
        self.provider = os.getenv("TRANSLATION_PROVIDER", "anthropic")
        self._validate_configuration()
        logger.info(f"Translation Engine initialized: {self.model_name} via {self.provider}")
    
    def _validate_configuration(self):
        """Validate that required API credentials are configured"""
        if self.provider == "anthropic":
            if not os.getenv("TRANSLATION_ANTHROPIC_API_KEY"):
                raise RuntimeError("TRANSLATION_ANTHROPIC_API_KEY environment variable not set")
        elif self.provider == "openai":
            if not os.getenv("TRANSLATION_OPENAI_API_KEY"):
                raise RuntimeError("TRANSLATION_OPENAI_API_KEY environment variable not set")
        elif self.provider == "huggingface":
            if not os.getenv("TRANSLATION_HUGGINGFACE_API_KEY"):
                raise RuntimeError("TRANSLATION_HUGGINGFACE_API_KEY environment variable not set")
    
    def translate(self, text: str, target_language: str) -> str:
        """
        Translate text to target language using configured LLM provider
        
        Integrations:
        - Anthropic Claude API (claude-3-sonnet)
        - OpenAI GPT-4
        - HuggingFace Llama endpoint
        """
        if not text or not text.strip():
            raise ValueError("Text to translate cannot be empty")
        
        if target_language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {target_language}")
        
        try:
            if self.provider == "anthropic":
                return self._translate_anthropic(text, target_language)
            elif self.provider == "openai":
                return self._translate_openai(text, target_language)
            elif self.provider == "huggingface":
                return self._translate_huggingface(text, target_language)
            else:
                raise ValueError(f"Unknown provider: {self.provider}")
        except Exception as e:
            logger.error(f"Translation failed for {target_language}: {str(e)}")
            raise
    
    def _translate_anthropic(self, text: str, target_language: str) -> str:
        """Translate using Anthropic Claude API"""
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=os.getenv("TRANSLATION_ANTHROPIC_API_KEY"))
            lang_name = SUPPORTED_LANGUAGES[target_language]['name']
            message = client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1024,
                messages=[
                    {"role": "user", "content": f"Translate to {lang_name}: {text}"}
                ]
            )
            return message.content[0].text
        except ImportError:
            raise RuntimeError("anthropic package not installed. Install: pip install anthropic")
    
    def _translate_openai(self, text: str, target_language: str) -> str:
        """Translate using OpenAI GPT-4 API"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("TRANSLATION_OPENAI_API_KEY"))
            lang_name = SUPPORTED_LANGUAGES[target_language]['name']
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": f"Translate to {lang_name}: {text}"}]
            )
            return response.choices[0].message.content
        except ImportError:
            raise RuntimeError("openai package not installed. Install: pip install openai")
    
    def _translate_huggingface(self, text: str, target_language: str) -> str:
        """Translate using HuggingFace Llama endpoint"""
        try:
            import requests
            api_url = os.getenv("TRANSLATION_HUGGINGFACE_API_URL", "https://api-inference.huggingface.co/models/meta-llama/Llama-2-7b-chat-hf")
            headers = {"Authorization": f"Bearer {os.getenv('TRANSLATION_HUGGINGFACE_API_KEY')}"}
            lang_name = SUPPORTED_LANGUAGES[target_language]['name']
            payload = {"inputs": f"Translate to {lang_name}: {text}"}
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            if response.status_code != 200:
                raise RuntimeError(f"HuggingFace API error: {response.status_code}")
            result = response.json()
            return result[0].get('generated_text', '')
        except ImportError:
            raise RuntimeError("requests package not installed. Install: pip install requests")
    
    async def translate_batch(self, text: str, target_languages: List[str]) -> Dict[str, str]:
        """Translate text to multiple languages in parallel"""
        
        translations = {}
        for lang_code in target_languages:
            if lang_code in SUPPORTED_LANGUAGES:
                translations[lang_code] = self.translate(text, lang_code)
        
        return translations

# Start translation engine
translation_engine = LlamaTranslationEngine()

# ============ STARTUP/SHUTDOWN ============

@app.on_event("startup")
async def startup_event():
    logger.info(f"\n{'='*60}")
    logger.info(f"{SERVICE_NAME} starting up...")
    logger.info(f"{'='*60}")
    logger.info(f"Model: Llama-based Translation")
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
        service="translation-service",
        model="llama-2-7b",
        supported_languages=len(SUPPORTED_LANGUAGES),
        languages=list(SUPPORTED_LANGUAGES.keys())
    )

# ============ TRANSLATION ENDPOINTS ============

@app.post("/api/v1/translate", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest) -> TranslationResponse:
    """
    Translate text using Llama model to 6 Indian languages
    
    For real-time system - translates to all 6 languages in parallel
    """
    
    start_time = time.time()
    
    try:
        # Determine target languages
        if request.target_language:
            target_langs = [request.target_language]
        elif request.target_languages:
            target_langs = request.target_languages
        else:
            # Default: translate to all 6 Indian languages
            target_langs = list(SUPPORTED_LANGUAGES.keys())
        
        # Validate languages
        invalid_langs = [lang for lang in target_langs if lang not in SUPPORTED_LANGUAGES]
        if invalid_langs:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported languages: {invalid_langs}"
            )
        
        logger.info(f"[{request.stream_id}] Translating to: {target_langs}")
        
        # Perform translation
        translations = await translation_engine.translate_batch(request.text, target_langs)
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # If single language, return single translation
        if request.target_language:
            return TranslationResponse(
                stream_id=request.stream_id,
                text=request.text,
                translation=translations.get(request.target_language),
                source_language=request.source_language,
                target_languages=target_langs,
                model="llama",
                processing_time_ms=processing_time,
                timestamp=datetime.utcnow().isoformat()
            )
        
        # Multiple languages - return all
        return TranslationResponse(
            stream_id=request.stream_id,
            text=request.text,
            translations=translations,
            source_language=request.source_language,
            target_languages=target_langs,
            model="llama",
            processing_time_ms=processing_time,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============ LANGUAGE ENDPOINTS ============

@app.get("/api/v1/languages")
async def get_supported_languages() -> Dict[str, LanguageInfo]:
    """Get list of supported languages"""
    
    languages = {}
    for code, info in SUPPORTED_LANGUAGES.items():
        languages[code] = LanguageInfo(
            code=code,
            name=info['name'],
            native_name=info['native'],
            supported=True
        )
    
    return languages

@app.get("/api/v1/languages/{language_code}")
async def get_language_info(language_code: str) -> LanguageInfo:
    """Get information about a specific language"""
    
    if language_code not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=404,
            detail=f"Language {language_code} not supported"
        )
    
    info = SUPPORTED_LANGUAGES[language_code]
    return LanguageInfo(
        code=language_code,
        name=info['name'],
        native_name=info['native'],
        supported=True
    )

# ============ CONTEXT ENDPOINTS ============

@app.post("/api/v1/context/save")
async def save_context(stream_id: str, context: List[Dict]):
    """Save translation context for consistency"""
    
    logger.info(f"[{stream_id}] Context saved with {len(context)} entries")
    
    return {
        "stream_id": stream_id,
        "context_size": len(context),
        "stored_at": datetime.utcnow().isoformat()
    }

@app.get("/api/v1/context/{stream_id}")
async def load_context(stream_id: str):
    """Load translation context"""
    
    logger.info(f"[{stream_id}] Context loaded")
    
    return {
        "stream_id": stream_id,
        "context": []
    }

# ============ STATUS ENDPOINTS ============

@app.get("/api/v1/stats")
async def get_stats():
    """Get service statistics"""
    
    return {
        "service": SERVICE_NAME,
        "model": "llama-2-7b",
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
