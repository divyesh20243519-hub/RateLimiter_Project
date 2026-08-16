"""
Redis client singleton.

Exposed as `get_redis_client`, a plain function that returns one shared
`redis.Redis` instance (backed by redis-py's own internal connection pool,
so this is safe to share across concurrent requests). We wire this in as a
FastAPI dependency (see app/api/routes.py) rather than importing a
module-level client directly, specifically so tests can override it with
`app.dependency_overrides[get_redis_client] = ...` and point at a test
database without monkeypatching internals.
"""

import redis

from app.config import settings

_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            socket_timeout=settings.redis_socket_timeout,
        )
    return _client