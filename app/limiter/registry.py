"""
In-memory bucket registry (Phase 2 only).

Maps a rate-limit key ("user:123") to its TokenBucket instance. This lets a
single process remember state between requests for the same key.

IMPORTANT — this is explicitly the thing Phase 3/4 replaces. A dict living in
one process's memory:
  - is lost on restart (spec section 19, test #9)
  - is NOT shared across multiple instances (spec section 5) — RL1 and RL2
    would each have their own registry and their own idea of how many tokens
    "user:123" has left, which is exactly the 240-requests-instead-of-100
    bug the spec describes.

We build it anyway as Phase 2 so we can prove the HTTP layer (validation,
status codes, headers) works correctly before adding Redis complexity on
top. Keep this file in mind as the "before" picture.
"""

import threading

from app.limiter.local_bucket import TokenBucket
from app.policy import Policy


class BucketRegistry:
    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._registry_lock = threading.Lock()

    def get_or_create(self, key: str, policy: Policy) -> TokenBucket:
        """
        Return the bucket for `key`, creating it with `policy` if it doesn't
        exist yet. Note: if a bucket already exists, its policy is NOT
        updated here — first policy seen for a key wins for that bucket's
        lifetime. This mirrors a real limitation we'll solve properly when
        policies become server-side config in a later phase.
        """
        with self._registry_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(capacity=policy.capacity, refill_rate=policy.refill_rate)
                self._buckets[key] = bucket
            return bucket

    def size(self) -> int:
        with self._registry_lock:
            return len(self._buckets)


# Process-wide singleton for Phase 2. Replaced by Redis client in Phase 3.
registry = BucketRegistry()