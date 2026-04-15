import asyncio
import os
import aiohttp
import json
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("SONIOX_API_KEY")

async def test_soniox():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect("wss://api.soniox.com/transcribe-websocket") as ws:
            print("Connected.")
            await ws.send_str(json.dumps({"api_key": api_key, "model": "en_v2_lowlatency", "sample_rate": 16000, "num_audio_channels": 1}))
            
            async def receive():
                async for msg in ws:
                    print(msg.type, msg.data)
            t = asyncio.create_task(receive())
            
            # send some audio
            for _ in range(50):
                await ws.send_bytes(b'\x00' * 512)
                await asyncio.sleep(0.01)
                
            await ws.send_str(json.dumps({"eof": True}))
            print("EOF True sent")
            
            await asyncio.sleep(2)
            
asyncio.run(test_soniox())
