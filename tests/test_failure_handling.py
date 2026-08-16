"""
Tests for Phase 6 -- what happens when Redis is unreachable.

We simulate "Redis is down" by pointing the get_redis_client dependency at
a port nothing is listening on (6399), with a very short socket timeout so
these tests fail fast instead of hanging for the default timeout duration.
This is a more realistic failure simulation than mocking the exception
directly -- it exercises the real redis-py connection-timeout code path.
"""

import redis
import pytest
from fastapi.testclient import TestClient

import app.config as config_module
from app.limiter.redis_client import get_redis_client
from app.main import app

client = TestClient(app)

# Nothing listens on this port -- connecting will genuinely time out /
# refuse, exercising the real redis.exceptions.ConnectionError path.
_unreachable_client = redis.Redis(
    host="localhost", port=6399, socket_connect_timeout=0.3, socket_timeout=0.3
)


@pytest.fixture
def redis_down():
    """Override the Redis dependency to point at an unreachable client for one test."""
    previous = app.dependency_overrides.get(get_redis_client)
    app.dependency_overrides[get_redis_client] = lambda: _unreachable_client
    yield
    if previous is not None:
        app.dependency_overrides[get_redis_client] = previous
    else:
        app.dependency_overrides.pop(get_redis_client, None)


def test_fail_open_lets_request_through_when_redis_down(redis_down, monkeypatch):
    monkeypatch.setattr(config_module.settings, "fail_mode", "open")

    resp = client.post(
        "/api/v1/check",
        json={"key": "failtest:1", "policy": {"capacity": 5, "refill_rate": 1}},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed"] is True
    assert body["degraded"] is True
    assert body["remaining"] is None
    assert resp.headers.get("X-RateLimit-Degraded") == "true"


def test_fail_closed_rejects_request_when_redis_down(redis_down, monkeypatch):
    monkeypatch.setattr(config_module.settings, "fail_mode", "closed")

    resp = client.post(
        "/api/v1/check",
        json={"key": "failtest:2", "policy": {"capacity": 5, "refill_rate": 1}},
    )

    assert resp.status_code == 503
    body = resp.json()
    assert body["allowed"] is False
    assert body["degraded"] is True


def test_invalid_fail_mode_rejected():
    """Settings should refuse to start with a nonsense FAIL_MODE value."""
    with pytest.raises(ValueError):
        import os
        os.environ["FAIL_MODE"] = "sideways"
        try:
            config_module.Settings()
        finally:
            del os.environ["FAIL_MODE"]