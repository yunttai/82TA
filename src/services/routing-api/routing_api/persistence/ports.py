from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .records import (
    CheckpointRecord,
    DeploymentRecord,
    MappingRecord,
    ModelArtifactRecord,
    OptimizationRunRecord,
    OptimizationResultRecord,
    ProviderOperationRecord,
)


class ProviderStateRepository(Protocol):
    def save(self, record: ProviderOperationRecord) -> None: ...


class CheckpointRepository(Protocol):
    def save(self, record: CheckpointRecord) -> None: ...


class MappingRepository(Protocol):
    def save(self, record: MappingRecord) -> str: ...


class OptimizationRunRepository(Protocol):
    def save(self, record: OptimizationRunRecord) -> str: ...


class OptimizationResultRepository(Protocol):
    def persist(self, record: OptimizationResultRecord) -> None: ...


class ModelRegistryRepository(Protocol):
    def get_artifact(self, purpose: str, version: str) -> ModelArtifactRecord | None: ...

    def get_deployment(
        self, purpose: str, version: str, environment: str
    ) -> DeploymentRecord | None: ...

    def transition(
        self,
        *,
        purpose: str,
        version: str,
        environment: str,
        expected_status: str,
        target_status: str,
        traffic_fraction: float,
        occurred_at: datetime,
    ) -> DeploymentRecord: ...

    def rollback(
        self,
        *,
        purpose: str,
        target_version: str,
        environment: str,
        occurred_at: datetime,
    ) -> DeploymentRecord: ...
