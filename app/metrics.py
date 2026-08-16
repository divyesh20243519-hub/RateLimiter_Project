"""
Prometheus metrics for the rate limiter.

Two metrics, deliberately kept small rather than instrumenting everything:

REQUESTS_TOTAL -- a Counter labeled by outcome. This is the metric that
actually matters operationally: it's what lets you build a dashboard
answering "what fraction of traffic is being rejected right now?" and,
critically, "is Redis degraded right now?" -- the degraded_open/
degraded_closed labels are what turn Phase 6's silent fail-open behavior
into something visible and alertable, instead of an invisible outage.

REDIS_CALL_LATENCY -- a Histogram of how long the Lua script call takes.
Buckets are tuned for a call that should normally complete in low
milliseconds; if p99 creeps toward the socket timeout, that's an early
warning sign before Redis actually starts timing out and triggering
fail-open/fail-closed.
"""

from prometheus_client import Counter, Histogram

REQUESTS_TOTAL = Counter(
    "rate_limiter_requests_total",
    "Total number of rate limit check requests, by outcome",
    ["result"],  # "allowed" | "rejected" | "degraded_open" | "degraded_closed"
)

REDIS_CALL_LATENCY = Histogram(
    "rate_limiter_redis_call_latency_seconds",
    "Latency of the Redis Lua script call (HMGET+HSET+EXPIRE as one EVALSHA)",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
)