"""Framework-independent provider ports.

Implementations accept validated canonical inputs and return only canonical values
inside a sanitized envelope. Network clients and raw schemas remain adapter-local.
"""

from __future__ import annotations

from typing import Protocol

from .canonical import CanonicalItinerary
from .envelope import ProviderEnvelope
from .requests import TransitSearchRequest
from .resilience import Deadline


class TransitRouteProvider(Protocol):
    provider: str
    operation: str

    def search(
        self,
        request: TransitSearchRequest,
        *,
        deadline: Deadline,
    ) -> ProviderEnvelope[tuple[CanonicalItinerary, ...]]: ...
