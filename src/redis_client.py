"""
redis_client.py — Shared Redis connection manager.
Used for distributed caching, pub/sub, and shared state.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import redis.asyncio as aioredis

from src.config_loader import cfg
from src.logger import get_logger

log = get_logger(__name__)

_redis: Optional[aioredis.Redis] = None
_last_attempt = 0.0
_lock = asyncio.Lock()


async def get_redis() -> Optional[aioredis.Redis]:
    """Get or create a shared Redis client instance with back-off."""
    global _redis, _last_attempt
    
    if not cfg.redis.host:
        return None
        
    async with _lock:
        now = time.perf_counter()
        
        # If we have a working connection, return it
        if _redis is not None:
            try:
                await asyncio.wait_for(_redis.ping(), timeout=0.1)
                return _redis
            except Exception:
                _redis = None
        
        # If we just failed, don't try again too soon (30s backoff)
        if now - _last_attempt < 30.0:
            return None

        try:
            log.info("redis_connecting", host=cfg.redis.host, port=cfg.redis.port)
            _last_attempt = now
            pool = aioredis.ConnectionPool.from_url(
                f"redis://{cfg.redis.host}:{cfg.redis.port}/{cfg.redis.db}",
                password=cfg.redis.password or None,
                max_connections=cfg.redis.max_connections,
                decode_responses=False,
            )
            _redis = aioredis.Redis(connection_pool=pool)
            await asyncio.wait_for(_redis.ping(), timeout=1.0)
            log.info("redis_connected")
            return _redis
        except Exception as e:
            log.warning("redis_connection_failed", error=str(e))
            _redis = None
            return None


async def _is_connected() -> bool:
    if _redis is None:
        return False
    try:
        await _redis.ping()
        return True
    except Exception:
        return False


async def close_redis() -> None:
    global _redis
    async with _lock:
        if _redis:
            await _redis.aclose()
            _redis = None
            log.info("redis_connection_closed")
