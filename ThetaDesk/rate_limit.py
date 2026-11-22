from collections import deque
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class RateLimitSnapshot:
    limit: int
    remaining: int
    reset_after_seconds: float


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"The ThetaData limit is reached. Retry in "
            f"{ceil(retry_after_seconds)} seconds."
        )


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")

        self.limit = limit
        self.window_seconds = window_seconds
        self._request_times: deque[float] = deque()
        self._lock = Lock()

    def acquire(self) -> None:
        with self._lock:
            now = monotonic()
            self._expire_old_requests(now)
            if len(self._request_times) >= self.limit:
                retry_after = self.window_seconds - (
                    now - self._request_times[0]
                )
                raise RateLimitExceeded(retry_after)
            self._request_times.append(now)

    def snapshot(self) -> RateLimitSnapshot:
        with self._lock:
            now = monotonic()
            self._expire_old_requests(now)
            reset_after = 0.0
            if self._request_times:
                reset_after = self.window_seconds - (
                    now - self._request_times[0]
                )
            return RateLimitSnapshot(
                limit=self.limit,
                remaining=max(0, self.limit - len(self._request_times)),
                reset_after_seconds=max(0.0, reset_after),
            )

    def _expire_old_requests(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._request_times and self._request_times[0] <= cutoff:
            self._request_times.popleft()
