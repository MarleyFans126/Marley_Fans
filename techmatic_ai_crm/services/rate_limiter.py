# -*- coding: utf-8 -*-
"""In-memory sliding-window rate limiter.

Stateless across workers — adequate for a single-worker dev box and as
a soft cap for small teams. For multi-worker production, swap the
``_BUCKETS`` dict for a Redis-backed implementation by overriding
``RateLimiter.hit``; the public API stays the same.
"""
import time
import threading
import logging

from .exceptions import AIRateLimitError

_logger = logging.getLogger(__name__)

_BUCKETS = {}            # {(scope, key): [timestamps...]}
_BUCKETS_LOCK = threading.Lock()


class RateLimiter(object):
    """Sliding-window counter.

    :param str scope: logical name (e.g. ``'ai.generate'``) — separates
        unrelated limits so a chatty endpoint cannot starve another.
    :param int max_calls: requests allowed inside ``window_seconds``.
    :param int window_seconds: rolling window size.
    """

    def __init__(self, scope, max_calls=30, window_seconds=60):
        self.scope = scope
        self.max_calls = max_calls
        self.window_seconds = window_seconds

    def hit(self, key):
        """Record one call for ``key`` (usually ``user.id``).

        :raises AIRateLimitError: when the window is full.
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds
        bucket_key = (self.scope, key)

        with _BUCKETS_LOCK:
            stamps = _BUCKETS.get(bucket_key, [])
            stamps = [t for t in stamps if t > cutoff]
            if len(stamps) >= self.max_calls:
                _logger.warning(
                    'Rate limit hit: scope=%s key=%s (%s calls in %ss)',
                    self.scope, key, len(stamps), self.window_seconds,
                )
                raise AIRateLimitError(
                    'Too many AI requests. Please wait a moment and retry.'
                )
            stamps.append(now)
            _BUCKETS[bucket_key] = stamps
