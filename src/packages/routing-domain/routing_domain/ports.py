"""Ports consumed by the pure routing domain."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import LegCost, LegSpec


class LegEvaluator(Protocol):
    """Evaluate one canonical leg at the supplied, propagated entry time.

    Evaluation must be deterministic and side-effect free.  The domain may
    first call at the ready time to determine wait, then call again at the
    resulting movement start to determine travel, fare and reliability.
    """

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        ...


class TravelPhaseLegEvaluator(Protocol):
    """Optional explicit movement-phase hook for phase-aware adapters."""

    def evaluate_travel(
        self,
        leg: LegSpec,
        start_at: datetime,
        ready_cost: LegCost | None,
    ) -> LegCost:
        ...
