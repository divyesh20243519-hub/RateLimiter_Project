"""
Phase 4 — Redis-backed Token Bucket, ATOMIC (production) version.

This is the real implementation the API uses. It replaces the naive
HGETALL -> calculate -> HSET sequence (app/limiter/naive_redis_bucket.py)
with a single EVALSHA call running app/limiter/lua/token_bucket.lua.

Why this fixes the race condition:
Redis executes Lua scripts to completion, single-threaded, before
processing any other command. Two concurrent callers hitting the same key
are queued and run the ENTIRE read-calculate-write sequence one at a time,
never interleaved. This is the single most important correctness property
of this whole project -- see tests/test_redis_bucket.py, which runs the
exact same concurrency test as the naive version and asserts the opposite
result: exactly 1 allowed, not "more than 1."

"""

import time
from pathlib import Path

import redis

_LUA_SCRIPT_PATH = Path(__file__).parent / "lua" / "token_bucket.lua"
# Read once at import time rather than on every bucket construction --
# the file content never changes at runtime, so re-reading it from disk
# on every single request would be pure overhead.
_LUA_SCRIPT_TEXT = _LUA_SCRIPT_PATH.read_text()


class RedisTokenBucket:
    def __init__(self, redis_client: redis.Redis, key: str, capacity: float, refill_rate: float,
                 ttl_seconds: int | None = None):
        self.redis = redis_client
        self.key = f"rl:{key}"
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)

        # Default TTL: how long a fully-empty bucket takes to refill to
        # capacity, plus a buffer. Any longer and we'd be wasting Redis
        # memory on keys nobody's using; any shorter and an active client
        # could have its history wiped mid-window.
        self.ttl_seconds = ttl_seconds or max(60, int((self.capacity / self.refill_rate) * 2))

        self._script = redis_client.register_script(_LUA_SCRIPT_TEXT)

    def allow(self) -> tuple[bool, float]:
        now_ms = int(time.time() * 1000)

        result = self._script(
            keys=[self.key],
            args=[self.capacity, self.refill_rate, now_ms, self.ttl_seconds],
        )

        allowed = bool(int(result[0]))
        remaining = float(result[1])
        return allowed, remaining