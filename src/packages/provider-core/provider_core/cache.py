"""Small bounded TTL cache with explicit fresh/stale/miss semantics."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from threading import Lock
from typing import Callable, Generic, Hashable, TypeVar

T = TypeVar("T")


class CacheState(StrEnum):
    MISS = "MISS"
    FRESH = "FRESH"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class CacheLookup(Generic[T]):
    state: CacheState
    value: T | None = None


@dataclass(frozen=True, slots=True)
class _Entry(Generic[T]):
    value: T
    fresh_until: float
    stale_until: float


class BoundedTTLCache(Generic[T]):
    def __init__(self, *, maximum_entries: int, clock: Callable[[], float] = monotonic) -> None:
        if maximum_entries <= 0:
            raise ValueError("maximum_entries must be positive")
        self._maximum_entries = maximum_entries
        self._clock = clock
        self._entries: OrderedDict[Hashable, _Entry[T]] = OrderedDict()
        self._lock = Lock()

    def put(self, key: Hashable, value: T, *, ttl_seconds: float, stale_seconds: float = 0.0) -> None:
        if ttl_seconds <= 0 or stale_seconds < 0:
            raise ValueError("cache TTL must be positive and stale TTL non-negative")
        now = self._clock()
        with self._lock:
            self._entries[key] = _Entry(value, now + ttl_seconds, now + ttl_seconds + stale_seconds)
            self._entries.move_to_end(key)
            while len(self._entries) > self._maximum_entries:
                self._entries.popitem(last=False)

    def get(self, key: Hashable, *, allow_stale: bool = False) -> CacheLookup[T]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return CacheLookup(CacheState.MISS)
            now = self._clock()
            if now <= entry.fresh_until:
                self._entries.move_to_end(key)
                return CacheLookup(CacheState.FRESH, entry.value)
            if allow_stale and now <= entry.stale_until:
                self._entries.move_to_end(key)
                return CacheLookup(CacheState.STALE, entry.value)
            self._entries.pop(key, None)
            return CacheLookup(CacheState.MISS)

    def invalidate(self, key: Hashable) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
