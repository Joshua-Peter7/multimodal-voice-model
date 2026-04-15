import asyncio
import os
import aiohttp
import json
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("SONIOX_API_KEY")

async def test_soniox():
    print("Connecting...")
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect("wss://api.soniox.com/transcribe-websocket") as ws:
            print("Connected.")
            config = {
                "api_key": api_key,
                "model": "en_v2",
                "sample_rate": 16000,
                "num_audio_channels": 1,
            }
            await ws.send_str(json.dumps(config))
            print("Config sent.")
            
            async def send_audio():
                for _ in range(5):
                    await ws.send_bytes(b'\x00' * 1024)
                    await asyncio.sleep(0.032)
                await ws.send_str(json.dumps({"eof": True}))
                print("EOF sent.")
                
            asyncio.create_task(send_audio())
            
            async for msg in ws:
                print("Received msg:", msg.type, msg.data)
                
            print("WebSocket closed. Close code:", ws.close_code)

if __name__ == "__main__":
    asyncio.run(test_soniox())
