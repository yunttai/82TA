"""Sanitized result envelope shared by provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from .canonical import require_aware

T = TypeVar("T")


class ProviderStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    BAD_RESPONSE = "BAD_RESPONSE"
    DISABLED = "DISABLED"


class Freshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class QualityFlag(StrEnum):
    SCHEMA_VALIDATED = "SCHEMA_VALIDATED"
    EMPTY_RESULT = "EMPTY_RESULT"
    OBSERVED_AT_MISSING = "OBSERVED_AT_MISSING"
    STALE = "STALE"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"
    SANITIZED_FIXTURE = "SANITIZED_FIXTURE"


def classify_freshness(
    *,
    received_at: datetime,
    observed_at: datetime | None,
    maximum_age_seconds: int,
) -> Freshness:
    require_aware(received_at, "received_at")
    if maximum_age_seconds < 0:
        raise ValueError("maximum_age_seconds must be non-negative")
    if observed_at is None:
        return Freshness.UNKNOWN
    require_aware(observed_at, "observed_at")
    if observed_at > received_at:
        raise ValueError("observed_at cannot be after received_at")
    age_seconds = int((received_at - observed_at).total_seconds())
    return Freshness.FRESH if age_seconds <= maximum_age_seconds else Freshness.STALE


@dataclass(frozen=True, slots=True)
class ProviderEnvelope(Generic[T]):
    provider: str
    operation: str
    fingerprint: str
    fetched_at: datetime
    received_at: datetime
    observed_at: datetime | None
    status: ProviderStatus
    schema_version: str | None
    freshness: Freshness
    normalized_count: int
    quality_flags: tuple[QualityFlag, ...]
    payload: T | None
    latency_ms: int = 0
    cache_hit: bool = False
    message_code: str | None = None

    def __post_init__(self) -> None:
        for value, name in ((self.provider, "provider"), (self.operation, "operation"), (self.fingerprint, "fingerprint")):
            if not value or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        require_aware(self.fetched_at, "fetched_at")
        require_aware(self.received_at, "received_at")
        if self.observed_at is not None:
            require_aware(self.observed_at, "observed_at")
            if self.observed_at > self.received_at:
                raise ValueError("observed_at cannot be after received_at")
        if self.fetched_at > self.received_at:
            raise ValueError("fetched_at cannot be after received_at")
        if not isinstance(self.normalized_count, int) or isinstance(self.normalized_count, bool) or self.normalized_count < 0:
            raise ValueError("normalized_count must be a non-negative integer")
        if not isinstance(self.latency_ms, int) or isinstance(self.latency_ms, bool) or self.latency_ms < 0:
            raise ValueError("latency_ms must be a non-negative integer")
        if len(set(self.quality_flags)) != len(self.quality_flags):
            raise ValueError("quality_flags cannot contain duplicates")
        if self.status in {ProviderStatus.TIMEOUT, ProviderStatus.RATE_LIMITED, ProviderStatus.UNAVAILABLE, ProviderStatus.BAD_RESPONSE, ProviderStatus.DISABLED}:
            if self.payload is not None or self.normalized_count != 0:
                raise ValueError("failed or disabled envelopes cannot carry payload")
        if self.payload is None and self.normalized_count != 0:
            raise ValueError("normalized_count must be zero when payload is absent")
