"""Production-shaped dependency factory for RI-405 source-path evidence.

The HTTP transport emits deterministic sanitized bodies in the documented Kakao
vendor shapes, and persistence is in-memory. Operation scoping, capability/evidence
gates, normalizers, production fan-in and graph optimization use product code.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from provider_core.capabilities import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
)
from provider_core.http import HttpRequest, HttpResponse, SensitiveValue
from provider_core.kakao_mobility import KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION
from provider_core.kakao_raw import (
    KAKAO_PUBLIC_TRANSIT_SCHEMA_VERSION,
    KAKAO_WALK_SCHEMA_VERSION,
)
from provider_core.named import (
    ProviderAdapterSuiteConfig,
    ProviderOperationBinding,
    ScopedProviderCredential,
    ScopedProviderTransport,
)
from provider_core.runtime import (
    ProviderRuntimeEvidenceConfig,
    RuntimeEvidence,
    RuntimeEvidenceKind,
)
from routing_api.fanin_integration import (
    InMemoryOptimizationPersistence,
    TaxiDispatchEstimate,
)
from routing_api.production_composition import ProductionCompositionDependencies
from routing_domain import TimeEstimate


_OPERATIONS = (
    (
        "KAKAO_PUBLIC_TRANSIT",
        "search_current",
        KAKAO_PUBLIC_TRANSIT_SCHEMA_VERSION,
    ),
    ("KAKAO_WALK", "route", KAKAO_WALK_SCHEMA_VERSION),
    (
        "KAKAO_DIRECTIONS",
        "route_current",
        KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION,
    ),
)
_FAULT_ORIGIN_LON = 127.187459
_RECORD_LOCK = threading.Lock()


class SanitizedVendorRawTransport:
    def __init__(self, provider: str, operation: str) -> None:
        self.provider = provider
        self.operation = operation

    def send(self, request: HttpRequest) -> HttpResponse:
        origin, destination = _coordinates(request, self.provider)
        credentials = [
            value
            for _, value in (*request.headers, *request.query)
            if isinstance(value, SensitiveValue)
        ]
        if len(credentials) != 1:
            raise AssertionError("exactly one scoped Provider credential is required")
        if math.isclose(origin[0], _FAULT_ORIGIN_LON, abs_tol=0.0000001):
            self._record(request, status=503, body=b"")
            return HttpResponse(503, "application/json", b"{}")

        if self.provider == "KAKAO_PUBLIC_TRANSIT":
            body = _transit_body(origin, destination)
        elif self.provider == "KAKAO_WALK":
            body = _walk_body(origin, destination)
        elif self.provider == "KAKAO_DIRECTIONS":
            body = _directions_body(origin, destination)
        else:  # pragma: no cover - the scoped constructor makes this unreachable.
            raise AssertionError("unexpected Provider operation")
        encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        self._record(request, status=200, body=encoded)
        return HttpResponse(200, "application/json", encoded)

    def _record(self, request: HttpRequest, *, status: int, body: bytes) -> None:
        path = Path(os.environ["RI405_PROVIDER_RECORD_PATH"])
        safe = request.safe_summary()
        record = {
            "provider": self.provider,
            "operation": self.operation,
            "sourceProof": "SANITIZED_VENDOR_RAW",
            "credential": "***",
            "request": safe,
            "responseStatus": status,
            "rawBodySha256": hashlib.sha256(body).hexdigest(),
            "rawBodyBytes": len(body),
        }
        with _RECORD_LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")


class SanitizedTaxiDispatchEstimator:
    """Explicit historical proxy; never represented as Provider observation."""

    def estimate(self, request, *, evaluated_at):
        del request, evaluated_at
        return TaxiDispatchEstimate(
            TimeEstimate(90, 150),
            "RI405_SANITIZED_HISTORICAL_PROXY",
            "ri405-taxi-dispatch-v1",
            origin="HISTORICAL_PROXY",
        )


def _coordinates(
    request: HttpRequest, provider: str
) -> tuple[tuple[float, float], tuple[float, float]]:
    query = {
        key: value
        for key, value in request.query
        if not isinstance(value, SensitiveValue)
    }
    if provider in {"KAKAO_PUBLIC_TRANSIT", "KAKAO_WALK"}:
        return (
            (float(query["start_x"]), float(query["start_y"])),
            (float(query["end_x"]), float(query["end_y"])),
        )
    origin = tuple(float(value) for value in str(query["origin"]).split(","))
    destination = tuple(
        float(value) for value in str(query["destination"]).split(",")
    )
    return (origin[0], origin[1]), (destination[0], destination[1])


def _transit_body(
    origin: tuple[float, float], destination: tuple[float, float]
) -> dict[str, Any]:
    return {
        "status": "OK",
        "properties": {
            "total": 1,
            "bus": 0,
            "subway": 1,
            "busAndSubway": 0,
            "landingURL": "https://example.invalid/sanitized-transit",
        },
        "routes": [
            {
                "properties": {
                    "type": "SUBWAY",
                    "totalDistance": 28_400,
                    "totalTime": 3_300,
                    "transfers": 0,
                    "fare": {"value": 3_000, "min": 3_000, "max": 3_000},
                },
                "steps": [
                    {
                        "properties": {
                            "guidance": "sanitized vendor-raw subway leg",
                            "type": "SUBWAY",
                            "distance": 28_400,
                            "time": 3_300,
                            "stops": [
                                {"name": "Sanitized South Origin"},
                                {"name": "Sanitized North Destination"},
                            ],
                            "vehicles": [
                                {"name": "SAN-SUBWAY", "type": "SUBWAY"}
                            ],
                        },
                        "path": {"points": [list(origin), list(destination)]},
                    }
                ],
            }
        ],
    }


def _walk_body(
    origin: tuple[float, float], destination: tuple[float, float]
) -> dict[str, Any]:
    return {
        "status": "OK",
        "route": {
            "properties": {
                "totalDistance": 28_400,
                "totalTime": 18_000,
                "landingUrl": "https://example.invalid/sanitized-walk",
            },
            "legs": [
                {
                    "properties": {"distance": 28_400, "time": 18_000},
                    "steps": [
                        {
                            "properties": {
                                "distance": 28_400,
                                "guidance": "sanitized vendor-raw walk leg",
                                "time": 18_000,
                                "x": origin[0],
                                "y": origin[1],
                            },
                            "path": {"points": [list(origin), list(destination)]},
                        }
                    ],
                }
            ],
        },
    }


def _directions_body(
    origin: tuple[float, float], destination: tuple[float, float]
) -> dict[str, Any]:
    return {
        # A raw-only field with a canary value gives the E2E an explicit leakage
        # assertion after normalization and Service projection.
        "trans_id": os.environ.get(
            "RI405_RAW_SENTINEL", "sanitized-ri405-directions"
        ),
        "routes": [
            {
                "result_code": 0,
                "result_msg": "success",
                "summary": {
                    "origin": {"name": "", "x": origin[0], "y": origin[1]},
                    "destination": {
                        "name": "",
                        "x": destination[0],
                        "y": destination[1],
                    },
                    "waypoints": [],
                    "priority": "TIME",
                    "bound": {
                        "min_x": min(origin[0], destination[0]),
                        "min_y": min(origin[1], destination[1]),
                        "max_x": max(origin[0], destination[0]),
                        "max_y": max(origin[1], destination[1]),
                    },
                    "fare": {"taxi": 7_000, "toll": 0},
                    "distance": 28_400,
                    "duration": 1_800,
                },
                "sections": [
                    {
                        "distance": 28_400,
                        "duration": 1_800,
                        "bound": {
                            "min_x": min(origin[0], destination[0]),
                            "min_y": min(origin[1], destination[1]),
                            "max_x": max(origin[0], destination[0]),
                            "max_y": max(origin[1], destination[1]),
                        },
                        "roads": [
                            {
                                "name": "sanitized road",
                                "distance": 28_400,
                                "duration": 1_800,
                                "traffic_speed": 56.8,
                                "traffic_state": 1,
                                "vertexes": [
                                    origin[0],
                                    origin[1],
                                    destination[0],
                                    destination[1],
                                ],
                            }
                        ],
                        "guides": [],
                    }
                ],
            }
        ],
    }


def build_provider_config() -> ProviderAdapterSuiteConfig:
    now = datetime.now(timezone.utc)
    capabilities = CapabilityRegistry(
        Capability(
            provider,
            operation,
            DocumentationState.DOCUMENTED,
            KeyVerificationState.KEY_VERIFIED,
            ProductionState.PRODUCTION_APPROVED,
            fixture_only=False,
        )
        for provider, operation, _ in _OPERATIONS
    )
    evidence: list[RuntimeEvidence] = []
    for index, (provider, operation, schema_version) in enumerate(_OPERATIONS):
        for kind_index, kind in enumerate(RuntimeEvidenceKind):
            version = (
                schema_version
                if kind is RuntimeEvidenceKind.RESPONSE_SCHEMA
                else f"ri405.{kind.value.lower()}.v1"
            )
            evidence.append(
                RuntimeEvidence(
                    provider,
                    operation,
                    kind,
                    f"ri405-{provider.lower()}-{operation}-{kind.value.lower()}",
                    f"{index + kind_index + 1:x}" * 64,
                    version,
                    now - timedelta(minutes=5),
                    now + timedelta(hours=1),
                )
            )
    secret = os.environ["RI405_PROVIDER_SECRET_SENTINEL"]
    bindings = tuple(
        ProviderOperationBinding(
            ScopedProviderTransport(
                provider,
                operation,
                SanitizedVendorRawTransport(provider, operation),
            ),
            ScopedProviderCredential(
                provider,
                operation,
                SensitiveValue(secret),
            ),
        )
        for provider, operation, _ in _OPERATIONS
    )
    return ProviderAdapterSuiteConfig(
        bindings=bindings,
        capabilities=capabilities,
        runtime_evidence=ProviderRuntimeEvidenceConfig(evidence),
    )


def build_dependencies() -> ProductionCompositionDependencies:
    provider_config = build_provider_config()
    return ProductionCompositionDependencies(
        provider_config=provider_config,
        persistence=InMemoryOptimizationPersistence(),
        taxi_dispatch=SanitizedTaxiDispatchEstimator(),
        capability_registry=provider_config.capabilities,
        deployment_environment="staging",
    )
