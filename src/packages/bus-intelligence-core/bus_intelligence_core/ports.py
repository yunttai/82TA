"""Prediction ports kept separate for training-serving parity and fallback safety."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .domain import EtaPrediction, SeatRiskPrediction
from .feature_context import EtaFeatureContext, SeatRiskFeatureContext


@dataclass(frozen=True, slots=True)
class EtaPredictorInput:
    vehicle_ref: str
    route_id: str
    direction: str
    boarding_stop_id: str
    observed_at: datetime
    remain_seat_observed: int | None
    prediction_at: datetime | None = None
    feature_context: EtaFeatureContext | None = None


@dataclass(frozen=True, slots=True)
class SeatRiskPredictorInput:
    vehicle_ref: str
    route_id: str
    direction: str
    boarding_stop_id: str
    target_stop_id: str
    observed_at: datetime
    prediction_at: datetime
    remain_seat_observed: int | None
    feature_context: SeatRiskFeatureContext | None = None


class EtaPredictor(Protocol):
    def predict(self, value: EtaPredictorInput) -> EtaPrediction | None: ...


class SeatRiskPredictor(Protocol):
    def predict(self, value: SeatRiskPredictorInput) -> SeatRiskPrediction | None: ...
