"""
Tests for the atomic, Lua-backed RedisTokenBucket (Phase 4) -- the real
production implementation.

test_atomic_bucket_fixes_race_condition is the payoff test of the whole
project: same setup as
tests/test_naive_redis_bucket.py::test_naive_bucket_has_race_condition
(20 concurrent threads, capacity=1, same key), but this time we assert
EXACTLY 1 request is allowed, not "more than 1."
"""

import threading
import time

import pytest
import redis

from app.limiter.redis_bucket import RedisTokenBucket

try:
    _client = redis.Redis(host="localhost", port=6379, db=0)
    _client.ping()
    REDIS_AVAILABLE = True
except redis.exceptions.ConnectionError:
    REDIS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not running on localhost:6379")


@pytest.fixture
def redis_client():
    client = redis.Redis(host="localhost", port=6379, db=0)
    yield client
    client.flushdb()


def test_basic_allow_and_reject(redis_client):
    bucket = RedisTokenBucket(redis_client, "atomic:basic", capacity=3, refill_rate=0.001)

    assert bucket.allow()[0] is True
    assert bucket.allow()[0] is True
    assert bucket.allow()[0] is True
    assert bucket.allow()[0] is False


def test_refill_over_time(redis_client):
    bucket = RedisTokenBucket(redis_client, "atomic:refill", capacity=5, refill_rate=5)  # 5 tokens/sec

    for _ in range(5):
        assert bucket.allow()[0] is True
    assert bucket.allow()[0] is False  # drained

    time.sleep(0.3)  # should earn ~1.5 tokens

    allowed, _ = bucket.allow()
    assert allowed is True


def test_tokens_never_exceed_capacity(redis_client):

    key = "atomic:cap"

    seed_bucket = RedisTokenBucket(redis_client, key, capacity=3, refill_rate=100)
    time.sleep(0.1)  # would earn ~10 tokens if the bucket didn't cap at capacity
    allowed, remaining = seed_bucket.allow()
    assert allowed is True
    assert remaining <= 2.01, "bucket should have capped at capacity=3, not kept accruing to ~9"

    drain_bucket = RedisTokenBucket(redis_client, key, capacity=3, refill_rate=0.00001)
    allowed_count = 1  # the seed_bucket call above already consumed 1
    for _ in range(9):
        allowed, _ = drain_bucket.allow()
        if allowed:
            allowed_count += 1

    assert allowed_count == 3


def test_state_persists_across_process_boundaries(redis_client):
    """Two separate RedisTokenBucket objects (simulating two RL instances) sharing one key."""
    b1 = RedisTokenBucket(redis_client, "atomic:shared", capacity=2, refill_rate=0.001)
    b2 = RedisTokenBucket(redis_client, "atomic:shared", capacity=2, refill_rate=0.001)

    assert b1.allow()[0] is True   # instance 1 takes token 1
    assert b2.allow()[0] is True   # instance 2 takes token 2 -- sees b1's write
    assert b1.allow()[0] is False  # both tokens gone, either instance sees it
    assert b2.allow()[0] is False


def test_ttl_is_set(redis_client):
    bucket = RedisTokenBucket(redis_client, "atomic:ttl", capacity=5, refill_rate=1)
    bucket.allow()
    ttl = redis_client.ttl(bucket.key)
    assert ttl > 0


def test_new_key_starts_full(redis_client):
    """First-ever request for a brand-new key should see a full bucket, not an empty one."""
    bucket = RedisTokenBucket(redis_client, "atomic:fresh", capacity=10, refill_rate=1)
    allowed, remaining = bucket.allow()
    assert allowed is True
    assert remaining == pytest.approx(9, abs=0.01)


def test_atomic_bucket_fixes_race_condition(redis_client):
    """
    THE PAYOFF TEST.

    Identical setup to
    test_naive_redis_bucket.py::test_naive_bucket_has_race_condition:
    capacity=1, 20 concurrent threads, same key. The naive version allowed
    MORE than 1 request due to the unprotected read-modify-write. This
    atomic, Lua-backed version must allow EXACTLY 1 -- proving the fix
    actually closes the race rather than just making it less likely.

    Redis's single-threaded Lua execution
    serializes these calls regardless of timing.
    """
    key = "atomic:race"
    allowed_count = 0
    lock = threading.Lock()

    def worker():
        nonlocal allowed_count
        bucket = RedisTokenBucket(redis_client, key, capacity=1, refill_rate=0.00001)
        allowed, _ = bucket.allow()
        if allowed:
            with lock:
                allowed_count += 1

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert allowed_count == 1, (
        f"Expected EXACTLY 1 allowed request under concurrency, got {allowed_count}. "
        f"If this is greater than 1, the Lua script is not actually atomic -- "
        f"check that HMGET/HSET/EXPIRE all happen inside the script, not around it."
    )


def test_many_concurrent_requests_never_exceed_capacity(redis_client):
    """
    Broader version of the race test: capacity=10, 100 threads. No matter
    how much concurrency we throw at it, allowed count must never exceed
    capacity for a fresh bucket with negligible refill during the test.
    """
    key = "atomic:race_wide"
    allowed_count = 0
    lock = threading.Lock()

    def worker():
        nonlocal allowed_count
        bucket = RedisTokenBucket(redis_client, key, capacity=10, refill_rate=0.00001)
        allowed, _ = bucket.allow()
        if allowed:
            with lock:
                allowed_count += 1

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert allowed_count == 10