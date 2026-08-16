"""
Tests for the HTTP API layer, now backed by real Redis (via the atomic
RedisTokenBucket) instead of the Phase 2 in-memory registry.

We override the `get_redis_client` FastAPI dependency to point at Redis
DB 15 (a separate logical database from the default DB 0 used elsewhere)
so these tests never collide with data from test_redis_bucket.py or a
manually-running dev server, and we flush it before every test.
"""

import redis
from fastapi.testclient import TestClient

from app.limiter.redis_client import get_redis_client
from app.main import app

try:
    _client = redis.Redis(host="localhost", port=6379, db=15)
    _client.ping()
    REDIS_AVAILABLE = True
except redis.exceptions.ConnectionError:
    REDIS_AVAILABLE = False

import pytest

pytestmark = pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not running on localhost:6379")

test_redis_client = redis.Redis(host="localhost", port=6379, db=15)
app.dependency_overrides[get_redis_client] = lambda: test_redis_client

client = TestClient(app)


def setup_function():
    """Clean Redis state before every test."""
    test_redis_client.flushdb()


def test_allowed_request_returns_200_with_headers():
    resp = client.post(
        "/api/v1/check",
        json={"key": "user:1", "policy": {"capacity": 5, "refill_rate": 1}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed"] is True
    assert body["remaining"] == 4
    assert resp.headers["X-RateLimit-Limit"] == "5.0"
    assert resp.headers["X-RateLimit-Remaining"] == "4"


def test_rejected_request_returns_429_with_retry_after():
    key = "user:2"
    for _ in range(3):
        client.post("/api/v1/check", json={"key": key, "policy": {"capacity": 3, "refill_rate": 0.001}})

    resp = client.post("/api/v1/check", json={"key": key, "policy": {"capacity": 3, "refill_rate": 0.001}})
    assert resp.status_code == 429
    body = resp.json()
    assert body["allowed"] is False
    assert body["remaining"] < 1
    assert body["retry_after"] > 0
    assert "Retry-After" in resp.headers


def test_same_key_shares_bucket_across_requests():
    """The whole point of Redis-backed state: persists between separate HTTP calls for the same key."""
    key = "user:3"
    policy = {"capacity": 2, "refill_rate": 0.001}

    r1 = client.post("/api/v1/check", json={"key": key, "policy": policy})
    r2 = client.post("/api/v1/check", json={"key": key, "policy": policy})
    r3 = client.post("/api/v1/check", json={"key": key, "policy": policy})

    assert r1.json()["allowed"] is True
    assert r2.json()["allowed"] is True
    assert r3.json()["allowed"] is False  # capacity=2 exhausted


def test_different_keys_have_independent_buckets():
    policy = {"capacity": 1, "refill_rate": 0.001}
    r1 = client.post("/api/v1/check", json={"key": "userA", "policy": policy})
    r2 = client.post("/api/v1/check", json={"key": "userB", "policy": policy})

    assert r1.json()["allowed"] is True
    assert r2.json()["allowed"] is True  # independent bucket, not affected by userA


def test_malformed_request_missing_key_returns_400():
    resp = client.post("/api/v1/check", json={"policy": {"capacity": 5, "refill_rate": 1}})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"


def test_invalid_policy_negative_capacity_returns_400():
    resp = client.post(
        "/api/v1/check",
        json={"key": "user:4", "policy": {"capacity": -1, "refill_rate": 1}},
    )
    assert resp.status_code == 400


def test_invalid_policy_zero_refill_rate_returns_400():
    resp = client.post(
        "/api/v1/check",
        json={"key": "user:5", "policy": {"capacity": 5, "refill_rate": 0}},
    )
    assert resp.status_code == 400


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_two_simulated_instances_share_global_limit():
    """
    Simulates two separate RL server instances (RL1, RL2) both handling
    requests for the same key. Since both talk to the same Redis, the
    global limit is enforced correctly across "instances" -- this is the
    exact scenario spec section 5 describes as broken with in-memory state,
    and Redis-backed state (which is what routes.py now uses) fixes it.
    """
    key = "user:multi_instance"
    policy = {"capacity": 3, "refill_rate": 0.001}

    # Both "RL1" and "RL2" are really just this same TestClient hitting the
    # same app + same Redis -- but the point is neither call carries any
    # server-side session state between them; each is a fresh HTTP request.
    results = []
    for _ in range(5):
        resp = client.post("/api/v1/check", json={"key": key, "policy": policy})
        results.append(resp.json()["allowed"])

    assert results == [True, True, True, False, False], (
        "exactly 3 of 5 requests should be allowed, matching capacity=3 "
        "regardless of which 'instance' handled which request"
    )