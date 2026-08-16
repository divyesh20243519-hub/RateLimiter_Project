"""
Pydantic models for the /api/v1/check request and response bodies.

FastAPI uses these for both validation AND auto-generated OpenAPI docs
(visit /docs once the server is running) — that's a free interview-demo
asset, not just boilerplate.
"""

from pydantic import BaseModel, Field

from app.policy import Policy


class CheckRequest(BaseModel):
    key: str = Field(..., min_length=1, description="Rate-limit key, e.g. 'user:123'")
    policy: Policy


class CheckResponse(BaseModel):
    allowed: bool
    remaining: float | None = None
    retry_after: float | None = None
    # True only when this decision was made WITHOUT successfully reaching
    # Redis (i.e. during a Redis outage/timeout) -- see app/config.py's
    # fail_mode. When degraded, `remaining` is None because we genuinely
    # don't know the real token count; we're either letting the request
    # through blind (fail-open) or blocking it blind (fail-closed).
    degraded: bool = False