from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar


Key = TypeVar("Key")
Value = TypeVar("Value")


@dataclass(frozen=True)
class _Entry(Generic[Value]):
    value: Value
    expires_at: float


class BoundedTTLCache(Generic[Key, Value]):
    """Small process-local TTL cache with deterministic LRU eviction."""

    def __init__(
        self,
        *,
        max_entries: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[Key, _Entry[Value]] = OrderedDict()
        self._lock = threading.RLock()

    def _prune_expired(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)

    def get(self, key: Key) -> Value | None:
        now = self._clock()
        with self._lock:
            self._prune_expired(now)
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry.value

    def set(self, key: Key, value: Value) -> None:
        now = self._clock()
        with self._lock:
            self._prune_expired(now)
            self._entries.pop(key, None)
            while len(self._entries) >= self.max_entries:
                self._entries.popitem(last=False)
            self._entries[key] = _Entry(value=value, expires_at=now + self.ttl_seconds)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        now = self._clock()
        with self._lock:
            self._prune_expired(now)
            return len(self._entries)
