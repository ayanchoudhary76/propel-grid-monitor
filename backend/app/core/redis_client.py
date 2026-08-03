"""
Async Redis client singleton for the KSPDCL fault detection system.

Usage
-----
- Call ``await init_redis()`` on app startup.
- Inject the client via ``Depends(get_redis_dep)`` in route handlers.
- Call ``await close_redis()`` on app shutdown.

The client uses a connection pool internally (managed by the redis library),
so a single ``Redis`` instance is shared safely across concurrent requests.
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level singleton
_redis_client: aioredis.Redis | None = None


async def init_redis() -> None:
    """
    Create the async Redis connection pool and verify connectivity.

    Raises ``ConnectionError`` if the Redis server is unreachable.
    """
    global _redis_client
    _redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,    # all responses are str, not bytes
        max_connections=20,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    # Verify the connection is live
    pong = await _redis_client.ping()
    if not pong:
        raise ConnectionError("Redis ping failed during startup")
    logger.info("Redis connected at %s", settings.REDIS_URL)


async def close_redis() -> None:
    """Close the Redis connection pool gracefully."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    """
    Return the active Redis client.

    Raises ``RuntimeError`` if called before ``init_redis()``.
    """
    if _redis_client is None:
        raise RuntimeError(
            "Redis client is not initialised. "
            "Ensure init_redis() is called during application startup."
        )
    return _redis_client


async def get_redis_dep() -> aioredis.Redis:
    """
    FastAPI dependency: return the shared Redis client.

    No per-request lifecycle management is needed because the redis library
    manages a connection pool internally.
    """
    return get_redis()
