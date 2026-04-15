import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ELEVENLABS_API_KEY")

async def get_voices():
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": api_key}) as resp:
            data = await resp.json()
            for v in data.get("voices", []):
                print(f"{v['voice_id']} - {v['name']} ({v.get('category')})")

asyncio.run(get_voices())
