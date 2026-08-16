import time

from fastapi import APIRouter, Depends, Response
import redis

from app.api.schemas import CheckRequest, CheckResponse
from app.config import settings
from app.limiter.redis_bucket import RedisTokenBucket
from app.limiter.redis_client import get_redis_client
from app.metrics import REQUESTS_TOTAL, REDIS_CALL_LATENCY

router = APIRouter()


@router.post("/api/v1/check", response_model=CheckResponse)
def check(
    req: CheckRequest,
    response: Response,
    redis_client: redis.Redis = Depends(get_redis_client),
):
    # Note: we construct a fresh RedisTokenBucket on every request. This is
    # intentional and cheap -- ALL the actual state lives in Redis (see
    # app/limiter/redis_bucket.py), not on this object, so there is nothing
    # to "keep around" between requests. This is exactly what makes this
    # server stateless (spec section 3): any RL instance can handle any
    # request for any key, because none of them privately own the answer.
    bucket = RedisTokenBucket(
        redis_client,
        req.key,
        capacity=req.policy.capacity,
        refill_rate=req.policy.refill_rate,
    )

    start = time.perf_counter()
    try:
        allowed, remaining = bucket.allow()
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError) as exc:
        REDIS_CALL_LATENCY.observe(time.perf_counter() - start)
        result_label = "degraded_closed" if settings.fail_mode == "closed" else "degraded_open"
        REQUESTS_TOTAL.labels(result=result_label).inc()
        return _handle_redis_failure(response, exc)

    REDIS_CALL_LATENCY.observe(time.perf_counter() - start)

    response.headers["X-RateLimit-Limit"] = str(req.policy.capacity)
    response.headers["X-RateLimit-Remaining"] = str(max(0, int(remaining)))

    if allowed:
        REQUESTS_TOTAL.labels(result="allowed").inc()
        return CheckResponse(allowed=True, remaining=remaining)

    # When rejected, `remaining` is the (fractional) token count the Lua
    # script measured at decision time -- always < 1 since that's why we
    # were rejected. retry_after is how long until it crosses 1 again.
    retry_after = max(0.0, (1 - remaining) / req.policy.refill_rate)
    response.status_code = 429
    response.headers["Retry-After"] = str(round(retry_after, 3))
    REQUESTS_TOTAL.labels(result="rejected").inc()
    return CheckResponse(allowed=False, remaining=remaining, retry_after=round(retry_after, 3))


def _handle_redis_failure(response: Response, exc: Exception) -> CheckResponse:
    """
    Redis is unreachable or timed out. Behavior is controlled by
    settings.fail_mode (env var FAIL_MODE, default "open"):

      - "open"   -- let the request through, unenforced. The rate limiter
                    being down does not take the protected backend down
                    with it. `allowed=True`, `remaining=None` (genuinely
                    unknown), `degraded=True` so callers/monitoring can
                    tell this wasn't a real enforcement decision.
      - "closed" -- reject with 503 Service Unavailable (NOT 429 --
                    429 means "you exceeded your limit," 503 means "the
                    limiter itself is broken," and callers should be able
                    to tell those apart and handle them differently, e.g.
                    retry-with-backoff vs alerting on-call).

    In both cases we set X-RateLimit-Degraded so infrastructure/monitoring
    can detect and alert on Redis outages even when fail-open is silently
    keeping the user-facing behavior looking normal. The REQUESTS_TOTAL
    metric (labeled degraded_open/degraded_closed, incremented by the
    caller before this function runs) is what makes that alertable in
    practice -- a dashboard/alert rule watching for a nonzero rate of
    degraded_* results is how you'd actually find out about a Redis
    outage in production, since fail-open by design looks fine to users.
    """
    response.headers["X-RateLimit-Degraded"] = "true"

    if settings.fail_mode == "closed":
        response.status_code = 503
        return CheckResponse(allowed=False, remaining=None, retry_after=None, degraded=True)

    # fail-open (default)
    return CheckResponse(allowed=True, remaining=None, degraded=True)