"""Secret-free operation, quota and cost telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .envelope import ProviderStatus


@dataclass(frozen=True, slots=True)
class OperationTelemetry:
    provider: str
    operation: str
    status: ProviderStatus
    latency_ms: int
    provider_call_count: int
    retry_count: int
    cache_hit: bool
    quota_units: int
    estimated_cost_microunits: int | None
    response_bytes: int

    def __post_init__(self) -> None:
        integers = (
            self.latency_ms, self.provider_call_count, self.retry_count,
            self.quota_units, self.response_bytes,
        )
        if any(value < 0 for value in integers):
            raise ValueError("telemetry counters cannot be negative")
        if self.estimated_cost_microunits is not None and self.estimated_cost_microunits < 0:
            raise ValueError("estimated cost cannot be negative")


class TelemetrySink(Protocol):
    def record(self, event: OperationTelemetry) -> None: ...


class MemoryTelemetrySink:
    def __init__(self) -> None:
        self.events: list[OperationTelemetry] = []

    def record(self, event: OperationTelemetry) -> None:
        self.events.append(event)
