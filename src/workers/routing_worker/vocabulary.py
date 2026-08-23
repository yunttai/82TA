"""Exact worker-to-private-API persistence vocabulary and drift inventory.

Training code may use ``ETA`` as a local family label. Routing persistence and the
private admin API never do: the database purpose is ``BUS_ETA``. Likewise, uppercase
runtime environments are process configuration only; persisted deployment identity
uses the lowercase private-API enum.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


TRAINING_FAMILY_TO_PURPOSE = MappingProxyType(
    {"ETA": "BUS_ETA", "SEAT_RISK": "SEAT_RISK"}
)
CANONICAL_MODEL_PURPOSES = frozenset(
    {"BUS_ETA", "SEAT_RISK", "CALIBRATION", "TAXI_DISPATCH_WAIT"}
)
WORKER_MODEL_PURPOSES = frozenset(TRAINING_FAMILY_TO_PURPOSE.values())
PROCESS_RUNTIME_ENVIRONMENTS = frozenset(
    {"DEVELOPMENT", "STAGING", "PRODUCTION"}
)
RUNTIME_TO_DEPLOYMENT_ENVIRONMENT = MappingProxyType(
    {"DEVELOPMENT": "dev", "STAGING": "staging", "PRODUCTION": "prod"}
)
CANONICAL_DEPLOYMENT_ENVIRONMENTS = frozenset(
    RUNTIME_TO_DEPLOYMENT_ENVIRONMENT.values()
)

_LEGACY_PURPOSE_ALIASES = MappingProxyType({"ETA": "BUS_ETA"})
_LEGACY_ENVIRONMENT_ALIASES = RUNTIME_TO_DEPLOYMENT_ENVIRONMENT


class VocabularyError(ValueError):
    pass


def persisted_model_purpose(training_family: str) -> str:
    """Map an exact local training label to its canonical persisted purpose."""

    if not isinstance(training_family, str):
        raise VocabularyError("unsupported training model family")
    try:
        return TRAINING_FAMILY_TO_PURPOSE[training_family]
    except KeyError as exc:
        raise VocabularyError("unsupported training model family") from exc


def persisted_environment(runtime_environment: str) -> str:
    """Map exact process configuration to private-API deployment identity."""

    if not isinstance(runtime_environment, str):
        raise VocabularyError("unsupported process runtime environment")
    try:
        return RUNTIME_TO_DEPLOYMENT_ENVIRONMENT[runtime_environment]
    except KeyError as exc:
        raise VocabularyError("unsupported process runtime environment") from exc


def require_worker_model_purpose(value: str) -> str:
    if not isinstance(value, str) or value not in WORKER_MODEL_PURPOSES:
        raise VocabularyError("worker model purpose must be BUS_ETA or SEAT_RISK")
    return value


def require_deployment_environment(value: str) -> str:
    if not isinstance(value, str) or value not in CANONICAL_DEPLOYMENT_ENVIRONMENTS:
        raise VocabularyError("deployment environment must be dev, staging, or prod")
    return value


@dataclass(frozen=True, slots=True)
class VocabularyMigrationPlan:
    purpose_updates: tuple[tuple[str, str, int], ...]
    environment_updates: tuple[tuple[str, str, int], ...]
    blockers: tuple[str, ...]

    @property
    def executable(self) -> bool:
        return not self.blockers


def _validated_counts(values: Mapping[str, int], label: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, count in values.items():
        if (
            not isinstance(key, str)
            or not key
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise VocabularyError(f"{label} inventory is invalid")
        if count:
            result[key] = count
    return result


def plan_vocabulary_migration(
    *, purpose_counts: Mapping[str, int], environment_counts: Mapping[str, int]
) -> VocabularyMigrationPlan:
    """Create a non-mutating legacy-row plan with explicit collision blockers.

    This function never aliases reads and never updates a database. Operators must
    first inventory rows, resolve collisions, back up the Routing DB, and apply a
    separately reviewed migration before canonical-only worker/admin reads resume.
    """

    purposes = _validated_counts(purpose_counts, "purpose")
    environments = _validated_counts(environment_counts, "environment")
    purpose_updates: list[tuple[str, str, int]] = []
    environment_updates: list[tuple[str, str, int]] = []
    blockers: list[str] = []

    for legacy, canonical in _LEGACY_PURPOSE_ALIASES.items():
        count = purposes.get(legacy, 0)
        if not count:
            continue
        if purposes.get(canonical, 0):
            blockers.append(f"purpose collision: {legacy}->{canonical}")
        else:
            purpose_updates.append((legacy, canonical, count))
    for value in sorted(set(purposes) - CANONICAL_MODEL_PURPOSES - set(_LEGACY_PURPOSE_ALIASES)):
        blockers.append(f"unknown persisted purpose: {value}")

    for legacy, canonical in _LEGACY_ENVIRONMENT_ALIASES.items():
        count = environments.get(legacy, 0)
        if not count:
            continue
        if environments.get(canonical, 0):
            blockers.append(f"environment collision: {legacy}->{canonical}")
        else:
            environment_updates.append((legacy, canonical, count))
    for value in sorted(
        set(environments)
        - CANONICAL_DEPLOYMENT_ENVIRONMENTS
        - set(_LEGACY_ENVIRONMENT_ALIASES)
    ):
        blockers.append(f"unknown persisted environment: {value}")

    return VocabularyMigrationPlan(
        purpose_updates=tuple(purpose_updates),
        environment_updates=tuple(environment_updates),
        blockers=tuple(blockers),
    )
