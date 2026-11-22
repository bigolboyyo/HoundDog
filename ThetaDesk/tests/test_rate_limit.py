import unittest
from unittest.mock import patch

from rate_limit import RateLimitExceeded, SlidingWindowRateLimiter


class SlidingWindowRateLimiterTests(unittest.TestCase):
    @patch("rate_limit.monotonic", side_effect=[100.0, 101.0, 102.0, 160.0])
    def test_blocks_above_limit_until_a_request_leaves_the_window(
        self,
        monotonic: unittest.mock.Mock,
    ) -> None:
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)

        limiter.acquire()
        limiter.acquire()
        with self.assertRaises(RateLimitExceeded) as raised:
            limiter.acquire()

        self.assertEqual(raised.exception.retry_after_seconds, 58.0)
        limiter.acquire()
        self.assertEqual(monotonic.call_count, 4)

    def test_rejects_non_positive_limits(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit must be greater"):
            SlidingWindowRateLimiter(limit=0, window_seconds=60)

        with self.assertRaisesRegex(ValueError, "window_seconds must be"):
            SlidingWindowRateLimiter(limit=20, window_seconds=0)
