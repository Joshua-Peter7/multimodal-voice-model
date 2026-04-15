import asyncio
import os
import aiohttp
import json
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("SONIOX_API_KEY")

async def test_soniox():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect("wss://stt-rt.soniox.com/transcribe-websocket") as ws:
            await ws.send_str(json.dumps({"api_key": api_key, "model": "stt-rt-v4", "audio_format": "s16le", "sample_rate": 16000, "num_audio_channels": 1}))
            
            async def receive():
                async for msg in ws:
                    print("Received:", msg.data)
                    return
            t = asyncio.create_task(receive())
            
            for _ in range(20):
                await ws.send_bytes(b'\x01' * 512)
                await asyncio.sleep(0.01)
                
            await ws.send_str(json.dumps({"type": "finalize"}))
            await asyncio.sleep(2)
            
asyncio.run(test_soniox())
