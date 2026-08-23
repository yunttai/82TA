"""Named, production-shaped provider adapters.

All foundation capabilities remain disabled. The live path is present only as an
injected composition seam; no concrete HTTP client, key probe, or approval claim is
included. Sanitized fixture parsing uses a closed provider/scenario allowlist.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .cache import BoundedTTLCache, CacheState
from .canonical import (
    CanonicalItinerary, CanonicalLeg, CanonicalStop, Coordinate, DataOrigin,
    MoneyRange, TimeEstimate, TransitDescriptor, TravelMode, require_aware,
)
from .capabilities import CapabilityRegistry, foundation_capability_registry
from .context import (
    BusArrivalObservation, BusLocationObservation, BusRouteRecord,
    BusStationRecord, TrafficLinkContext, WeatherContext,
)
from .context_queries import (
    GitsTrafficCorridorQuery, KmaGrid, KmaWeatherQuery, MAX_TRAFFIC_LINKS,
)
from .envelope import Freshness, ProviderEnvelope, ProviderStatus, QualityFlag, classify_freshness
from .http import AuthInjection, BoundedHttpTransport, HttpRequest, SensitiveValue
from .kakao_mobility import (
    KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION,
    normalize_current_directions,
)
from .requests import TransitSearchRequest
from .resilience import (
    CircuitBreaker, CircuitOpenError, Deadline, DeadlineExceeded,
    ProviderConcurrencyLimiter, RetryPolicy, SingleFlight, call_with_retry,
)
from .runtime import ProviderRuntimeEvidenceConfig
from .telemetry import MemoryTelemetrySink, OperationTelemetry, TelemetrySink
from .transport import TransportNetworkError, TransportSecurityError, TransportTimeoutError
from .validation import EndpointRule, FixedEndpointAllowlist, InputValidationError, SchemaValidationError


class ProviderFixtureScenario(StrEnum):
    SUCCESS = "success"
    EMPTY = "empty"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    SCHEMA_DRIFT = "schema_drift"


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    provider: str
    operation: str
    method: str
    url: str | None
    timeout_ms: int
    maximum_response_bytes: int
    quota_units: int = 1
    estimated_cost_microunits: int | None = None
    auth: AuthInjection | None = None
    response_schema_verified: bool = False
    response_schema_version: str | None = None

    def __post_init__(self) -> None:
        if self.method not in {"GET", "POST"}:
            raise ValueError("endpoint method must be GET or POST")
        if self.url is not None:
            EndpointRule(self.provider, self.operation, self.url)
        if self.timeout_ms <= 0 or self.maximum_response_bytes <= 0 or self.quota_units < 0:
            raise ValueError("endpoint bounds must be positive")
        if self.response_schema_verified != (self.response_schema_version is not None):
            raise ValueError("response schema verification and version must be set together")


ENDPOINT_SPECS: tuple[EndpointSpec, ...] = (
    EndpointSpec("KAKAO_PUBLIC_TRANSIT", "search_current", "GET", "https://dapi.kakao.com/v2/routing/publictraffic", 1800, 1_000_000, auth=AuthInjection("header", "Authorization", "KakaoAK ")),
    EndpointSpec("KAKAO_WALK", "route", "GET", "https://dapi.kakao.com/v2/routing/walk", 900, 512_000, auth=AuthInjection("header", "Authorization", "KakaoAK ")),
    EndpointSpec(
        "KAKAO_DIRECTIONS",
        "route_current",
        "GET",
        "https://apis-navi.kakaomobility.com/v1/directions",
        1000,
        1_000_000,
        auth=AuthInjection("header", "Authorization", "KakaoAK "),
        response_schema_verified=True,
        response_schema_version=KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION,
    ),
    EndpointSpec("KAKAO_MULTI_DESTINATION", "many_destinations", "POST", "https://apis-navi.kakaomobility.com/v1/destinations/directions", 1000, 1_000_000, auth=AuthInjection("header", "Authorization", "KakaoAK ")),
    EndpointSpec("KAKAO_MULTI_ORIGIN", "many_origins", "POST", "https://apis-navi.kakaomobility.com/v1/origins/directions", 1000, 1_000_000, auth=AuthInjection("header", "Authorization", "KakaoAK ")),
    EndpointSpec("KAKAO_FUTURE_DIRECTIONS", "route_future", "GET", "https://apis-navi.kakaomobility.com/v1/future/directions", 1000, 1_000_000, auth=AuthInjection("header", "Authorization", "KakaoAK ")),
    EndpointSpec("GBIS_V2", "arrivals", "GET", "https://apis.data.go.kr/6410000/busarrivalservice/v2/getBusArrivalListv2", 700, 512_000, auth=AuthInjection("query", "serviceKey")),
    EndpointSpec("GBIS_V2", "locations", "GET", None, 700, 512_000, auth=AuthInjection("query", "serviceKey")),
    EndpointSpec("GBIS_V2", "routes", "GET", "https://apis.data.go.kr/6410000/busrouteservice/getAreaBusRouteList", 700, 512_000, auth=AuthInjection("query", "serviceKey")),
    EndpointSpec("GBIS_V2", "stations", "GET", None, 700, 512_000, auth=AuthInjection("query", "serviceKey")),
    EndpointSpec("KMA", "weather_context", "GET", "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst", 700, 512_000, auth=AuthInjection("query", "serviceKey")),
    # The official GITS page currently publishes an HTTP example only. Security policy
    # forbids guessing an executable HTTPS endpoint, so the documented operation has
    # no live URL until an official HTTPS endpoint is verified.
    EndpointSpec("GITS", "traffic_context", "GET", None, 700, 1_000_000, auth=AuthInjection("query", "apiKey")),
    EndpointSpec("TMAP_TRANSIT", "search", "POST", "https://apis.openapi.sk.com/transit/routes", 1800, 1_000_000, auth=AuthInjection("header", "appKey")),
    EndpointSpec("ODSAY", "search", "GET", "https://api.odsay.com/v1/api/searchPubTransPathT", 1800, 1_000_000, auth=AuthInjection("query", "apiKey")),
)

_SPECS = {(spec.provider, spec.operation): spec for spec in ENDPOINT_SPECS}
_ALLOWLIST = FixedEndpointAllowlist(*(EndpointRule(spec.provider, spec.operation, spec.url) for spec in ENDPOINT_SPECS if spec.url is not None))


@dataclass(frozen=True, slots=True, repr=False)
class ScopedProviderCredential:
    """A secret explicitly scoped to one Provider operation.

    The scope is assembly metadata, not proof that the key works. Runtime execution
    still requires the independent capability, response-schema, and evidence gates.
    """

    provider: str
    operation: str
    value: SensitiveValue = field(repr=False)

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.operation.strip():
            raise ValueError("credential provider and operation scope are required")
        if not isinstance(self.value, SensitiveValue):
            raise TypeError("scoped provider credential must contain SensitiveValue")

    @property
    def key(self) -> tuple[str, str]:
        return self.provider, self.operation

    def __repr__(self) -> str:
        return (
            "ScopedProviderCredential("
            f"provider={self.provider!r}, operation={self.operation!r}, value=***)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ScopedProviderTransport:
    """A bounded transport explicitly scoped to one Provider operation."""

    provider: str
    operation: str
    value: BoundedHttpTransport = field(repr=False)

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.operation.strip():
            raise ValueError("transport provider and operation scope are required")
        if not callable(getattr(self.value, "send", None)):
            raise TypeError("scoped provider transport must implement send(request)")

    @property
    def key(self) -> tuple[str, str]:
        return self.provider, self.operation

    def __repr__(self) -> str:
        return (
            "ScopedProviderTransport("
            f"provider={self.provider!r}, operation={self.operation!r}, value=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ProviderOperationBinding:
    """Fail-closed assembly binding for exactly one Provider operation."""

    transport: ScopedProviderTransport
    credential: ScopedProviderCredential

    def __post_init__(self) -> None:
        if self.transport.key != self.credential.key:
            raise ValueError("provider transport and credential scopes must match exactly")

    @property
    def key(self) -> tuple[str, str]:
        return self.transport.key

    def __repr__(self) -> str:
        provider, operation = self.key
        return (
            "ProviderOperationBinding("
            f"provider={provider!r}, operation={operation!r}, "
            "transport=<redacted>, credential=***)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ProviderAdapterSuiteConfig:
    """Immutable production assembly inputs with no caller-selected URL or headers."""

    bindings: tuple[ProviderOperationBinding, ...] = ()
    capabilities: CapabilityRegistry = field(default_factory=foundation_capability_registry)
    runtime_evidence: ProviderRuntimeEvidenceConfig = field(default_factory=ProviderRuntimeEvidenceConfig)
    telemetry: TelemetrySink | None = field(default=None, repr=False, compare=False)
    clock: Callable[[], datetime] | None = field(default=None, repr=False, compare=False)
    retry_policy: RetryPolicy | None = field(default=None, repr=False, compare=False)
    _binding_map: Mapping[tuple[str, str], ProviderOperationBinding] = field(
        init=False, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.capabilities, CapabilityRegistry):
            raise TypeError("suite capabilities must be CapabilityRegistry")
        if not isinstance(self.runtime_evidence, ProviderRuntimeEvidenceConfig):
            raise TypeError(
                "suite runtime_evidence must be ProviderRuntimeEvidenceConfig"
            )
        if self.clock is not None and not callable(self.clock):
            raise TypeError("suite clock must be callable")
        if self.retry_policy is not None and not isinstance(
            self.retry_policy, RetryPolicy
        ):
            raise TypeError("suite retry_policy must be RetryPolicy")
        entries: dict[tuple[str, str], ProviderOperationBinding] = {}
        for binding in self.bindings:
            if not isinstance(binding, ProviderOperationBinding):
                raise TypeError("suite bindings must be ProviderOperationBinding values")
            if binding.key not in _SPECS:
                raise ValueError(f"unknown provider operation binding: {binding.key!r}")
            if binding.key in entries:
                raise ValueError(f"duplicate provider operation binding: {binding.key!r}")
            entries[binding.key] = binding
        object.__setattr__(self, "_binding_map", MappingProxyType(entries))

    @property
    def binding_map(self) -> Mapping[tuple[str, str], ProviderOperationBinding]:
        return self._binding_map

    def __repr__(self) -> str:
        keys = tuple(sorted(self._binding_map))
        return f"ProviderAdapterSuiteConfig(operation_scopes={keys!r}, secrets=***)"


@dataclass(frozen=True, slots=True)
class ProviderCall:
    fingerprint: str
    query: tuple[tuple[str, str | int | float | bool], ...] = ()
    json_body: dict[str, Any] | None = None
    observed_hint: datetime | None = None

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raise ValueError("provider call fingerprint is required")
        if self.observed_hint is not None:
            require_aware(self.observed_hint, "observed_hint")


class _TransientHttpError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"transient provider HTTP {status_code}")
        self.status_code = status_code


class _ProviderHttpError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider rejected request with HTTP {status_code}")
        self.status_code = status_code


class NamedProviderAdapter:
    fixture_file: str
    provider: str
    operations: tuple[str, ...]
    fixture_schema_versions: Mapping[str, str] = MappingProxyType({})

    def __init__(
        self,
        transport: BoundedHttpTransport | None = None,
        *,
        capabilities: CapabilityRegistry | None = None,
        credential: SensitiveValue | None = None,
        telemetry: TelemetrySink | None = None,
        clock: Callable[[], datetime] | None = None,
        retry_policy: RetryPolicy | None = None,
        cache: BoundedTTLCache[ProviderEnvelope[Any]] | None = None,
        breaker: CircuitBreaker | None = None,
        limiter: ProviderConcurrencyLimiter | None = None,
        single_flight: SingleFlight[ProviderEnvelope[Any]] | None = None,
        runtime_evidence: ProviderRuntimeEvidenceConfig | None = None,
        operation_bindings: Mapping[
            tuple[str, str], ProviderOperationBinding
        ] | None = None,
    ) -> None:
        if operation_bindings is not None and (transport is not None or credential is not None):
            raise ValueError(
                "operation-scoped assembly cannot be combined with a shared transport or credential"
            )
        binding_entries: dict[tuple[str, str], ProviderOperationBinding] = {}
        if operation_bindings is not None:
            for key, binding in operation_bindings.items():
                if key != binding.key:
                    raise ValueError("provider operation binding key does not match its scope")
                binding_entries[key] = binding
        self.transport = transport
        self.capabilities = capabilities or foundation_capability_registry()
        self.credential = credential
        self._operation_bindings = MappingProxyType(binding_entries)
        self._operation_scoped = operation_bindings is not None
        self.telemetry = telemetry or MemoryTelemetrySink()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.retry_policy = retry_policy or RetryPolicy(max_attempts=2, backoff_ms=(25,))
        self.cache = cache or BoundedTTLCache(maximum_entries=128)
        self.breaker = breaker or CircuitBreaker()
        self.limiter = limiter or ProviderConcurrencyLimiter(8)
        self.single_flight = single_flight or SingleFlight()
        self.runtime_evidence = runtime_evidence or ProviderRuntimeEvidenceConfig()

    def endpoint_spec(self, operation: str) -> EndpointSpec:
        if operation not in self.operations:
            raise InputValidationError(f"unsupported {self.provider} operation")
        return _SPECS[(self.provider_for(operation), operation)]

    def provider_for(self, operation: str) -> str:
        return self.provider

    def invoke(self, operation: str, call: ProviderCall, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        spec = self.endpoint_spec(operation)
        capability = self.capabilities.get(spec.provider, operation)
        runtime_gate = self.runtime_evidence.assess(
            capability,
            provider=spec.provider,
            operation=operation,
            response_schema_verified=spec.response_schema_verified,
            response_schema_version=spec.response_schema_version,
            now=self.clock(),
        )
        if not runtime_gate.executable:
            return self._disabled(spec, operation, call.fingerprint)
        transport = self.transport
        credential = self.credential
        if self._operation_scoped:
            binding = self._operation_bindings.get((spec.provider, operation))
            if binding is None:
                return self._disabled(spec, operation, call.fingerprint)
            transport = binding.transport.value
            credential = binding.credential.value
        if spec.url is None or transport is None or credential is None or spec.auth is None:
            return self._disabled(spec, operation, call.fingerprint)
        _ALLOWLIST.assert_exact(spec.provider, operation, spec.url)
        cached = self.cache.get((spec.provider, operation, call.fingerprint))
        if cached.state is CacheState.FRESH and cached.value is not None:
            return replace(cached.value, cache_hit=True)

        def work() -> ProviderEnvelope[Any]:
            self.breaker.before_call()
            attempts = 0
            response_bytes = 0

            def send(timeout_ms: int):
                nonlocal attempts, response_bytes
                attempts += 1
                request = HttpRequest(
                    method=spec.method, url=spec.url, query=call.query,
                    json_body=call.json_body, timeout_ms=min(timeout_ms, spec.timeout_ms),
                    maximum_response_bytes=spec.maximum_response_bytes,
                    headers=(("Accept", "application/json"),),
                )
                request = spec.auth.apply(request, credential)
                response = self.limiter.run(lambda: transport.send(request))
                response_bytes = len(response.body)
                if response.status_code == 429 or response.status_code >= 500:
                    raise _TransientHttpError(response.status_code)
                if response.status_code < 200 or response.status_code >= 300:
                    raise _ProviderHttpError(response.status_code)
                return response

            try:
                response = call_with_retry(
                    send, deadline=deadline, timeout_cap_ms=spec.timeout_ms,
                    policy=self.retry_policy,
                    retryable=lambda error: isinstance(
                        error, (_TransientHttpError, TransportNetworkError),
                    ),
                )
                body = response.json_object(maximum_bytes=spec.maximum_response_bytes)
                now = self.clock()
                payload = self._parse(operation, body, call.observed_hint)
                envelope = self._ok_envelope(spec, operation, call.fingerprint, now, call.observed_hint, payload)
                self.breaker.record_success()
                self.cache.put((spec.provider, operation, call.fingerprint), envelope, ttl_seconds=30, stale_seconds=30)
                self._record(spec, envelope, calls=attempts, retries=max(0, attempts - 1), response_bytes=response_bytes)
                return envelope
            except _TransientHttpError as exc:
                self.breaker.record_failure()
                now = self.clock()
                envelope = ProviderEnvelope(
                    provider=spec.provider, operation=operation, fingerprint=call.fingerprint,
                    fetched_at=now, received_at=now, observed_at=None,
                    status=ProviderStatus.RATE_LIMITED if exc.status_code == 429 else ProviderStatus.UNAVAILABLE, schema_version=None,
                    freshness=Freshness.UNKNOWN, normalized_count=0, quality_flags=(), payload=None,
                    message_code="RATE_LIMITED" if exc.status_code == 429 else None,
                )
                self._record(spec, envelope, calls=attempts, retries=max(0, attempts - 1), response_bytes=response_bytes)
                return envelope
            except _ProviderHttpError:
                self.breaker.record_failure()
                now = self.clock()
                envelope = ProviderEnvelope(
                    provider=spec.provider, operation=operation,
                    fingerprint=call.fingerprint,
                    fetched_at=now, received_at=now, observed_at=None,
                    status=ProviderStatus.UNAVAILABLE, schema_version=None,
                    freshness=Freshness.UNKNOWN, normalized_count=0,
                    quality_flags=(), payload=None,
                )
                self._record(
                    spec,
                    envelope,
                    calls=attempts,
                    retries=max(0, attempts - 1),
                    response_bytes=response_bytes,
                )
                return envelope
            except TransportNetworkError:
                self.breaker.record_failure()
                now = self.clock()
                envelope = ProviderEnvelope(
                    provider=spec.provider, operation=operation, fingerprint=call.fingerprint,
                    fetched_at=now, received_at=now, observed_at=None,
                    status=ProviderStatus.UNAVAILABLE, schema_version=None,
                    freshness=Freshness.UNKNOWN, normalized_count=0,
                    quality_flags=(), payload=None,
                )
                self._record(spec, envelope, calls=attempts, retries=max(0, attempts - 1), response_bytes=response_bytes)
                return envelope
            except (DeadlineExceeded, TransportTimeoutError):
                self.breaker.record_failure()
                now = self.clock()
                envelope = ProviderEnvelope(
                    provider=spec.provider, operation=operation, fingerprint=call.fingerprint,
                    fetched_at=now, received_at=now, observed_at=None,
                    status=ProviderStatus.TIMEOUT, schema_version=None,
                    freshness=Freshness.UNKNOWN, normalized_count=0, quality_flags=(), payload=None,
                )
                self._record(spec, envelope, calls=attempts, retries=max(0, attempts - 1), response_bytes=response_bytes)
                return envelope
            except (SchemaValidationError, TransportSecurityError, ValueError, KeyError, TypeError):
                self.breaker.record_failure()
                now = self.clock()
                envelope = ProviderEnvelope(
                    provider=spec.provider, operation=operation, fingerprint=call.fingerprint,
                    fetched_at=now, received_at=now, observed_at=None,
                    status=ProviderStatus.BAD_RESPONSE, schema_version=None,
                    freshness=Freshness.UNKNOWN, normalized_count=0,
                    quality_flags=(QualityFlag.SCHEMA_DRIFT,), payload=None,
                    message_code="PROVIDER_BAD_RESPONSE",
                )
                self._record(spec, envelope, calls=attempts, retries=max(0, attempts - 1), response_bytes=response_bytes)
                return envelope

        try:
            return self.single_flight.do((spec.provider, operation, call.fingerprint), work)
        except CircuitOpenError:
            return self._unavailable(spec, operation, call.fingerprint)

    def fixture(self, operation: str, scenario: ProviderFixtureScenario) -> ProviderEnvelope[Any]:
        spec = self.endpoint_spec(operation)
        path = Path(__file__).resolve().parent / "fixtures" / self.fixture_file
        raw = path.read_bytes()
        if len(raw) > 256_000:
            raise SchemaValidationError("fixture file exceeds byte limit")
        document = json.loads(raw)
        _require_exact(document, {"fixtureVersion", "provider", "operations"}, "fixture")
        if document["provider"] != self.provider:
            raise SchemaValidationError("fixture provider mismatch")
        if not isinstance(document["operations"], dict):
            raise SchemaValidationError("fixture operations must be an object")
        operation_cases = document["operations"].get(operation, {})
        generic_cases = document["operations"].get("*", {})
        if not isinstance(operation_cases, dict) or not isinstance(generic_cases, dict):
            raise SchemaValidationError("fixture operation cases must be objects")
        case = operation_cases.get(scenario.value, generic_cases.get(scenario.value))
        if case is None:
            raise SchemaValidationError("fixture operation/scenario missing")
        _require_exact(case, {"fetchedAt", "receivedAt", "observedAt", "schemaVersion", "httpStatus", "contentType", "body"}, "fixture case")
        fetched = _time(case["fetchedAt"])
        received = _time(case["receivedAt"])
        observed = _time(case["observedAt"]) if case["observedAt"] is not None else None
        fingerprint = hashlib.sha256(raw + operation.encode() + scenario.value.encode()).hexdigest()
        try:
            self._validate_fixture_schema(
                document["fixtureVersion"], operation, case["schemaVersion"]
            )
        except SchemaValidationError:
            return self._fixture_bad(spec, operation, fingerprint, fetched, received)
        if case["contentType"] != "application/json":
            return self._fixture_bad(spec, operation, fingerprint, fetched, received)
        if case["httpStatus"] == 429:
            return ProviderEnvelope(
                provider=spec.provider, operation=operation, fingerprint=fingerprint,
                fetched_at=fetched, received_at=received, observed_at=observed,
                status=ProviderStatus.RATE_LIMITED, schema_version=case["schemaVersion"],
                freshness=Freshness.UNKNOWN, normalized_count=0,
                quality_flags=(QualityFlag.SANITIZED_FIXTURE,), payload=None,
                message_code="RATE_LIMITED",
            )
        if case["httpStatus"] >= 400:
            return ProviderEnvelope(
                provider=spec.provider, operation=operation, fingerprint=fingerprint,
                fetched_at=fetched, received_at=received, observed_at=observed,
                status=ProviderStatus.UNAVAILABLE, schema_version=case["schemaVersion"],
                freshness=Freshness.UNKNOWN, normalized_count=0,
                quality_flags=(QualityFlag.SANITIZED_FIXTURE,), payload=None,
                message_code="TRANSIT_PROVIDER_UNAVAILABLE" if "TRANSIT" in spec.provider or spec.provider in {"ODSAY", "GBIS_V2"} else None,
            )
        try:
            payload = self._parse(operation, case["body"], observed)
        except (SchemaValidationError, ValueError, KeyError, TypeError):
            return self._fixture_bad(spec, operation, fingerprint, fetched, received)
        flags = [QualityFlag.SCHEMA_VALIDATED, QualityFlag.SANITIZED_FIXTURE]
        if observed is None:
            flags.append(QualityFlag.OBSERVED_AT_MISSING)
        if len(payload) == 0:
            flags.append(QualityFlag.EMPTY_RESULT)
        return ProviderEnvelope(
            provider=spec.provider, operation=operation, fingerprint=fingerprint,
            fetched_at=fetched, received_at=received, observed_at=observed,
            status=ProviderStatus.OK, schema_version=case["schemaVersion"],
            freshness=classify_freshness(received_at=received, observed_at=observed, maximum_age_seconds=120),
            normalized_count=len(payload), quality_flags=tuple(flags), payload=payload,
        )

    def _validate_fixture_schema(
        self, fixture_version: Any, operation: str, schema_version: Any
    ) -> None:
        if fixture_version != "1.0":
            raise SchemaValidationError("fixture document version mismatch")
        if not isinstance(schema_version, str) or not schema_version.strip():
            raise SchemaValidationError("fixture response schema version is required")
        expected = self.fixture_schema_versions.get(operation)
        if expected is not None and schema_version != expected:
            raise SchemaValidationError("fixture response schema version mismatch")

    def _fixture_bad(self, spec: EndpointSpec, operation: str, fingerprint: str, fetched: datetime, received: datetime) -> ProviderEnvelope[Any]:
        return ProviderEnvelope(
            provider=spec.provider, operation=operation, fingerprint=fingerprint,
            fetched_at=fetched, received_at=received, observed_at=None,
            status=ProviderStatus.BAD_RESPONSE, schema_version=None,
            freshness=Freshness.UNKNOWN, normalized_count=0,
            quality_flags=(QualityFlag.SCHEMA_DRIFT, QualityFlag.SANITIZED_FIXTURE), payload=None,
            message_code="PROVIDER_BAD_RESPONSE",
        )

    def _ok_envelope(self, spec: EndpointSpec, operation: str, fingerprint: str, now: datetime, observed: datetime | None, payload: tuple[Any, ...]) -> ProviderEnvelope[Any]:
        if not spec.response_schema_verified or spec.response_schema_version is None:
            raise SchemaValidationError("verified response schema version is required")
        quality_flags = [QualityFlag.SCHEMA_VALIDATED]
        if observed is None:
            quality_flags.append(QualityFlag.OBSERVED_AT_MISSING)
        return ProviderEnvelope(
            provider=spec.provider, operation=operation, fingerprint=fingerprint,
            fetched_at=now, received_at=now, observed_at=observed,
            status=ProviderStatus.OK, schema_version=spec.response_schema_version,
            freshness=classify_freshness(received_at=now, observed_at=observed, maximum_age_seconds=120),
            normalized_count=len(payload), quality_flags=tuple(quality_flags), payload=payload,
        )

    def _unavailable(self, spec: EndpointSpec, operation: str, fingerprint: str) -> ProviderEnvelope[Any]:
        now = self.clock()
        envelope = ProviderEnvelope(
            provider=spec.provider, operation=operation, fingerprint=fingerprint,
            fetched_at=now, received_at=now, observed_at=None,
            status=ProviderStatus.UNAVAILABLE, schema_version=None,
            freshness=Freshness.UNKNOWN, normalized_count=0, quality_flags=(), payload=None,
        )
        self._record(spec, envelope, calls=0, retries=0, response_bytes=0)
        return envelope

    def _disabled(self, spec: EndpointSpec, operation: str, fingerprint: str) -> ProviderEnvelope[Any]:
        now = self.clock()
        envelope = ProviderEnvelope(
            provider=spec.provider, operation=operation, fingerprint=fingerprint,
            fetched_at=now, received_at=now, observed_at=None,
            status=ProviderStatus.DISABLED, schema_version=None,
            freshness=Freshness.UNKNOWN, normalized_count=0,
            quality_flags=(), payload=None, latency_ms=0, cache_hit=False,
        )
        self._record(spec, envelope, calls=0, retries=0, response_bytes=0)
        return envelope

    def _record(self, spec: EndpointSpec, envelope: ProviderEnvelope[Any], *, calls: int, retries: int, response_bytes: int) -> None:
        self.telemetry.record(OperationTelemetry(
            provider=spec.provider, operation=spec.operation, status=envelope.status,
            latency_ms=envelope.latency_ms, provider_call_count=calls, retry_count=retries,
            cache_hit=envelope.cache_hit, quota_units=spec.quota_units * calls,
            estimated_cost_microunits=None if calls == 0 or spec.estimated_cost_microunits is None else spec.estimated_cost_microunits * calls,
            response_bytes=response_bytes,
        ))

    def _parse(self, operation: str, body: Any, observed: datetime | None) -> tuple[Any, ...]:
        raise NotImplementedError


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise SchemaValidationError("fixture timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require_aware(parsed, "fixture timestamp")
    return parsed


def _require_exact(value: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SchemaValidationError(f"{path} schema mismatch")
    return value


def _fingerprint(*values: Any) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _route_payload(body: Any, *, mode: TravelMode, provider: str, observed: datetime | None) -> tuple[CanonicalItinerary, ...]:
    """Parse the internal sanitized-fixture schema, never a claimed vendor raw shape."""
    root = _require_exact(body, {"routes"}, f"{provider}.body")
    if not isinstance(root["routes"], list):
        raise SchemaValidationError("routes must be an array")
    out = []
    for index, route in enumerate(root["routes"]):
        _require_exact(route, {"id", "origin", "destination", "durationSeconds", "p90Seconds", "distanceMeters", "fareKrw", "routeId", "routeLabel", "direction", "geometry"}, "route")
        origin = _coordinate(route["origin"])
        destination = _coordinate(route["destination"])
        geometry = tuple(_coordinate(point) for point in route["geometry"])
        if not geometry or geometry[0] != origin or geometry[-1] != destination:
            raise SchemaValidationError("route geometry endpoints mismatch")
        duration = route["durationSeconds"]
        p90 = route["p90Seconds"]
        distance = route["distanceMeters"]
        fare = route["fareKrw"]
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (duration, p90, distance, fare)):
            raise SchemaValidationError("route units must be integer")
        transit = None
        if mode in {TravelMode.BUS, TravelMode.SUBWAY, TravelMode.GTX, TravelMode.TRAIN}:
            transit = TransitDescriptor(route_label=route["routeLabel"], external_route_id=route["routeId"], direction=route["direction"])
        leg = CanonicalLeg(
            leg_id=f"{provider.lower()}-leg-{index}", sequence=0, mode=mode,
            from_stop=CanonicalStop("Sanitized Origin", origin, f"{provider.lower()}-origin"),
            to_stop=CanonicalStop("Sanitized Destination", destination, f"{provider.lower()}-destination"),
            duration=TimeEstimate(duration, p90, DataOrigin.PROVIDER_ESTIMATE),
            distance_meters=distance,
            fare=MoneyRange(fare, fare, fare, DataOrigin.PROVIDER_ESTIMATE),
            transit=transit, geometry=geometry,
        )
        out.append(CanonicalItinerary(route["id"], (leg,)))
    return tuple(out)


def _coordinate(value: Any) -> Coordinate:
    _require_exact(value, {"lon", "lat"}, "coordinate")
    if not all(isinstance(value[key], (int, float)) and not isinstance(value[key], bool) for key in ("lon", "lat")):
        raise SchemaValidationError("coordinate values must be numeric")
    return Coordinate(float(value["lon"]), float(value["lat"]))


def _context_schema_drift(
    envelope: ProviderEnvelope[Any],
) -> ProviderEnvelope[Any]:
    flags = tuple(
        dict.fromkeys(
            flag
            for flag in (*envelope.quality_flags, QualityFlag.SCHEMA_DRIFT)
            if flag is not QualityFlag.SCHEMA_VALIDATED
        )
    )
    return replace(
        envelope,
        observed_at=None,
        status=ProviderStatus.BAD_RESPONSE,
        schema_version=None,
        freshness=Freshness.UNKNOWN,
        normalized_count=0,
        quality_flags=flags,
        payload=None,
        message_code="PROVIDER_BAD_RESPONSE",
    )


class KakaoTransitAdapter(NamedProviderAdapter):
    fixture_file = "named_kakao_transit.json"
    provider = "KAKAO_PUBLIC_TRANSIT"
    operations = ("search_current",)

    def search(self, request: TransitSearchRequest, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        call = ProviderCall(
            request.fingerprint(),
            query=(("x", request.origin.lon), ("y", request.origin.lat), ("ex", request.destination.lon), ("ey", request.destination.lat)),
            observed_hint=request.departure_time,
        )
        return self.invoke("search_current", call, deadline=deadline)

    def _parse(self, operation: str, body: Any, observed: datetime | None) -> tuple[Any, ...]:
        return _route_payload(body, mode=TravelMode.BUS, provider=self.provider, observed=observed)


class KakaoWalkAdapter(NamedProviderAdapter):
    fixture_file = "named_kakao_walk.json"
    provider = "KAKAO_WALK"
    operations = ("route",)

    def route(self, request: TransitSearchRequest, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        return self.invoke("route", ProviderCall(
            request.fingerprint(),
            query=(("x", request.origin.lon), ("y", request.origin.lat), ("ex", request.destination.lon), ("ey", request.destination.lat)),
            observed_hint=request.departure_time,
        ), deadline=deadline)

    def _parse(self, operation: str, body: Any, observed: datetime | None) -> tuple[Any, ...]:
        return _route_payload(body, mode=TravelMode.WALK, provider=self.provider, observed=observed)


class KakaoMobilityDirectionsAdapter(NamedProviderAdapter):
    fixture_file = "named_kakao_mobility.json"
    provider = "KAKAO_MOBILITY"
    operations = ("route_current", "many_destinations", "many_origins", "route_future")
    fixture_schema_versions = MappingProxyType(
        {"route_current": KAKAO_DIRECTIONS_CURRENT_SCHEMA_VERSION}
    )
    _providers = {
        "route_current": "KAKAO_DIRECTIONS",
        "many_destinations": "KAKAO_MULTI_DESTINATION",
        "many_origins": "KAKAO_MULTI_ORIGIN",
        "route_future": "KAKAO_FUTURE_DIRECTIONS",
    }

    def provider_for(self, operation: str) -> str:
        return self._providers[operation]

    def route(self, request: TransitSearchRequest, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        return self.invoke("route_current", self._current_call(request), deadline=deadline)

    def many_destinations(self, origin: Coordinate, destinations: tuple[Coordinate, ...], *, deadline: Deadline) -> ProviderEnvelope[Any]:
        _bounded_coordinates(destinations)
        return self.invoke("many_destinations", ProviderCall(
            _fingerprint("many-destinations", origin, destinations),
            json_body={"origins": [{"x": origin.lon, "y": origin.lat}], "destinations": [{"x": item.lon, "y": item.lat} for item in destinations]},
        ), deadline=deadline)

    def many_origins(self, origins: tuple[Coordinate, ...], destination: Coordinate, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        _bounded_coordinates(origins)
        return self.invoke("many_origins", ProviderCall(
            _fingerprint("many-origins", origins, destination),
            json_body={"origins": [{"x": item.lon, "y": item.lat} for item in origins], "destinations": [{"x": destination.lon, "y": destination.lat}]},
        ), deadline=deadline)

    def future(self, request: TransitSearchRequest, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        return self.invoke("route_future", self._single_call(request), deadline=deadline)

    @staticmethod
    def _current_call(request: TransitSearchRequest) -> ProviderCall:
        return ProviderCall(
            request.fingerprint(),
            query=(
                ("origin", f"{request.origin.lon},{request.origin.lat}"),
                (
                    "destination",
                    f"{request.destination.lon},{request.destination.lat}",
                ),
                ("priority", "RECOMMEND"),
                ("car_fuel", "GASOLINE"),
                ("car_hipass", "false"),
                ("alternatives", "false"),
                ("road_details", "false"),
                ("summary", "false"),
            ),
            # Current Directions has no response observation timestamp.  Departure
            # time remains in the request fingerprint but is not falsely presented as
            # Provider observation time.
            observed_hint=None,
        )

    @staticmethod
    def _single_call(request: TransitSearchRequest) -> ProviderCall:
        return ProviderCall(
            request.fingerprint(),
            query=(("origin", f"{request.origin.lon},{request.origin.lat}"), ("destination", f"{request.destination.lon},{request.destination.lat}")),
            observed_hint=request.departure_time,
        )

    def _parse(self, operation: str, body: Any, observed: datetime | None) -> tuple[Any, ...]:
        if operation == "route_current":
            return self.normalize_current_response(body)
        return _route_payload(body, mode=TravelMode.TAXI, provider=self.provider_for(operation), observed=observed)

    @staticmethod
    def normalize_current_response(body: Any) -> tuple[CanonicalItinerary, ...]:
        """Normalize a decoded response without performing HTTP or promoting gates."""

        return normalize_current_directions(body)


def _bounded_coordinates(values: tuple[Coordinate, ...]) -> None:
    if not 1 <= len(values) <= 30:
        raise InputValidationError("matrix coordinates must contain one to thirty points")


class GbisAdapter(NamedProviderAdapter):
    fixture_file = "named_gbis.json"
    provider = "GBIS_V2"
    operations = ("arrivals", "locations", "routes", "stations")

    def arrivals(self, station_id: str, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        return self.invoke("arrivals", self._id_call("stationId", station_id), deadline=deadline)

    def locations(self, route_id: str, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        return self.invoke("locations", self._id_call("routeId", route_id), deadline=deadline)

    def routes(self, keyword: str, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        return self.invoke("routes", self._id_call("keyword", keyword), deadline=deadline)

    def stations(self, coordinate: Coordinate, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        return self.invoke("stations", ProviderCall(
            _fingerprint("stations", coordinate), query=(("x", coordinate.lon), ("y", coordinate.lat)),
        ), deadline=deadline)

    @staticmethod
    def _id_call(name: str, value: str) -> ProviderCall:
        if not value or len(value) > 64 or any(ord(char) < 32 for char in value):
            raise InputValidationError("provider identifier is invalid")
        return ProviderCall(_fingerprint(name, value), query=((name, value),))

    def _parse(self, operation: str, body: Any, observed: datetime | None) -> tuple[Any, ...]:
        if observed is None:
            raise SchemaValidationError("GBIS observed timestamp is required")
        root = _require_exact(body, {"items"}, "GBIS body")
        items = root["items"]
        if not isinstance(items, list):
            raise SchemaValidationError("GBIS items must be an array")
        if operation == "arrivals":
            result = []
            for item in items:
                _require_allowed(
                    item,
                    {"routeId", "stationId", "predictTimeMinutes", "remainSeatCnt"},
                    {"vehicleToken"},
                    "GBIS arrival",
                )
                minutes = _integer(item["predictTimeMinutes"], "predictTimeMinutes", minimum=0)
                seats = _integer(item["remainSeatCnt"], "remainSeatCnt", minimum=-1)
                result.append(BusArrivalObservation(
                    item["routeId"], item["stationId"], minutes * 60,
                    None if seats == -1 else seats, observed, item.get("vehicleToken"),
                ))
            return tuple(result)
        if operation == "locations":
            result = []
            for item in items:
                _require_exact(item, {"routeId", "vehicleToken", "stationSeq", "coordinate"}, "GBIS location")
                result.append(BusLocationObservation(item["routeId"], item["vehicleToken"], _integer(item["stationSeq"], "stationSeq", minimum=0), _coordinate(item["coordinate"]), observed))
            return tuple(result)
        if operation == "routes":
            return tuple(BusRouteRecord(item["routeId"], item["routeName"], item.get("routeType")) for item in _exact_items(items, {"routeId", "routeName", "routeType"}, "GBIS route"))
        return tuple(BusStationRecord(item["stationId"], item["stationName"], _coordinate(item["coordinate"])) for item in _exact_items(items, {"stationId", "stationName", "coordinate"}, "GBIS station"))


class KmaContextAdapter(NamedProviderAdapter):
    fixture_file = "named_kma.json"
    provider = "KMA"
    operations = ("weather_context",)
    fixture_schema_versions = MappingProxyType(
        {"weather_context": "kma.fixture.v1"}
    )

    def context(self, *, nx: int, ny: int, coordinate: Coordinate, observed_at: datetime, deadline: Deadline) -> ProviderEnvelope[Any]:
        try:
            request = KmaWeatherQuery(coordinate, observed_at, KmaGrid(nx, ny))
        except ValueError as exc:
            raise InputValidationError(str(exc)) from exc
        return self.context_query(request, deadline=deadline)

    def context_query(
        self, request: KmaWeatherQuery, *, deadline: Deadline
    ) -> ProviderEnvelope[Any]:
        if not isinstance(request, KmaWeatherQuery):
            raise InputValidationError("KMA context request has an invalid type")
        envelope = self.invoke("weather_context", ProviderCall(
            request.fingerprint(),
            query=request.provider_query,
            observed_hint=request.observed_at,
            json_body={
                "coordinate": {
                    "lon": request.coordinate.lon,
                    "lat": request.coordinate.lat,
                }
            },
        ), deadline=deadline)
        return self._guard_request(envelope, request)

    def fixture_context(
        self, request: KmaWeatherQuery, scenario: ProviderFixtureScenario
    ) -> ProviderEnvelope[Any]:
        if not isinstance(request, KmaWeatherQuery):
            raise InputValidationError("KMA context request has an invalid type")
        envelope = self.fixture("weather_context", scenario)
        envelope = replace(
            envelope,
            fingerprint=_fingerprint(
                "fixture-context", request.identity_version,
                request.fingerprint(), envelope.fingerprint,
            ),
        )
        return self._guard_request(envelope, request)

    @staticmethod
    def _guard_request(
        envelope: ProviderEnvelope[Any], request: KmaWeatherQuery
    ) -> ProviderEnvelope[Any]:
        if envelope.status is not ProviderStatus.OK or envelope.payload is None:
            return envelope
        if len(envelope.payload) > 1 or any(
            not isinstance(item, WeatherContext)
            or item.coordinate != request.coordinate
            for item in envelope.payload
        ):
            return _context_schema_drift(envelope)
        return envelope

    def _parse(self, operation: str, body: Any, observed: datetime | None) -> tuple[Any, ...]:
        if observed is None:
            raise SchemaValidationError("KMA observed timestamp is required")
        root = _require_exact(body, {"coordinate", "items"}, "KMA body")
        coordinate = _coordinate(root["coordinate"])
        if not isinstance(root["items"], list):
            raise SchemaValidationError("KMA items must be an array")
        values: dict[str, float] = {}
        for item in root["items"]:
            _require_exact(item, {"category", "value"}, "KMA item")
            if item["category"] not in {"T1H", "RN1"}:
                raise SchemaValidationError("KMA category/value drift")
            if item["category"] in values:
                raise SchemaValidationError("KMA category is duplicated")
            values[item["category"]] = _number(
                item["value"], f"KMA {item['category']}",
                minimum=0 if item["category"] == "RN1" else None,
            )
        if not values:
            return ()
        return (WeatherContext(coordinate, observed, values.get("T1H"), values.get("RN1")),)


class GitsTrafficAdapter(NamedProviderAdapter):
    fixture_file = "named_gits.json"
    provider = "GITS"
    operations = ("traffic_context",)
    fixture_schema_versions = MappingProxyType(
        {"traffic_context": "gits.fixture.v1"}
    )

    def context(self, minimum: Coordinate, maximum: Coordinate, *, observed_at: datetime, deadline: Deadline) -> ProviderEnvelope[Any]:
        try:
            request = GitsTrafficCorridorQuery.from_bounds(
                minimum, maximum, observed_at
            )
        except ValueError as exc:
            raise InputValidationError(str(exc)) from exc
        return self.context_query(request, deadline=deadline)

    def context_query(
        self, request: GitsTrafficCorridorQuery, *, deadline: Deadline
    ) -> ProviderEnvelope[Any]:
        if not isinstance(request, GitsTrafficCorridorQuery):
            raise InputValidationError("GITS context request has an invalid type")
        envelope = self.invoke("traffic_context", ProviderCall(
            request.fingerprint(), query=request.provider_query,
            observed_hint=request.observed_at,
        ), deadline=deadline)
        return self._guard_request(envelope, request)

    def fixture_context(
        self,
        request: GitsTrafficCorridorQuery,
        scenario: ProviderFixtureScenario,
    ) -> ProviderEnvelope[Any]:
        if not isinstance(request, GitsTrafficCorridorQuery):
            raise InputValidationError("GITS context request has an invalid type")
        envelope = self.fixture("traffic_context", scenario)
        envelope = replace(
            envelope,
            fingerprint=_fingerprint(
                "fixture-context", request.identity_version,
                request.fingerprint(), envelope.fingerprint,
            ),
        )
        return self._guard_request(envelope, request)

    @staticmethod
    def _guard_request(
        envelope: ProviderEnvelope[Any], request: GitsTrafficCorridorQuery
    ) -> ProviderEnvelope[Any]:
        if envelope.status is not ProviderStatus.OK or envelope.payload is None:
            return envelope
        if len(envelope.payload) > request.maximum_links or any(
            not isinstance(item, TrafficLinkContext)
            or not request.accepts_link(item.link_external_id)
            for item in envelope.payload
        ):
            return _context_schema_drift(envelope)
        return envelope

    def _parse(self, operation: str, body: Any, observed: datetime | None) -> tuple[Any, ...]:
        root = _require_exact(body, {"data"}, "GITS body")
        if not isinstance(root["data"], list):
            raise SchemaValidationError("GITS data must be an array")
        if len(root["data"]) > MAX_TRAFFIC_LINKS:
            raise SchemaValidationError("GITS link count exceeds the response bound")
        result = []
        external_ids: set[str] = set()
        for item in root["data"]:
            _require_exact(item, {"linkId", "speedKph", "travelTimeSeconds", "createdAt"}, "GITS item")
            if item["linkId"] in external_ids:
                raise SchemaValidationError("GITS link identifier is duplicated")
            external_ids.add(item["linkId"])
            item_observed = _time(item["createdAt"])
            result.append(TrafficLinkContext(item["linkId"], _integer(item["speedKph"], "speedKph", minimum=0), _number(item["travelTimeSeconds"], "travelTimeSeconds", minimum=0), item_observed))
        return tuple(result)


class TmapTransitAdapter(KakaoTransitAdapter):
    fixture_file = "named_tmap.json"
    provider = "TMAP_TRANSIT"
    operations = ("search",)

    def search(self, request: TransitSearchRequest, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        return self.invoke("search", ProviderCall(
            request.fingerprint(),
            json_body={"startX": str(request.origin.lon), "startY": str(request.origin.lat), "endX": str(request.destination.lon), "endY": str(request.destination.lat), "count": request.max_itineraries, "format": "json"},
            observed_hint=request.departure_time,
        ), deadline=deadline)


class OdsayTransitAdapter(KakaoTransitAdapter):
    fixture_file = "named_odsay.json"
    provider = "ODSAY"
    operations = ("search",)

    def search(self, request: TransitSearchRequest, *, deadline: Deadline) -> ProviderEnvelope[Any]:
        return self.invoke("search", ProviderCall(
            request.fingerprint(),
            query=(("SX", request.origin.lon), ("SY", request.origin.lat), ("EX", request.destination.lon), ("EY", request.destination.lat), ("OPT", 0), ("SearchType", 0)),
            observed_hint=request.departure_time,
        ), deadline=deadline)


def _integer(value: Any, name: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SchemaValidationError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value: Any, name: str, *, minimum: float | None) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or (minimum is not None and value < minimum)
    ):
        suffix = " finite" if minimum is None else f" >= {minimum}"
        raise SchemaValidationError(f"{name} must be numeric{suffix}")
    return float(value)


def _exact_items(items: list[Any], keys: set[str], path: str) -> list[Mapping[str, Any]]:
    return [_require_exact(item, keys, path) for item in items]


def _require_allowed(
    value: Any,
    required: set[str],
    optional: set[str],
    path: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{path} must be an object")
    if set(value) - required - optional or required - set(value):
        raise SchemaValidationError(f"{path} schema mismatch")
    return value


class ProviderAdapterSuite:
    """Provider collection with separate disabled and production assembly paths.

    The public constructor is the fixture/default fail-closed path. Legacy shared
    capability/credential arguments are quarantined and never forwarded. Production
    callers must use :meth:`from_config` with exact operation-scoped bindings.
    """

    def __init__(
        self,
        transport: BoundedHttpTransport,
        *,
        capabilities: CapabilityRegistry | None = None,
        credential: SensitiveValue | None = None,
        telemetry: TelemetrySink | None = None,
        clock: Callable[[], datetime] | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        # Backward-compatible quarantine for an earlier security regression test and
        # already-deployed call sites. These values are deliberately *not* forwarded:
        # a shared credential/capability surface can never assemble a live suite.
        # Production assembly is exclusively the exact-scoped from_config path.
        self.shared_configuration_quarantined = (
            capabilities is not None or credential is not None
        )
        self._configure(
            transport=transport,
            telemetry=telemetry,
            clock=clock,
            retry_policy=retry_policy,
        )

    @classmethod
    def from_config(cls, config: ProviderAdapterSuiteConfig) -> "ProviderAdapterSuite":
        if not isinstance(config, ProviderAdapterSuiteConfig):
            raise TypeError("config must be ProviderAdapterSuiteConfig")
        suite = cls.__new__(cls)
        suite.shared_configuration_quarantined = False
        suite._configure(
            operation_bindings=config.binding_map,
            capabilities=config.capabilities,
            runtime_evidence=config.runtime_evidence,
            telemetry=config.telemetry,
            clock=config.clock,
            retry_policy=config.retry_policy,
        )
        return suite

    def _configure(
        self,
        *,
        transport: BoundedHttpTransport | None = None,
        operation_bindings: Mapping[
            tuple[str, str], ProviderOperationBinding
        ] | None = None,
        capabilities: CapabilityRegistry | None = None,
        runtime_evidence: ProviderRuntimeEvidenceConfig | None = None,
        telemetry: TelemetrySink | None = None,
        clock: Callable[[], datetime] | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        kwargs = {
            "capabilities": capabilities,
            "runtime_evidence": runtime_evidence,
            "telemetry": telemetry,
            "clock": clock,
            "retry_policy": retry_policy,
            "operation_bindings": operation_bindings,
        }
        self.kakao_transit = KakaoTransitAdapter(transport, **kwargs)
        self.kakao_walk = KakaoWalkAdapter(transport, **kwargs)
        self.kakao_mobility = KakaoMobilityDirectionsAdapter(transport, **kwargs)
        self.gbis = GbisAdapter(transport, **kwargs)
        self.kma = KmaContextAdapter(transport, **kwargs)
        self.gits = GitsTrafficAdapter(transport, **kwargs)
        self.tmap = TmapTransitAdapter(transport, **kwargs)
        self.odsay = OdsayTransitAdapter(transport, **kwargs)
