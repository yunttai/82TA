from __future__ import annotations

import threading
import time

from django.conf import settings
from django.http import HttpRequest

from .api_common import ApiProblem
from .cache import BoundedTTLCache
from .coordination import CoordinationUnavailable, redis_coordination
from .proxy import client_ip

_lock = threading.Lock()
_buckets = BoundedTTLCache[str, tuple[int, int]](
    max_entries=settings.RATE_LIMIT_CACHE_MAX_ENTRIES,
    ttl_seconds=settings.RATE_LIMIT_CACHE_TTL_SECONDS,
)


def enforce_rate_limit(request: HttpRequest, *, scope: str, limit: int, title: str) -> None:
    if limit <= 0:
        return
    subject = client_ip(request)
    if settings.COORDINATION_BACKEND == "redis":
        try:
            allowed = redis_coordination().enforce_rate_limit(
                scope=scope,
                subject=subject,
                limit=limit,
            )
        except CoordinationUnavailable:
            raise ApiProblem(
                429,
                "RATE_LIMITED",
                "Request coordination is temporarily unavailable",
                retryable=True,
            ) from None
        if not allowed:
            raise ApiProblem(429, "RATE_LIMITED", title, retryable=True)
        return
    window = int(time.monotonic() // 60)
    key = f"{scope}:{subject}"
    with _lock:
        bucket_window, count = _buckets.get(key) or (window, 0)
        if bucket_window != window:
            bucket_window, count = window, 0
        count += 1
        _buckets.set(key, (bucket_window, count))
        if count > limit:
            raise ApiProblem(429, "RATE_LIMITED", title, retryable=True)


def reset_rate_limits() -> None:
    """Test hook; production resets are handled by TTL expiry."""

    _buckets.clear()


def rate_limit_cache() -> BoundedTTLCache[str, tuple[int, int]]:
    return _buckets
