"""Candidate selection, arbitration, boardability policy, wait and confidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from math import ceil
from statistics import median
from typing import Iterable

from .domain import (
    BusIntelligenceRequest,
    BusIntelligenceResult,
    CandidateVehicle,
    EtaPrediction,
    ModelProvenance,
    SeatRiskPrediction,
    VehicleObservation,
)
from .feature_context import (
    DEFAULT_ETA_FEATURE_CONTEXT_POLICY,
    DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY,
    EtaFeatureContext,
    FeatureContextPolicy,
    SeatRiskFeatureContext,
    resolve_eta_feature_context,
    resolve_seat_risk_feature_context,
)
from .ports import EtaPredictor, EtaPredictorInput, SeatRiskPredictor, SeatRiskPredictorInput


@dataclass(frozen=True, slots=True)
class EnginePolicy:
    stale_after_seconds: int = 180
    conservative_headway_seconds: int = 900
    max_candidates: int = 6
    max_batch_requests: int = 32
    eta_feature_context_policy: FeatureContextPolicy = (
        DEFAULT_ETA_FEATURE_CONTEXT_POLICY
    )
    seat_risk_feature_context_policy: FeatureContextPolicy = (
        DEFAULT_SEAT_RISK_FEATURE_CONTEXT_POLICY
    )

    def __post_init__(self) -> None:
        if self.stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        if self.conservative_headway_seconds <= 0:
            raise ValueError("conservative_headway_seconds must be positive")
        if self.max_candidates <= 0:
            raise ValueError("max_candidates must be positive")
        if self.max_batch_requests <= 0:
            raise ValueError("max_batch_requests must be positive")
        if not isinstance(self.eta_feature_context_policy, FeatureContextPolicy):
            raise ValueError("eta_feature_context_policy must be FeatureContextPolicy")
        if not isinstance(self.seat_risk_feature_context_policy, FeatureContextPolicy):
            raise ValueError("seat_risk_feature_context_policy must be FeatureContextPolicy")


class EtaArbitrator:
    """Fresh official ETA wins; the predictor owns position/history fallback."""

    @staticmethod
    def choose(
        observation: VehicleObservation,
        predictor: EtaPredictor,
        *,
        evaluated_at: datetime,
        stale_after_seconds: int,
        feature_context: EtaFeatureContext | None = None,
    ) -> tuple[EtaPrediction | None, tuple[str, ...]]:
        age_seconds = max(0.0, (evaluated_at - observation.observed_at).total_seconds())
        official_is_fresh = age_seconds <= stale_after_seconds
        if observation.official_eta is not None and official_is_fresh:
            return observation.official_eta, ()
        prediction = predictor.predict(
            EtaPredictorInput(
                vehicle_ref=observation.vehicle_ref,
                route_id=observation.route_id,
                direction=observation.direction,
                boarding_stop_id=observation.boarding_stop_id,
                observed_at=observation.observed_at,
                remain_seat_observed=observation.remain_seat_observed,
                prediction_at=evaluated_at,
                feature_context=feature_context,
            )
        )
        if prediction is not None and prediction.source == "OFFICIAL":
            raise ValueError("ETA predictor fallback cannot manufacture official ETA")
        warnings = ("DATA_STALE",) if observation.official_eta is not None else ()
        return prediction, warnings


class BusIntelligenceEngine:
    def __init__(
        self,
        eta_predictor: EtaPredictor,
        seat_risk_predictor: SeatRiskPredictor,
        policy: EnginePolicy | None = None,
    ) -> None:
        self._eta_predictor = eta_predictor
        self._seat_risk_predictor = seat_risk_predictor
        self._policy = policy or EnginePolicy()

    def evaluate_many(
        self, requests: Iterable[BusIntelligenceRequest]
    ) -> tuple[BusIntelligenceResult, ...]:
        """Evaluate an already-resolved request batch in deterministic input order.

        This is a pure, sequential boundary.  Provider I/O, threading, scheduling,
        and request-time dependency resolution remain the API layer's responsibility.
        The bounded look-ahead rejects an oversized iterable before invoking either
        predictor, so partial model side effects cannot masquerade as a batch result.
        Every request still passes independently through :meth:`enrich`; per-arrival
        candidate selection, nullable observations, and model provenance are never
        deduplicated or collapsed across results.
        """

        batch = tuple(islice(iter(requests), self._policy.max_batch_requests + 1))
        if len(batch) > self._policy.max_batch_requests:
            raise ValueError(
                f"Bus Intelligence batch exceeds {self._policy.max_batch_requests} requests"
            )
        return tuple(self.enrich(request) for request in batch)

    def enrich(self, request: BusIntelligenceRequest) -> BusIntelligenceResult:
        if request.mapping_grade != "HIGH" or not request.mapping_allows_bus_intelligence:
            return BusIntelligenceResult(
                enrichment_applied=False,
                candidate_vehicles=(),
                expected_wait_seconds=None,
                p90_wait_seconds=None,
                coverage="UNSUPPORTED",
                confidence_score=0.0,
                confidence_grade="UNKNOWN",
                warnings=("BUS_MAPPING_LOW_CONFIDENCE",),
                model_provenance=(),
            )

        warnings: set[str] = set()
        candidates: list[CandidateVehicle] = []
        provenance: set[ModelProvenance] = set()
        freshness: list[float] = []
        prediction_confidence: list[float] = []
        saw_historical = False
        missing_eta_count = 0
        eta_feature_context = resolve_eta_feature_context(
            request.eta_feature_context,
            request.evaluated_at,
            policy=self._policy.eta_feature_context_policy,
        )
        seat_risk_feature_context = (
            resolve_seat_risk_feature_context(
                request.seat_risk_feature_context,
                request.evaluated_at,
                policy=self._policy.seat_risk_feature_context_policy,
            )
            if request.service_type == "SEATED"
            else None
        )

        # One canonical observation per vehicle prevents duplicate probability mass.
        # A request may only consume the immutable observation snapshot that was
        # actually available at evaluation time.  Filtering before de-duplication
        # is important: a future-dated row must not shadow the latest valid row for
        # the same opaque vehicle identity.
        observed_as_of_request = tuple(
            observation
            for observation in request.observations
            if observation.observed_at <= request.evaluated_at
        )
        deduped = self._latest_observation_per_vehicle(observed_as_of_request)
        eta_candidates: list[tuple[EtaPrediction, VehicleObservation]] = []
        for observation in deduped:
            eta, eta_warnings = EtaArbitrator.choose(
                observation,
                self._eta_predictor,
                evaluated_at=request.evaluated_at,
                stale_after_seconds=self._policy.stale_after_seconds,
                feature_context=eta_feature_context,
            )
            warnings.update(eta_warnings)
            if eta is None:
                missing_eta_count += 1
                continue
            # RI-220 policy is literal: only vehicles strictly after user arrival
            # are eligible. Before and equality are both excluded.
            if eta.p50_arrival_at <= request.user_arrival_at:
                continue
            eta_candidates.append((eta, observation))

        eta_candidates.sort(key=lambda item: (item[0].p50_arrival_at, item[1].vehicle_ref))
        for eta, observation in eta_candidates[: self._policy.max_candidates]:
            age_seconds = max(0.0, (request.evaluated_at - observation.observed_at).total_seconds())
            fresh_factor = max(0.0, 1.0 - age_seconds / self._policy.stale_after_seconds)
            freshness.append(fresh_factor)
            if age_seconds > self._policy.stale_after_seconds:
                warnings.add("DATA_STALE")

            if eta.source == "POSITION_MODEL":
                warnings.add("ETA_MODEL_FALLBACK")
            elif eta.source == "HISTORICAL":
                warnings.add("HISTORICAL_PROXY_USED")
                saw_historical = True
            warnings.update(eta.warnings)
            prediction_confidence.append(eta.confidence)
            if eta.model_version is not None:
                provenance.add(
                    ModelProvenance(
                        purpose="BUS_ETA",
                        version=eta.model_version,
                        origin=(
                            "MODEL_PREDICTED"
                            if eta.source == "POSITION_MODEL"
                            else "HISTORICAL_PROXY"
                        ),
                        readiness=eta.model_readiness,
                    )
                )

            # Seat Risk is decision-relevant only for explicitly seated service.
            # General-service crowding is not a boarding-failure signal and must
            # not indirectly reduce route reliability through model confidence,
            # provenance, fallback warnings, or coverage.
            seat_risk = (
                self._predict_seat_risk(
                    request, observation, seat_risk_feature_context
                )
                if request.service_type == "SEATED"
                else None
            )
            boardability: float | None = None
            if seat_risk is not None:
                prediction_confidence.append(seat_risk.confidence)
                warnings.update(seat_risk.warnings)
                if seat_risk.origin == "HISTORICAL_PROXY":
                    warnings.add("HISTORICAL_PROXY_USED")
                    saw_historical = True
                provenance.add(
                    ModelProvenance(
                        purpose="SEAT_RISK",
                        version=seat_risk.model_version,
                        origin=seat_risk.origin,
                        readiness=seat_risk.model_readiness,
                    )
                )
                if request.service_type == "SEATED":
                    # A policy proxy, never an actual boarding probability.
                    boardability = 1.0 - seat_risk.no_seat_probability
                    warnings.add("BOARDABILITY_IS_PROXY")

            wait_p50 = ceil((eta.p50_arrival_at - request.user_arrival_at).total_seconds())
            wait_p90 = ceil((eta.p90_arrival_at - request.user_arrival_at).total_seconds())
            candidates.append(
                CandidateVehicle(
                    vehicle_ref=observation.vehicle_ref,
                    eta=eta,
                    wait_p50_seconds=wait_p50,
                    wait_p90_seconds=max(wait_p50, wait_p90),
                    remain_seat_observed=observation.remain_seat_observed,
                    seat_risk_at_boarding=seat_risk,
                    boardability_proxy=boardability,
                    future_target_remaining_seats=observation.future_target_remaining_seats,
                    future_target_observed=observation.has_future_target_observation,
                )
            )

        if not candidates:
            warnings.add("BUS_DATA_UNAVAILABLE")
            return BusIntelligenceResult(
                enrichment_applied=False,
                candidate_vehicles=(),
                expected_wait_seconds=None,
                p90_wait_seconds=None,
                coverage="UNKNOWN",
                confidence_score=0.0,
                confidence_grade="UNKNOWN",
                warnings=tuple(sorted(warnings)),
                model_provenance=tuple(sorted(provenance, key=lambda item: item.purpose)),
            )

        seated_coverage = sum(c.seat_risk_at_boarding is not None for c in candidates) / len(candidates)
        required_coverage = 1.0 if request.service_type == "GENERAL" else seated_coverage
        if request.service_type == "SEATED" and required_coverage < 1.0:
            warnings.add("BUS_DATA_UNAVAILABLE")

        confidence = self._confidence(
            mapping_score=request.mapping_score,
            freshness=freshness,
            required_coverage=required_coverage,
            prediction_confidence=prediction_confidence,
        )
        # Without any Seat Risk for a seated service there is no valid sequential
        # probability distribution. Preserve unavailable/null instead of inventing
        # a boardability probability. API projection must omit Bus Intelligence.
        if request.service_type == "SEATED" and required_coverage == 0.0:
            return BusIntelligenceResult(
                enrichment_applied=False,
                candidate_vehicles=tuple(candidates),
                expected_wait_seconds=None,
                p90_wait_seconds=None,
                coverage="PARTIAL",
                confidence_score=confidence,
                confidence_grade=self._confidence_grade(confidence),
                warnings=tuple(sorted(warnings)),
                model_provenance=tuple(
                    sorted(provenance, key=lambda item: (item.purpose, item.version, item.origin))
                ),
            )

        expected_wait, p90_wait = self._wait_distribution(candidates, request.service_type)
        if missing_eta_count > 0:
            warnings.add("BUS_DATA_UNAVAILABLE")
            coverage = "PARTIAL"
        elif saw_historical and all(c.eta.source == "HISTORICAL" for c in candidates):
            coverage = "HISTORICAL"
        elif saw_historical:
            coverage = "PARTIAL"
        elif min(freshness, default=0.0) > 0.0 and required_coverage == 1.0:
            coverage = "LIVE"
        else:
            coverage = "PARTIAL"

        return BusIntelligenceResult(
            enrichment_applied=True,
            candidate_vehicles=tuple(candidates),
            expected_wait_seconds=expected_wait,
            p90_wait_seconds=p90_wait,
            coverage=coverage,
            confidence_score=confidence,
            confidence_grade=self._confidence_grade(confidence),
            warnings=tuple(sorted(warnings)),
            model_provenance=tuple(
                sorted(provenance, key=lambda item: (item.purpose, item.version, item.origin))
            ),
        )

    def _predict_seat_risk(
        self,
        request: BusIntelligenceRequest,
        observation: VehicleObservation,
        feature_context: SeatRiskFeatureContext | None = None,
    ) -> SeatRiskPrediction | None:
        # Crucially, future_target_remaining_seats is absent from this port.
        return self._seat_risk_predictor.predict(
            SeatRiskPredictorInput(
                vehicle_ref=observation.vehicle_ref,
                route_id=observation.route_id,
                direction=observation.direction,
                boarding_stop_id=observation.boarding_stop_id,
                target_stop_id=request.target_stop_id,
                observed_at=observation.observed_at,
                prediction_at=request.evaluated_at,
                remain_seat_observed=observation.remain_seat_observed,
                feature_context=feature_context,
            )
        )

    @staticmethod
    def _latest_observation_per_vehicle(
        observations: tuple[VehicleObservation, ...],
    ) -> tuple[VehicleObservation, ...]:
        latest: dict[str, VehicleObservation] = {}
        for observation in observations:
            previous = latest.get(observation.vehicle_ref)
            if previous is None or observation.observed_at > previous.observed_at:
                latest[observation.vehicle_ref] = observation
        return tuple(latest.values())

    def _wait_distribution(
        self, candidates: list[CandidateVehicle], service_type: str
    ) -> tuple[int, int]:
        waits = [candidate.wait_p50_seconds for candidate in candidates]
        positive_gaps = [right - left for left, right in zip(waits, waits[1:]) if right > left]
        observed_headway = ceil(median(positive_gaps)) if positive_gaps else 0
        tail_headway = max(self._policy.conservative_headway_seconds, observed_headway)
        # Anchor the tail on the last candidate's conservative ETA, not its p50.
        tail_wait = candidates[-1].wait_p90_seconds + tail_headway

        survival = 1.0
        expected = 0.0
        cumulative = 0.0
        p90: int | None = None
        for candidate in candidates:
            if service_type == "GENERAL":
                # Seat/crowding is not a boarding-failure gate for general buses.
                operational_mass = 1.0
            else:
                # Unknown seat risk is conservative tail mass, not zero risk and
                # not a fabricated boardability probability.
                operational_mass = candidate.boardability_proxy or 0.0
            mass = survival * operational_mass
            expected += mass * candidate.wait_p50_seconds
            cumulative += mass
            if p90 is None and cumulative >= 0.9:
                p90 = candidate.wait_p90_seconds
            survival *= 1.0 - operational_mass

        expected += survival * tail_wait
        if p90 is None:
            p90 = tail_wait
        expected_wait = ceil(expected)
        # The optimizer consumes expected wait as its central (P50) contribution,
        # so preserve the platform-wide P90 >= P50 invariant conservatively.  This
        # widens time uncertainty only; it does not raise model confidence or turn
        # the boardability proxy into an observed boarding probability.
        return expected_wait, max(expected_wait, p90)

    @staticmethod
    def _confidence(
        *,
        mapping_score: float,
        freshness: list[float],
        required_coverage: float,
        prediction_confidence: list[float],
    ) -> float:
        freshness_score = sum(freshness) / len(freshness)
        predictor_score = (
            sum(prediction_confidence) / len(prediction_confidence)
            if prediction_confidence
            else 0.0
        )
        score = mapping_score * (
            0.35 * freshness_score + 0.35 * required_coverage + 0.30 * predictor_score
        )
        return round(max(0.0, min(1.0, score)), 6)

    @staticmethod
    def _confidence_grade(score: float) -> str:
        if score >= 0.8:
            return "HIGH"
        if score >= 0.55:
            return "MEDIUM"
        if score > 0.0:
            return "LOW"
        return "UNKNOWN"
