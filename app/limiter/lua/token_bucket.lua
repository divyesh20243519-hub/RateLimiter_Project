-- token_bucket.lua
--
-- Atomic Token Bucket decision. Runs as a single Redis command — Redis
-- executes Lua scripts single-threaded, so no other client can read or
-- write KEYS[1] while this script is running. This is what makes the
-- read -> calculate -> write sequence atomic, closing the race condition
-- that app/limiter/naive_redis_bucket.py deliberately demonstrates.
--
-- KEYS[1] = the Redis key for this bucket, e.g. "rl:user:123"
-- ARGV[1] = capacity        (max tokens)
-- ARGV[2] = refill_rate     (tokens per second)
-- ARGV[3] = now_ms          (current time in milliseconds, passed in from
--                             the application rather than read via Redis
--                             TIME -- this keeps the script deterministic
--                             and easy to unit test with fixed timestamps)
-- ARGV[4] = ttl_seconds     (expiry for idle keys)
--
-- Returns: { allowed (1 or 0), tokens_remaining (string) }

local key          = KEYS[1]
local capacity     = tonumber(ARGV[1])
local refill_rate  = tonumber(ARGV[2])
local now_ms       = tonumber(ARGV[3])
local ttl_seconds  = tonumber(ARGV[4])

local data = redis.call("HMGET", key, "tokens", "last_refill")
local tokens
local last_refill_ms

if data[1] == false then
    -- Key doesn't exist yet -- bucket starts full, as if it had always
    -- been sitting there refilling since before the first request.
    tokens = capacity
    last_refill_ms = now_ms
else
    tokens = tonumber(data[1])
    last_refill_ms = tonumber(data[2])
end

local elapsed_seconds = (now_ms - last_refill_ms) / 1000.0
if elapsed_seconds < 0 then
    -- Defensive: never let a clock anomaly produce negative elapsed time,
    -- which would otherwise silently REMOVE tokens instead of adding them.
    elapsed_seconds = 0
end

tokens = math.min(capacity, tokens + elapsed_seconds * refill_rate)

local allowed
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    allowed = 0
end

redis.call("HSET", key, "tokens", tostring(tokens), "last_refill", tostring(now_ms))
redis.call("EXPIRE", key, ttl_seconds)

return { allowed, tostring(tokens) }