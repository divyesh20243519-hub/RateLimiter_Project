"""
Load test for the rate limiter, using Locust (https://locust.io).

Run against the FULL multi-instance deployment (Docker Compose: 3 RL
instances behind nginx), not a single dev server -- the whole point of
this project is proving correctness AND performance hold up under real
distributed load, not just on one process.

Usage (headless, no web UI, prints a summary at the end):

    locust -f loadtest/locustfile.py --headless \
        -u 200 -r 20 -t 60s \
        --host http://localhost:8080 \
        --csv=benchmarks/results

    -u 200   : simulate 200 concurrent virtual users
    -r 20    : spawn 20 new users per second until reaching 200
    -t 60s   : run for 60 seconds
    --host   : nginx's address -- traffic gets load-balanced across
               rl1/rl2/rl3 from here, exactly like real clients would see
    --csv    : write results to benchmarks/results_stats.csv etc, so the
               numbers are saved, not just printed and lost

Two user classes, weighted differently, to cover two realistic scenarios:

NormalUser (weight 9): each simulated user gets its OWN unique rate-limit
key (like a distinct real user/API key would). This measures raw
throughput/latency under realistic traffic where most requests don't
contend with each other for the same Redis key.

HotKeyUser (weight 1): all simulated users of this class hammer the SAME
key. This deliberately creates contention on one Redis key -- since the
Lua script executes atomically, these requests serialize against each
other. Useful for seeing whether/how much latency increases under
worst-case contention on a single popular key (e.g. a viral endpoint,
or an API key shared by many clients).
"""

import uuid

from locust import HttpUser, task, between


class NormalUser(HttpUser):
    weight = 9
    wait_time = between(0.01, 0.1)

    def on_start(self):
        # One unique key per simulated user, generated once when this
        # "virtual user" starts -- simulates one real, distinct client.
        self.key = f"loadtest:user:{uuid.uuid4()}"

    @task
    def check(self):
        self.client.post(
            "/api/v1/check",
            json={
                "key": self.key,
                "policy": {"capacity": 100, "refill_rate": 10},
            },
            name="/api/v1/check [unique key]",
        )


class HotKeyUser(HttpUser):
    weight = 1
    wait_time = between(0.01, 0.1)

    HOT_KEY = "loadtest:hotkey:shared"

    @task
    def check(self):
        self.client.post(
            "/api/v1/check",
            json={
                "key": self.HOT_KEY,
                "policy": {"capacity": 1000, "refill_rate": 200},
            },
            name="/api/v1/check [shared hot key]",
        )