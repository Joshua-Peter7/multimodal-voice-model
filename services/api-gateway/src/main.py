# API Gateway - Main Entry Point
# Handles authentication, rate limiting, routing

import os
import sys
from pathlib import Path
from datetime import datetime

# Add root directory to path for imports
root_dir = Path(__file__).parent.parent.parent.parent.absolute()
sys.path.insert(0, str(root_dir))

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import configuration
from config import load_config

# Create FastAPI app
app = FastAPI(
    title="Multimodal Voice Translation - API Gateway",
    description="Main entry point for all client requests",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ CONFIGURATION ============

config = load_config()

# ============ MIDDLEWARE ============

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add request ID header"""
    from shared.python.utils import generate_request_id
    request.state.request_id = generate_request_id()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response

# ============ ROUTES ============

@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "api-gateway",
        "version": "1.0.0"
    }

@app.get("/api/v1/supported-languages")
async def get_supported_languages():
    """Get list of supported Indian languages"""
    return {
        "system": "real-time-6-language",
        "supported_languages": [
            {"code": "ta", "name": "Tamil", "native": "தமிழ்"},
            {"code": "en", "name": "English", "native": "English"},
            {"code": "te", "name": "Telugu", "native": "తెలుగు"},
            {"code": "ml", "name": "Malayalam", "native": "മലയാളം"},
            {"code": "kn", "name": "Kannada", "native": "ಕನ್ನಡ"},
            {"code": "hi", "name": "Hindi", "native": "हिंदी"}
        ]
    }

@app.get("/api/v1/status")
async def get_status():
    """Get system status for real-time 6-language pipeline"""
    status = {
        "system": "real-time-6-language",
        "gateway": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {}
    }
    
    # Check service health
    services_to_check = [
        ("asr", "http://localhost:5002/api/v1/health"),
        ("translation", "http://localhost:5003/api/v1/health"),
        ("tts", "http://localhost:5005/api/v1/health")
    ]
    
    try:
        import requests
        for service_name, health_url in services_to_check:
            try:
                response = requests.get(health_url, timeout=2)
                status["services"][service_name] = "healthy" if response.status_code == 200 else "unhealthy"
            except:
                status["services"][service_name] = "unreachable"
    except ImportError:
        # If requests not available, mark as unknown
        for service_name, _ in services_to_check:
            status["services"][service_name] = "unknown"
    
    return status

# ============ ERROR HANDLERS ============

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions"""
    return {
        "error": exc.detail,
        "status_code": exc.status_code,
        "request_id": request.state.request_id
    }

# ============ STARTUP/SHUTDOWN ============

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    print("API Gateway starting...")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    print("API Gateway shutting down...")

# ============ MAIN ============

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("GATEWAY_PORT", 5000))
    workers = int(os.getenv("GATEWAY_WORKERS", 4))
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        workers=workers,
        reload=os.getenv("APP_ENV") == "development"
    )
