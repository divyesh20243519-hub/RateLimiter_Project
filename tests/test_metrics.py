"""
Tests for Phase 7 -- Prometheus metrics.

Prometheus's client library uses one process-wide global registry by
default, so counters accumulate across the whole test session (not reset
per test). We work with that instead of fighting it: rather than asserting
exact values, we capture a metric's value BEFORE an action and assert it
increased by the expected amount AFTER -- this is robust to test order and
to other test files having already incremented the same counters.
"""

import re

import redis
import pytest
from fastapi.testclient import TestClient

from app.limiter.redis_client import get_redis_client
from app.main import app

try:
    _client = redis.Redis(host="localhost", port=6379, db=15)
    _client.ping()
    REDIS_AVAILABLE = True
except redis.exceptions.ConnectionError:
    REDIS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not running on localhost:6379")

test_redis_client = redis.Redis(host="localhost", port=6379, db=15)
app.dependency_overrides[get_redis_client] = lambda: test_redis_client

client = TestClient(app)


def setup_function():
    test_redis_client.flushdb()


def _counter_value(body: str, result_label: str) -> float:
    """Parse a specific result= series out of Prometheus text-format output."""
    pattern = rf'rate_limiter_requests_total\{{result="{result_label}"\}} (\S+)'
    match = re.search(pattern, body)
    return float(match.group(1)) if match else 0.0


def test_metrics_endpoint_returns_prometheus_format():
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "rate_limiter_requests_total" in resp.text
    assert "rate_limiter_redis_call_latency_seconds" in resp.text


def test_allowed_request_increments_allowed_counter():
    before = _counter_value(client.get("/metrics").text, "allowed")

    client.post("/api/v1/check", json={"key": "metrics:1", "policy": {"capacity": 5, "refill_rate": 1}})

    after = _counter_value(client.get("/metrics").text, "allowed")
    assert after == before + 1


def test_rejected_request_increments_rejected_counter():
    key = "metrics:2"
    policy = {"capacity": 1, "refill_rate": 0.001}
    client.post("/api/v1/check", json={"key": key, "policy": policy})  # consume the only token

    before = _counter_value(client.get("/metrics").text, "rejected")
    client.post("/api/v1/check", json={"key": key, "policy": policy})  # this one gets rejected
    after = _counter_value(client.get("/metrics").text, "rejected")

    assert after == before + 1


def test_latency_histogram_has_observations():
    client.post("/api/v1/check", json={"key": "metrics:3", "policy": {"capacity": 5, "refill_rate": 1}})
    body = client.get("/metrics").text
    # _count is the histogram's total observation counter -- confirms at
    # least one call was actually timed and recorded, not just that the
    # metric exists with zero data.
    match = re.search(r"rate_limiter_redis_call_latency_seconds_count (\S+)", body)
    assert match is not None
    assert float(match.group(1)) >= 1