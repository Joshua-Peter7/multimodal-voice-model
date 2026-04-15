import asyncio
from soniox import SonioxClient
from soniox.types import RealtimeSTTConfig

async def test_sdk():
    client = SonioxClient()
    config = RealtimeSTTConfig(model="en_v2_lowlatency", include_nonfinal=True)
    
    with client.realtime.stt.connect(config=config) as session:
        print("Connected.")
        
        # Send some dummy 16kHz audio
        for _ in range(5):
            session.send_audio(b'\x00' * 1024)
            # await asyncio.sleep(0.032)
        session.send_audio_eof()
        
        for event in session.receive_events():
            print(event)

if __name__ == "__main__":
    asyncio.run(test_sdk())
