# -*- coding: utf-8 -*-
"""Pure unit tests for the in-memory sliding-window rate limiter."""
from odoo.tests.common import BaseCase

from ..services.rate_limiter import RateLimiter
from ..services.exceptions import AIRateLimitError


class TestRateLimiter(BaseCase):

    def test_allows_calls_under_cap(self):
        rl = RateLimiter('scope_a', max_calls=3, window_seconds=60)
        for _ in range(3):
            rl.hit('user-1')   # must not raise

    def test_raises_when_cap_exceeded(self):
        rl = RateLimiter('scope_b', max_calls=2, window_seconds=60)
        rl.hit('user-1')
        rl.hit('user-1')
        with self.assertRaises(AIRateLimitError):
            rl.hit('user-1')

    def test_keys_are_isolated(self):
        rl = RateLimiter('scope_c', max_calls=1, window_seconds=60)
        rl.hit('user-A')
        # Different key — should still pass on the same limiter.
        rl.hit('user-B')

    def test_scopes_are_isolated(self):
        rl1 = RateLimiter('scope_d', max_calls=1, window_seconds=60)
        rl2 = RateLimiter('scope_e', max_calls=1, window_seconds=60)
        rl1.hit('u')
        # Different scope shouldn't share the bucket.
        rl2.hit('u')
