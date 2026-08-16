# Distributed Rate Limiter

A Redis-backed, distributed rate limiter built with FastAPI. Implements the token bucket algorithm with atomic enforcement (Redis Lua scripting) across multiple stateless instances.

## Features

- Atomic token bucket via Redis Lua script — no race conditions under concurrency
- Stateless instances, verified correct across a 3-node Docker Compose + nginx deployment
- Configurable fail-open / fail-closed behavior on Redis outage
- Prometheus metrics (`/metrics`)
- 37 passing tests, load tested with Locust

## Architecture
Client → nginx → [rl1, rl2, rl3] → Redis (atomic Lua script)
