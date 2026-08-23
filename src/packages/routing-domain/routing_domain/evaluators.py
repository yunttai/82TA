"""Small deterministic evaluator implementations for fixtures and replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Mapping

from .models import LegCost, LegSpec


@dataclass(frozen=True, slots=True)
class StaticLegEvaluator:
    costs: Mapping[str, LegCost]

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        try:
            return self.costs[leg.evaluator_key]
        except KeyError as exc:
            raise ValueError(f"no cost configured for {leg.evaluator_key}") from exc


@dataclass(frozen=True, slots=True)
class TimeBand:
    start: time
    end: time
    cost: LegCost

    def contains(self, value: time) -> bool:
        local = value.replace(tzinfo=None)
        if self.start <= self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end


@dataclass(frozen=True, slots=True)
class TimeBandLegEvaluator:
    bands: Mapping[str, tuple[TimeBand, ...]]
    fallback: Mapping[str, LegCost]

    def evaluate(self, leg: LegSpec, entry_at: datetime) -> LegCost:
        if entry_at.tzinfo is None or entry_at.utcoffset() is None:
            raise ValueError("entry_at must be timezone-aware")
        for band in self.bands.get(leg.evaluator_key, ()):
            if band.contains(entry_at.timetz()):
                return band.cost
        try:
            return self.fallback[leg.evaluator_key]
        except KeyError as exc:
            raise ValueError(f"no cost configured for {leg.evaluator_key}") from exc
