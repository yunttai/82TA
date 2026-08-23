"""Fail-closed composition root for externally supplied worker infrastructure.

This module deliberately does not construct a PostgreSQL driver, Provider client,
distributed lease, idempotency store, or scheduler.  Deployments must inject those
reviewed dependencies.  Merely importing or constructing the default runner cannot
open a connection, call a Provider, register a schedule, or mutate state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from .cli import (
    COMMANDS,
    PROVIDER_COMMANDS,
    CommandError,
    CommandExecutor,
    RuntimeConfig,
    parse_payload,
    validate_command_payload,
)
from .repositories import PostgresWorkerRepository


_COLLECTOR_COMMANDS = frozenset({"collector-run"})
_LEGACY_COMMANDS = frozenset({"legacy-inventory", "legacy-import-plan"})
_QUALITY_COMMANDS = frozenset({"quality-gate", "dataset-build"})
_MODEL_COMMANDS = frozenset(COMMANDS) - _COLLECTOR_COMMANDS - _LEGACY_COMMANDS - _QUALITY_COMMANDS
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_RESERVATION_DISPOSITIONS = frozenset({"STARTED", "COMPLETED", "IN_PROGRESS"})


class Clock(Protocol):
    def now(self) -> datetime: ...


class UtcClock:
    """Small production-safe clock whose use is still explicit at composition."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class LeaseGrant:
    run_key: str
    owner_id: str
    token: str = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.owner_id) or not self.run_key.startswith("routing-worker:"):
            raise CommandError("worker lease identity is invalid")
        if not self.token:
            raise CommandError("worker lease token is absent")
        _aware(self.expires_at, "lease expiry")


class LeasePort(Protocol):
    """Distributed lease; acquire/release must use compare-and-delete semantics."""

    def acquire(
        self, *, run_key: str, owner_id: str, ttl_seconds: int, acquired_at: datetime,
    ) -> LeaseGrant | None: ...

    def release(self, grant: LeaseGrant, *, released_at: datetime) -> None: ...


@dataclass(frozen=True, slots=True)
class RunReservation:
    disposition: str
    result: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.disposition not in _RESERVATION_DISPOSITIONS:
            raise CommandError("worker idempotency disposition is invalid")
        if (self.disposition == "COMPLETED") != (self.result is not None):
            raise CommandError("completed worker reservation must contain a result")


class IdempotencyPort(Protocol):
    """Durable run ledger with atomic reserve and exact fingerprint comparison."""

    def reserve(
        self, *, run_key: str, fingerprint: str, reserved_at: datetime,
    ) -> RunReservation: ...

    def complete(
        self, *, run_key: str, fingerprint: str, result: Mapping[str, Any],
        completed_at: datetime,
    ) -> None: ...

    def abandon(
        self, *, run_key: str, fingerprint: str, abandoned_at: datetime,
    ) -> None: ...


class NormalizedProviderPort(Protocol):
    """Marker boundary for schema-validated canonical collector observations.

    Job implementations may define narrower methods.  Raw response shapes,
    credentials, vehicle plates, and Service identity must never cross this port.
    """

    @property
    def capability_enabled(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class JobContext:
    repository: PostgresWorkerRepository
    clock: Clock
    provider: NormalizedProviderPort | None
    started_at: datetime
    run_key: str
    runtime_environment: str
    deployment_environment: str

    def __post_init__(self) -> None:
        _aware(self.started_at, "job start")
        if not self.run_key.startswith("routing-worker:"):
            raise CommandError("worker run key is invalid")


class JobPort(Protocol):
    def run(
        self, command: str, payload: Mapping[str, Any], context: JobContext,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ProductionJobs:
    """Four explicit job boundaries; no handler can be silently omitted."""

    collector: JobPort
    quality: JobPort
    legacy: JobPort
    model_registry: JobPort

    def resolve(self, command: str) -> JobPort:
        if command in _COLLECTOR_COMMANDS:
            return self.collector
        if command in _QUALITY_COMMANDS:
            return self.quality
        if command in _LEGACY_COMMANDS:
            return self.legacy
        if command in _MODEL_COMMANDS:
            return self.model_registry
        raise CommandError("worker command is outside the closed production job set")


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    schedule_id: str
    command: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.schedule_id):
            raise CommandError("worker schedule id is invalid")
        if self.command not in COMMANDS:
            raise CommandError("worker schedule command is invalid")


@dataclass(frozen=True, slots=True)
class ScheduledInvocation:
    schedule_id: str
    command: str
    invoke: Callable[[], Mapping[str, Any]] = field(repr=False, compare=False)


class SchedulerPort(Protocol):
    def activate(self, invocations: tuple[ScheduledInvocation, ...]) -> None:
        """Atomically register all invocations without running them immediately."""
        ...


@dataclass(frozen=True, slots=True)
class RunnerPolicy:
    enabled: bool = False
    provider_enabled: bool = False
    scheduler_enabled: bool = False
    owner_id: str = "DISABLED"
    lease_ttl_seconds: int = 300

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.owner_id):
            raise CommandError("worker owner id is invalid")
        if not 1 <= self.lease_ttl_seconds <= 86_400:
            raise CommandError("worker lease TTL must be between 1 and 86400 seconds")


class ProductionRunner(CommandExecutor):
    """Compose one-shot and scheduled jobs from explicit durable dependencies."""

    def __init__(
        self,
        *,
        policy: RunnerPolicy = RunnerPolicy(),
        repository: PostgresWorkerRepository | None = None,
        provider: NormalizedProviderPort | None = None,
        clock: Clock | None = None,
        lease: LeasePort | None = None,
        idempotency: IdempotencyPort | None = None,
        scheduler: SchedulerPort | None = None,
        jobs: ProductionJobs | None = None,
    ) -> None:
        self._policy = policy
        self._repository = repository
        self._provider = provider
        self._clock = clock
        self._lease = lease
        self._idempotency = idempotency
        self._scheduler = scheduler
        self._jobs = jobs
        if policy.enabled:
            self._require_core_dependencies()

    def safe_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "clockComposed": self._clock is not None,
                "databaseComposed": self._repository is not None,
                "enabled": self._policy.enabled,
                "idempotencyComposed": self._idempotency is not None,
                "jobsComposed": self._jobs is not None,
                "leaseComposed": self._lease is not None,
                "providerComposed": self._provider is not None,
                "providerEnabled": self._policy.provider_enabled,
                "schedulerComposed": self._scheduler is not None,
                "schedulerEnabled": self._policy.scheduler_enabled,
            }
        )

    def execute(
        self, command: str, payload: Mapping[str, Any], config: RuntimeConfig,
    ) -> Mapping[str, Any]:
        if command not in COMMANDS:
            raise CommandError("worker command is unknown")
        if not self._policy.enabled:
            raise CommandError("production worker runner is disabled")
        self._require_core_dependencies()
        config.require(command)
        safe_payload = _safe_object(payload, "worker command payload")
        validate_command_payload(command, safe_payload, dry_run=False)
        requested_environment = safe_payload.get("environment")
        if requested_environment is not None and requested_environment != config.deployment_environment:
            raise CommandError("persisted environment does not match process runtime environment")
        if command in PROVIDER_COMMANDS:
            if not self._policy.provider_enabled or self._provider is None:
                raise CommandError("normalized Provider dependency is disabled or absent")
            if self._provider.capability_enabled is not True:
                raise CommandError("normalized Provider capability is not explicitly enabled")

        assert self._clock is not None
        assert self._idempotency is not None
        assert self._lease is not None
        assert self._jobs is not None
        started_at = self._clock.now()
        _aware(started_at, "runner clock")
        fingerprint = _fingerprint(command, safe_payload, config.deployment_environment)
        run_key = f"routing-worker:{command}:{fingerprint}"
        reservation = self._idempotency.reserve(
            run_key=run_key, fingerprint=fingerprint, reserved_at=started_at,
        )
        if reservation.disposition == "COMPLETED":
            assert reservation.result is not None
            return _safe_object(reservation.result, "cached worker result")
        if reservation.disposition == "IN_PROGRESS":
            raise CommandError("worker command is already in progress")

        grant = self._lease.acquire(
            run_key=run_key,
            owner_id=self._policy.owner_id,
            ttl_seconds=self._policy.lease_ttl_seconds,
            acquired_at=started_at,
        )
        if grant is None:
            self._idempotency.abandon(
                run_key=run_key, fingerprint=fingerprint,
                abandoned_at=self._checked_now(),
            )
            raise CommandError("worker command lease is unavailable")
        if grant.run_key != run_key or grant.owner_id != self._policy.owner_id:
            try:
                self._idempotency.abandon(
                    run_key=run_key, fingerprint=fingerprint,
                    abandoned_at=self._checked_now(),
                )
            finally:
                self._lease.release(grant, released_at=self._checked_now())
            raise CommandError("worker lease grant does not match the request")

        try:
            try:
                context = JobContext(
                    repository=self._repository,  # type: ignore[arg-type]
                    clock=self._clock,
                    provider=self._provider if command in PROVIDER_COMMANDS else None,
                    started_at=started_at,
                    run_key=run_key,
                    runtime_environment=config.environment,
                    deployment_environment=config.deployment_environment,
                )
                result = self._jobs.resolve(command).run(command, safe_payload, context)
                safe_result = _safe_object(result, "worker command result")
            except Exception:
                try:
                    self._idempotency.abandon(
                        run_key=run_key,
                        fingerprint=fingerprint,
                        abandoned_at=self._checked_now(),
                    )
                    if command == "collector-run":
                        self._repository.write_dead_letter(  # type: ignore[union-attr]
                            dedupe_key=fingerprint,
                            reason="COLLECTOR_JOB_FAILED",
                            occurred_at=self._checked_now(),
                            safe_summary={
                                "command": command,
                                "environment": config.deployment_environment,
                                "runFingerprint": fingerprint,
                            },
                        )
                except Exception:
                    raise CommandError(
                        "worker job and sanitized failure recording failed"
                    ) from None
                raise CommandError("worker job failed") from None
            self._idempotency.complete(
                run_key=run_key,
                fingerprint=fingerprint,
                result=safe_result,
                completed_at=self._checked_now(),
            )
            return safe_result
        finally:
            self._lease.release(grant, released_at=self._checked_now())

    def activate_schedules(
        self,
        schedules: tuple[ScheduledJob, ...],
        config: RuntimeConfig,
        *,
        activation_approved: bool = False,
    ) -> None:
        """Atomically register schedules only after a separate explicit approval."""

        if not self._policy.enabled or not self._policy.scheduler_enabled:
            raise CommandError("worker scheduler is disabled")
        if not activation_approved:
            raise CommandError("worker scheduler activation is not explicitly approved")
        self._require_core_dependencies()
        if self._scheduler is None:
            raise CommandError("worker scheduler dependency is absent")
        if not schedules or len({item.schedule_id for item in schedules}) != len(schedules):
            raise CommandError("worker schedules must be non-empty with unique ids")

        prepared: list[tuple[ScheduledJob, Mapping[str, Any]]] = []
        for item in schedules:
            config.require(item.command)
            payload = _safe_object(item.payload, "scheduled worker payload")
            validate_command_payload(item.command, payload, dry_run=False)
            requested_environment = payload.get("environment")
            if requested_environment is not None and requested_environment != config.deployment_environment:
                raise CommandError("scheduled persisted environment does not match runtime")
            if item.command in PROVIDER_COMMANDS and (
                not self._policy.provider_enabled
                or self._provider is None
                or self._provider.capability_enabled is not True
            ):
                raise CommandError("scheduled Provider dependency is disabled or absent")
            prepared.append((item, payload))

        invocations = tuple(
            ScheduledInvocation(
                item.schedule_id,
                item.command,
                lambda command=item.command, payload=payload: self.execute(command, payload, config),
            )
            for item, payload in prepared
        )
        try:
            self._scheduler.activate(invocations)
        except Exception:
            raise CommandError("worker scheduler activation failed") from None

    def _checked_now(self) -> datetime:
        assert self._clock is not None
        value = self._clock.now()
        _aware(value, "runner clock")
        return value

    def _require_core_dependencies(self) -> None:
        missing = tuple(
            name
            for name, value in (
                ("clock", self._clock),
                ("database", self._repository),
                ("idempotency", self._idempotency),
                ("jobs", self._jobs),
                ("lease", self._lease),
            )
            if value is None
        )
        if missing:
            raise CommandError(f"production worker dependencies are absent: {','.join(missing)}")


def _aware(value: datetime, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CommandError(f"{label} must be timezone-aware")


def _safe_object(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CommandError(f"{label} must be an object")
    try:
        encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CommandError(f"{label} must be deterministic JSON") from exc
    return dict(parse_payload(encoded))


def _fingerprint(command: str, payload: Mapping[str, Any], environment: str) -> str:
    encoded = json.dumps(
        {"command": command, "environment": environment, "payload": dict(payload)},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "Clock",
    "IdempotencyPort",
    "JobContext",
    "JobPort",
    "LeaseGrant",
    "LeasePort",
    "NormalizedProviderPort",
    "ProductionJobs",
    "ProductionRunner",
    "RunReservation",
    "RunnerPolicy",
    "ScheduledInvocation",
    "ScheduledJob",
    "SchedulerPort",
    "UtcClock",
]
