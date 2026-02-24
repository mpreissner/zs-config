"""Rolling-window rate limiter.

Tracks request timestamps in a deque and blocks (via time.sleep) until a
slot is available within the configured window.

Usage:
    limiter = RateLimiter(max_calls=20, window=10)   # 20 calls per 10 s
    for item in items:
        limiter.acquire()
        response = client.get(item)
"""

import time
from collections import deque
from threading import Lock


class RateLimiter:
    """Thread-safe rolling-window rate limiter.

    Args:
        max_calls: Maximum number of calls allowed within *window* seconds.
        window:    Length of the rolling window in seconds.
    """

    def __init__(self, max_calls: int, window: float):
        self.max_calls = max_calls
        self.window = window
        self._timestamps: deque[float] = deque()
        self._lock = Lock()

    def acquire(self) -> None:
        """Block until a call slot is available, then claim it."""
        with self._lock:
            while True:
                now = time.monotonic()
                cutoff = now - self.window

                # Drop timestamps outside the current window
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()

                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(now)
                    return

                # Sleep until the oldest timestamp falls outside the window
                sleep_for = self._timestamps[0] - cutoff
                self._lock.release()
                try:
                    time.sleep(sleep_for)
                finally:
                    self._lock.acquire()

    def remaining(self) -> int:
        """Return how many calls are available right now (without blocking)."""
        with self._lock:
            cutoff = time.monotonic() - self.window
            active = sum(1 for t in self._timestamps if t > cutoff)
            return max(0, self.max_calls - active)


# Pre-built limiters matching Zscaler OneAPI documented limits
ZPA_READ_LIMITER = RateLimiter(max_calls=15, window=10)    # conservative: 15/10 s (limit is 20)
ZPA_WRITE_LIMITER = RateLimiter(max_calls=8, window=10)    # conservative: 8/10 s (limit is 10)
ZIA_READ_LIMITER = RateLimiter(max_calls=15, window=10)
ZIA_WRITE_LIMITER = RateLimiter(max_calls=8, window=10)
