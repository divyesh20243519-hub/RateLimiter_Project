"""
Environment-based configuration.

All values are read from os.environ INSIDE __init__, not as class-body
assignments -- class-body assignments (`x: str = os.getenv(...)`) only
evaluate once, the moment the class is first defined (at import time).
Reading inside __init__ means each `Settings()` call reflects whatever the
environment looks like right now, which matters for tests that set/unset
env vars and expect a freshly constructed Settings() to see the change.
"""

import os


class Settings:
    def __init__(self):
        self.redis_host: str = os.getenv("REDIS_HOST", "localhost")
        self.redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
        self.redis_socket_connect_timeout: float = float(os.getenv("REDIS_CONNECT_TIMEOUT", "2.0"))
        self.redis_socket_timeout: float = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2.0"))
        # "open"   -- if Redis is unreachable/times out, let requests through
        #             (unenforced). Prioritizes availability of your backend
        #             over strict rate-limit enforcement. This is the more
        #             common real-world default: a rate limiter that's down
        #             should not be allowed to take the whole system down.
        # "closed" -- if Redis is unreachable/times out, reject requests
        #             (503). Prioritizes strict enforcement over availability
        #             -- appropriate when exceeding budget is worse than some
        #             requests failing (e.g. protecting an expensive or
        #             compliance-sensitive downstream resource).
        self.fail_mode: str = os.getenv("FAIL_MODE", "open").lower()
        if self.fail_mode not in ("open", "closed"):
            raise ValueError(f"FAIL_MODE must be 'open' or 'closed', got: {self.fail_mode!r}")


settings = Settings()