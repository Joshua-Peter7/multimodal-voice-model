import asyncio
from src.tts.elevenlabs_client import ElevenLabsTTSClient
from src.config_loader import cfg
import aiohttp
import json

async def test_tts():
    tts = ElevenLabsTTSClient()
    hi_lang = next(lang for lang in cfg.enabled_languages if lang.code == "hi")
    
    ws_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{hi_lang.voice_id}"
        f"/stream-input?model_id={tts._cfg.model_id}"
        f"&output_format={tts._cfg.output_format}"
    )

    payload = {
        "text": "?? ?? ??????? ??",
        "model_id": tts._cfg.model_id,
        "voice_settings": {
            "stability": hi_lang.stability,
            "similarity_boost": hi_lang.similarity_boost,
        }
    }
    
    session = await tts._ensure_session()
    async with session.ws_connect(ws_url, headers={"xi-api-key": tts._cfg.api_key}) as ws:
        await ws.send_str(json.dumps(payload))
        await ws.send_str(json.dumps({"text": ""}))
        async for msg in ws:
            print("MSG:", msg.data)
            
asyncio.run(test_tts())
