import asyncio
from src.tts.elevenlabs_client import ElevenLabsTTSClient
from src.config_loader import cfg

async def test_tts():
    tts = ElevenLabsTTSClient()
    
    # get lang object for hindi
    hi_lang = next(lang for lang in cfg.enabled_languages if lang.code == "hi")
    
    print("Testing translation audio generation for Hindi...")
    chunks = 0
    try:
        async for chunk in tts.stream_one_ws("?? ?? ??????? ??", hi_lang):
            if chunk.audio_chunk:
                chunks += 1
                
        print(f"WS received {chunks} chunks")
    except Exception as e:
        print(f"Exception: {e}")

asyncio.run(test_tts())
