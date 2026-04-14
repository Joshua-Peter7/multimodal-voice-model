#!/usr/bin/env python3.10
"""Debug WebSocket endpoint errors"""
import asyncio
import json

async def test_ws():
    try:
        import websockets
        print("Testing WebSocket connection to /ws/speaker...")
        async with websockets.connect("ws://localhost:8000/ws/speaker", ping_interval=None) as ws:
            print(f"Connected! Waiting for message...")
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"Received: {msg}")
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        print(f"Type: {type(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ws())
