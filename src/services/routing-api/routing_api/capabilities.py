"""Projection of RI-020 capability evidence into the private API contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True, slots=True)
class CapabilityProjection:
    features: Mapping[str, bool]
    providers: tuple[Mapping[str, object], ...]
    degraded: tuple[str, ...]
    models: tuple[Mapping[str, str], ...] = ()


def capability_projection_from_registry(
    registry,
    *,
    executable_operations: frozenset[tuple[str, str]] = frozenset(),
    models: tuple[Mapping[str, str], ...] = (),
) -> CapabilityProjection:
    """Project registry evidence plus operations that passed every runtime gate."""

    capabilities = registry.all()
    providers: list[Mapping[str, object]] = []
    for provider in sorted({item.provider for item in capabilities}):
        operations = tuple(item for item in capabilities if item.provider == provider)
        documentation_state = (
            "DOCUMENTED"
            if all(item.documentation_state.value == "DOCUMENTED" for item in operations)
            else "UNKNOWN"
        )
        key_verification_state = (
            "FAILED"
            if any(item.key_verification_state.value == "FAILED" for item in operations)
            else "KEY_VERIFIED"
            if all(
                item.key_verification_state.value == "KEY_VERIFIED"
                for item in operations
            )
            else "UNVERIFIED"
        )
        production_state = (
            "BLOCKED"
            if any(item.production_state.value == "BLOCKED" for item in operations)
            else "PRODUCTION_APPROVED"
            if all(
                item.production_state.value == "PRODUCTION_APPROVED"
                for item in operations
            )
            else "UNAPPROVED"
        )
        providers.append(
            {
                "provider": provider,
                "documentationState": documentation_state,
                "keyVerificationState": key_verification_state,
                "productionState": production_state,
                "health": (
                    "OK"
                    if any(
                        (item.provider, item.operation) in executable_operations
                        for item in operations
                    )
                    else "DISABLED"
                ),
            }
        )
    current_transit = any(
        (provider, operation) in executable_operations
        for provider, operation in (
            ("KAKAO_PUBLIC_TRANSIT", "search_current"),
            ("TMAP_TRANSIT", "search"),
            ("ODSAY", "search"),
        )
    )
    current_taxi = ("KAKAO_DIRECTIONS", "route_current") in executable_operations
    model_values = tuple(dict(item) for item in models)
    if any(
        set(item) != {"purpose", "version", "state"}
        or item["purpose"] not in {"BUS_ETA", "SEAT_RISK"}
        or item["state"] != "ACTIVE"
        or not isinstance(item["version"], str)
        or not item["version"].strip()
        for item in model_values
    ) or len({item["purpose"] for item in model_values}) != len(model_values):
        raise ValueError("verified model capability projection is invalid")
    active_models = {item["purpose"] for item in model_values}
    features = {
        "currentTransit": current_transit,
        "futureTransit": False,
        "currentTaxi": current_taxi,
        "futureTaxi": ("KAKAO_FUTURE_DIRECTIONS", "route_future")
        in executable_operations,
        "multiDestinationTaxi": (
            "KAKAO_MULTI_DESTINATION",
            "many_destinations",
        )
        in executable_operations,
        "busSeatRisk": "SEAT_RISK" in active_models,
        "busEtaModel": "BUS_ETA" in active_models,
        "taxiBridge": current_transit and current_taxi,
        "realtimeRerouting": False,
    }
    degraded = [] if active_models == {"BUS_ETA", "SEAT_RISK"} else ["NO_MODEL_ACTIVE"]
    if not executable_operations:
        degraded.insert(
            0,
            "CAPABILITY_REGISTRY_UNAVAILABLE"
            if any(item.enabled for item in capabilities)
            else "NO_PROVIDER_KEY_VERIFIED",
        )
    if any(item.fixture_only for item in capabilities):
        degraded.insert(0, "FIXTURE_ONLY")
    return CapabilityProjection(
        features=features,
        providers=tuple(providers),
        degraded=tuple(degraded),
        models=model_values,
    )


def foundation_capability_projection() -> CapabilityProjection:
    # Production composition consumes the installed internal wheel. Source-tree
    # activation is reserved for explicit local fixture/test entry points.
    from provider_core.capabilities import foundation_capability_registry

    registry = foundation_capability_registry()
    capabilities = registry.all()
    projection = capability_projection_from_registry(registry)
    if any(projection.features.values()):
        raise RuntimeError("foundation capability projection cannot enable live features")
    if any(item.enabled for item in capabilities):
        raise RuntimeError("fixture capability evidence cannot become live capability")
    return projection
