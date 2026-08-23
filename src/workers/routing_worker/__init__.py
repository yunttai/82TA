"""Fail-closed durable worker adapters for Routing & Intelligence."""

from importlib import import_module

from .repositories import PostgresWorkerRepository


_LAZY_EXPORTS = {
    "ActiveModelDeployment": ".model_deployment",
    "ActiveModelPair": ".model_deployment",
    "ApprovedBundleMaterialization": ".model_deployment",
    "FixedArtifactBundleResolver": ".model_deployment",
    "ModelDeploymentAssemblyError": ".model_deployment",
    "PostgresActiveModelPairSource": ".model_deployment",
    "VerifiedModelPairAssembler": ".model_deployment",
    "VerifiedModelPredictorPair": ".model_deployment",
    "ETA_POINT_IN_TIME_SQL": ".postgres_serving",
    "SEAT_RISK_POINT_IN_TIME_SQL": ".postgres_serving",
    "PostgresEtaServingFeatureSource": ".postgres_serving",
    "PostgresSeatRiskServingFeatureSource": ".postgres_serving",
    "ServingSnapshotTimeouts": ".postgres_serving",
}


def __getattr__(name: str) -> object:
    try:
        module_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


__all__ = ["PostgresWorkerRepository", *sorted(_LAZY_EXPORTS)]
