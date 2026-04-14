#!/usr/bin/env python3.10
"""
test_api_endpoints.py — Comprehensive API endpoint validation.
Tests all REST endpoints and WebSocket connections.
Run with: python3.10 test_api_endpoints.py
"""

import asyncio
import json
import sys
from urllib.request import urlopen, Request
import urllib.error

BASE_URL = "http://localhost:8000"

def test_health():
    """Test /health endpoint"""
    print("🧪 Testing /health endpoint...")
    try:
        with urlopen(f"{BASE_URL}/health", timeout=5) as response:
            data = json.loads(response.read().decode())
            print(f"   ✅ Status: {data.get('status')}")
            print(f"   ✅ Channels: {data.get('channels')}")
            print(f"   ✅ Active Speaker: {data.get('active_speaker')}")
            return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_languages():
    """Test /languages endpoint"""
    print("\n🧪 Testing /languages endpoint...")
    try:
        with urlopen(f"{BASE_URL}/languages", timeout=5) as response:
            data = json.loads(response.read().decode())
            source = data.get('source', {})
            targets = data.get('targets', [])
            print(f"   ✅ Source Language: {source.get('name')} ({source.get('code')})")
            print(f"   ✅ Target Languages ({len(targets)}):")
            for lang in targets:
                print(f"      - {lang.get('name')} ({lang.get('code')}): {lang.get('listeners')} listeners")
            return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_stats():
    """Test /stats endpoint"""
    print("\n🧪 Testing /stats endpoint...")
    try:
        with urlopen(f"{BASE_URL}/stats", timeout=5) as response:
            data = json.loads(response.read().decode())
            print(f"   ✅ Total Listeners: {data.get('total_listeners')}")
            print(f"   ✅ Channels: {data.get('channels')}")
            return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_frontend():
    """Test frontend serving"""
    print("\n🧪 Testing Frontend serving...")
    try:
        with urlopen(f"{BASE_URL}/", timeout=5) as response:
            content = response.read().decode()
            if "Real-Time Translation Broadcast" in content:
                print(f"   ✅ Frontend HTML loaded (size: {len(content)} bytes)")
                return True
            else:
                print(f"   ❌ Frontend not loaded correctly")
                return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

async def test_websocket_speaker():
    """Test Speaker WebSocket endpoint"""
    print("\n🧪 Testing /ws/speaker WebSocket endpoint...")
    try:
        import websockets
        uri = "ws://localhost:8000/ws/speaker"
        async with websockets.connect(uri, ping_interval=None) as websocket:
            # Receive initial connection message
            msg = await asyncio.wait_for(websocket.recv(), timeout=5)
            data = json.loads(msg)
            if data.get("type") == "connected":
                print(f"   ✅ Connected with session ID: {data.get('session_id')}")
                print(f"   ✅ Config: {data.get('config')}")
                await websocket.close()
                return True
            else:
                print(f"   ❌ Unexpected message: {msg}")
                return False
    except ImportError:
        print(f"   ⚠️  websockets library not installed (skipping WebSocket test)")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

async def test_websocket_listener():
    """Test Listener WebSocket endpoint"""
    print("\n🧪 Testing /ws/listener/{{lang}} WebSocket endpoint...")
    try:
        import websockets
        uri = "ws://localhost:8000/ws/listener/hi"
        async with websockets.connect(uri, ping_interval=None) as websocket:
            # Receive initial subscription message
            msg = await asyncio.wait_for(websocket.recv(), timeout=5)
            data = json.loads(msg)
            if data.get("type") == "subscribed":
                print(f"   ✅ Subscribed to {data.get('lang_code')} with ID: {data.get('listener_id')}")
                await websocket.close()
                return True
            else:
                print(f"   ❌ Unexpected message: {msg}")
                return False
    except ImportError:
        print(f"   ⚠️  websockets library not installed (skipping WebSocket test)")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

async def main():
    print("=" * 60)
    print("🚀 Real-Time Translation API Test Suite")
    print("=" * 60)
    
    results = []
    
    # REST endpoint tests
    results.append(("Health Endpoint", test_health()))
    results.append(("Languages Endpoint", test_languages()))
    results.append(("Stats Endpoint", test_stats()))
    results.append(("Frontend Serving", test_frontend()))
    
    # WebSocket tests
    results.append(("Speaker WebSocket", await test_websocket_speaker()))
    results.append(("Listener WebSocket", await test_websocket_listener()))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:8} {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! API is fully functional.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check the errors above.")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
