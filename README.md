# Distributed Rate Limiter

A Redis-backed, distributed rate limiter built with FastAPI. Implements the token bucket algorithm with atomic enforcement (Redis Lua scripting) across multiple stateless instances.

## Features

- Atomic token bucket via Redis Lua script — no race conditions under concurrency
- Stateless instances, verified correct across a 3-node Docker Compose + nginx deployment
- Configurable fail-open / fail-closed behavior on Redis outage
- Prometheus metrics (`/metrics`)
- 37 passing tests, load tested with Locust

## Architecture

```
Client → nginx → [rl1, rl2, rl3] → Redis (atomic Lua script)
```

## Quick start

```bash
git clone https://github.com/divyesh20243519/distributed-rate-limiter.git
cd distributed-rate-limiter
docker compose -f deploy/docker-compose.yml up --build
```

```bash
curl -X POST http://localhost:8080/api/v1/check \
  -H "Content-Type: application/json" \
  -d '{"key":"user:123","policy":{"capacity":5,"refill_rate":1}}'
```

## API

**POST** `/api/v1/check`

```json
// Request
{ "key": "user:123", "policy": { "capacity": 100, "refill_rate": 1.5 } }

// Response
{ "allowed": true, "remaining": 99.0, "retry_after": null }
```

`GET /health` · `GET /metrics` · `GET /docs`

## Tech stack

Python · FastAPI · Redis (Lua) · Docker Compose · nginx · Prometheus · Locust · pytest

## Benchmarks

Load tested with Locust (200 concurrent users, 60s) against the full 3-instance deployment. Diagnosed and fixed a FastAPI thread-pool bottleneck (default 40-thread cap) by raising it to 500.

| Metric | Before | After | Change |
|---|---|---|---|
| Requests served (60s) | 15,144 | 26,033 | +72% |
| Median latency | 340ms | 210ms | −38% |
| p99 latency | 940ms | 530ms | −44% |
| Max latency | 2,200ms | 960ms | −56% |
| Failures | 0 | 0 | — |

