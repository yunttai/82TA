"""Fail-closed worker command dispatcher.

The installed command is deliberately unscheduled and has no built-in connector.
Production composition must inject a reviewed executor and connection factory. Dry
runs are deterministic, redact configuration, and perform no filesystem/network/DB
access beyond parsing the caller-supplied inline JSON.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import PurePosixPath
import re
import sys
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from .repositories import CANONICAL_MODEL_STATES, MODEL_TRANSITIONS
from .vocabulary import (
    CANONICAL_DEPLOYMENT_ENVIRONMENTS,
    PROCESS_RUNTIME_ENVIRONMENTS,
    TRAINING_FAMILY_TO_PURPOSE,
    VocabularyError,
    persisted_environment,
)


COMMANDS = (
    "collector-run",
    "legacy-inventory",
    "legacy-import-plan",
    "quality-gate",
    "dataset-build",
    "evaluate-eta",
    "evaluate-seat",
    "model-register",
    "model-vocabulary-inventory",
    "model-transition",
    "drift-audit",
    "model-rollback",
)
MUTATING_COMMANDS = frozenset(
    {
        "collector-run",
        "quality-gate",
        "dataset-build",
        "evaluate-eta",
        "evaluate-seat",
        "model-register",
        "model-transition",
        "drift-audit",
        "model-rollback",
    }
)
PROVIDER_COMMANDS = frozenset({"collector-run"})
FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "email", "name", "phone", "userId", "user_id", "socialId",
        "plate", "plateNumber", "raw", "rawPayload", "apiKey", "secret",
        "password", "dsn", "databaseUrl",
    }
)


class CommandError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    environment: str
    worker_enabled: bool
    db_approved: bool
    mutation_approved: bool
    provider_approved: bool
    db_dsn: str | None = field(repr=False)

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "RuntimeConfig":
        truth = lambda key: environ.get(key, "").lower() == "true"
        return cls(
            environment=environ.get("ROUTING_WORKER_ENVIRONMENT", ""),
            worker_enabled=truth("ROUTING_WORKER_ENABLED"),
            db_approved=truth("ROUTING_WORKER_DB_APPROVED"),
            mutation_approved=truth("ROUTING_WORKER_MUTATION_APPROVED"),
            provider_approved=truth("ROUTING_WORKER_PROVIDER_PRODUCTION_APPROVED"),
            db_dsn=environ.get("ROUTING_WORKER_DB_DSN") or None,
        )

    def require(self, command: str) -> None:
        if self.environment not in PROCESS_RUNTIME_ENVIRONMENTS:
            raise CommandError("ROUTING_WORKER_ENVIRONMENT is missing or invalid")
        if not self.worker_enabled:
            raise CommandError("worker execution is not explicitly enabled")
        if not self.db_approved or not self.db_dsn:
            raise CommandError("approved Routing DB configuration is unavailable")
        if command in MUTATING_COMMANDS and not self.mutation_approved:
            raise CommandError("worker mutation is not explicitly approved")
        if command in PROVIDER_COMMANDS and not self.provider_approved:
            raise CommandError("Provider production approval is absent")

    @property
    def deployment_environment(self) -> str:
        try:
            return persisted_environment(self.environment)
        except VocabularyError as exc:
            raise CommandError(str(exc)) from exc

    def safe_summary(self) -> Mapping[str, object]:
        return {
            "dbConfigured": self.db_dsn is not None,
            "dbApproved": self.db_approved,
            "environment": self.environment if self.environment in PROCESS_RUNTIME_ENVIRONMENTS else "UNSET",
            "mutationApproved": self.mutation_approved,
            "providerApproved": self.provider_approved,
            "workerEnabled": self.worker_enabled,
        }


class CommandExecutor(Protocol):
    def execute(
        self, command: str, payload: Mapping[str, Any], config: RuntimeConfig
    ) -> Mapping[str, Any]: ...


class InjectedCommandExecutor:
    """Closed dispatch table supplied by the reviewed worker composition root."""

    def __init__(
        self,
        handlers: Mapping[
            str, Callable[[Mapping[str, Any], RuntimeConfig], Mapping[str, Any]]
        ],
    ) -> None:
        unknown = set(handlers) - set(COMMANDS)
        if unknown:
            raise CommandError(f"unknown injected worker commands: {sorted(unknown)}")
        self._handlers = MappingProxyType(dict(handlers))

    def execute(
        self, command: str, payload: Mapping[str, Any], config: RuntimeConfig
    ) -> Mapping[str, Any]:
        handler = self._handlers.get(command)
        if handler is None:
            raise CommandError(f"worker command handler is not composed: {command}")
        result = handler(payload, config)
        if not isinstance(result, Mapping):
            raise CommandError("worker command result must be an object")
        _validate_safe(result)
        return result


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CommandError(f"duplicate input key: {key}")
        result[key] = value
    return result


def _validate_safe(value: object) -> None:
    if isinstance(value, dict):
        canonical = lambda item: re.sub(r"[^a-z0-9]", "", str(item).casefold())
        forbidden_values = {canonical(item) for item in FORBIDDEN_INPUT_KEYS}
        forbidden = forbidden_values & {canonical(item) for item in value}
        if forbidden:
            raise CommandError("input contains forbidden identity/secret/raw fields")
        for nested in value.values():
            _validate_safe(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_safe(nested)


def parse_payload(text: str) -> Mapping[str, Any]:
    if len(text.encode("utf-8")) > 1_048_576:
        raise CommandError("inline input exceeds one MiB")
    try:
        value = json.loads(text, object_pairs_hook=_object_no_duplicates)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CommandError("input must be valid JSON") from exc
    if not isinstance(value, dict):
        raise CommandError("input root must be an object")
    _validate_safe(value)
    return value


_REQUIRED_INPUTS = {
    "collector-run": {"sourceId", "partitionKey", "observations"},
    "legacy-inventory": {"sourcePath", "tableSpecs"},
    "legacy-import-plan": {"sourceSha256", "records"},
    "quality-gate": {"sourceId", "datasetVersion", "observations"},
    "dataset-build": {"family", "datasetVersion", "rows", "validationStart", "testStart"},
    "evaluate-eta": {"predictions"},
    "evaluate-seat": {"labels", "probabilities"},
    "model-register": {
        "family", "version", "artifactUri", "artifactSha256",
        "featureSchemaVersion", "trainingScope",
    },
    "model-vocabulary-inventory": set(),
    "model-transition": {"version", "expectedState", "targetState", "environment"},
    "drift-audit": {"featureName", "baseline", "current"},
    "model-rollback": {"failedVersion", "restoreVersion", "environment"},
}


def validate_command_payload(
    command: str, payload: Mapping[str, Any], *, dry_run: bool,
) -> None:
    if not dry_run:
        missing = _REQUIRED_INPUTS[command] - set(payload)
        if missing:
            raise CommandError(f"command input is missing required keys: {sorted(missing)}")
    family = payload.get("family")
    if command == "dataset-build" and family is not None:
        if not isinstance(family, str) or family not in {"ETA", "SEAT_RISK"}:
            raise CommandError("training family must be ETA or SEAT_RISK")
    if command == "model-register" and family is not None:
        if not isinstance(family, str) or family not in TRAINING_FAMILY_TO_PURPOSE:
            raise CommandError("worker training family must be ETA or SEAT_RISK")
    schema = payload.get("featureSchemaVersion")
    if schema is not None:
        if not isinstance(schema, str):
            raise CommandError("feature schema version must be a string")
        expected_prefix = (
            "eta-" if family == "ETA"
            else "seat-risk-" if family == "SEAT_RISK"
            else None
        )
        if expected_prefix is not None and not schema.startswith(expected_prefix):
            raise CommandError("feature schema does not match ETA/Seat family")
    scope = payload.get("trainingScope")
    if scope is not None:
        if not isinstance(scope, Mapping):
            raise CommandError("trainingScope must be an object")
        if scope.get("splitPolicy") != "TEMPORAL_TRIP_GROUP_PURGED":
            raise CommandError("training split must be temporal and trip-group purged")
        if scope.get("missingTargetPolicy") != "EXCLUDE_UNOBSERVED":
            raise CommandError("missing future target must remain unobserved")
    artifact_uri = payload.get("artifactUri")
    if artifact_uri is not None:
        if not isinstance(artifact_uri, str):
            raise CommandError("artifact URI must be a string")
        suffix = PurePosixPath(artifact_uri.split("?", 1)[0]).suffix.casefold()
        if suffix not in {".json", ".txt"}:
            raise CommandError("model artifact must use an allowlisted non-pickle format")
    expected_state = payload.get("expectedState")
    target_state = payload.get("targetState")
    for state in (expected_state, target_state):
        if state is not None and state not in CANONICAL_MODEL_STATES:
            raise CommandError("model state is outside the canonical registry")
    if expected_state is not None and target_state is not None:
        if target_state not in MODEL_TRANSITIONS[expected_state]:
            raise CommandError("model transition is outside the canonical lifecycle")
    environment = payload.get("environment")
    if (
        environment is not None
        and (
            not isinstance(environment, str)
            or environment not in CANONICAL_DEPLOYMENT_ENVIRONMENTS
        )
    ):
        raise CommandError("persisted environment must be dev, staging, or prod")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="routing-worker")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--input-json", default="{}")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _emit(value: Mapping[str, Any], stream: Any) -> None:
    stream.write(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
    stream.write("\n")


def run(
    argv: Sequence[str], *, environ: Mapping[str, str], executor: CommandExecutor | None,
    stdout: Any, stderr: Any,
) -> int:
    try:
        arguments = _parser().parse_args(tuple(argv))
        payload = parse_payload(arguments.input_json)
        validate_command_payload(arguments.command, payload, dry_run=arguments.dry_run)
        config = RuntimeConfig.from_environ(environ)
        if arguments.dry_run:
            _emit(
                {
                    "command": arguments.command,
                    "config": config.safe_summary(),
                    "dryRun": True,
                    "input": payload,
                    "networkCalls": 0,
                    "scheduled": False,
                    "wouldMutate": arguments.command in MUTATING_COMMANDS,
                },
                stdout,
            )
            return 0
        config.require(arguments.command)
        requested_environment = payload.get("environment")
        if (
            requested_environment is not None
            and requested_environment != config.deployment_environment
        ):
            raise CommandError(
                "persisted environment does not match process runtime environment"
            )
        if executor is None:
            raise CommandError("approved worker executor is not composed")
        result = executor.execute(arguments.command, payload, config)
        _emit({"command": arguments.command, "dryRun": False, "result": result}, stdout)
        return 0
    except CommandError as exc:
        _emit({"error": str(exc), "status": "FAIL_CLOSED"}, stderr)
        return 2
    except Exception:
        # Driver/handler exceptions can contain endpoints, SQL detail or payload data.
        _emit({"error": "worker execution failed", "status": "FAIL_CLOSED"}, stderr)
        return 3


def main(argv: Sequence[str] | None = None) -> int:
    return run(
        sys.argv[1:] if argv is None else argv,
        environ=os.environ,
        executor=None,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
