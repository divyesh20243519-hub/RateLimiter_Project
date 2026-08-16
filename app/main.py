"""
FastAPI application entrypoint.

Run locally with:
    uvicorn app.main:app --reload

Then visit http://127.0.0.1:8000/docs for the auto-generated API explorer.
"""

from contextlib import asynccontextmanager

from anyio import to_thread
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Our /api/v1/check handler is a sync `def`, not `async def` -- because
    the underlying redis-py client we're using is a blocking (sync)
    client, not redis.asyncio. FastAPI's answer to "I got a sync function"
    is to run it in a background thread pool (via anyio.to_thread) instead
    of on the main event loop, so one slow/blocking call can't freeze
    every other request.

    """
    limiter = to_thread.current_default_thread_limiter()
    limiter.total_tokens = 500
    yield


app = FastAPI(title="Distributed Rate Limiter", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """
    Spec section 12 asks for HTTP 400 on malformed requests. FastAPI's
    default for Pydantic validation failures is 422 Unprocessable Entity,
    which is arguably more RESTful — but we override it here to match the
    spec's explicit contract.
    """
    # jsonable_encoder strips non-serializable internals (e.g. the raw
    # exception object Pydantic v2 attaches to each error's `ctx`) that
    # plain json.dumps chokes on.
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "detail": jsonable_encoder(exc.errors())},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    """
    Prometheus scrape endpoint. Point a Prometheus server's scrape config
    at this path (see deploy/docker-compose.yml, Phase 7 addition) and it
    will pull rate_limiter_requests_total and
    rate_limiter_redis_call_latency_seconds on its own schedule -- nothing
    pushes data anywhere; Prometheus's model is "pull," not "push."
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)