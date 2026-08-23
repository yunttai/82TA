"""One-shot, deployment-owned production dependency registration.

This module intentionally does not infer Provider credentials, database handles,
model artifacts or capability evidence from environment variables.  A deployment
factory owns that assembly and returns the exact API boundary DTO.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
import os

from routing_api.container import register_production_dependencies
from routing_api.production_composition import ProductionCompositionDependencies


PRODUCTION_DEPENDENCIES_FACTORY_ENV = "ROUTING_PRODUCTION_DEPENDENCIES_FACTORY"


class ProductionBootstrapError(RuntimeError):
    """Sanitized startup failure with no factory exception or secret material."""


def bootstrap_production_dependencies(
    factory: Callable[[], ProductionCompositionDependencies],
) -> ProductionCompositionDependencies:
    """Construct and register one exact dependency object before app startup."""

    if not callable(factory):
        raise ProductionBootstrapError("production dependency factory is not callable")
    try:
        dependencies = factory()
    except Exception:
        # Do not chain a deployment factory exception: its message or repr may
        # contain a credential, DSN, artifact URI or Provider raw response.
        raise ProductionBootstrapError("production dependency factory failed") from None
    if type(dependencies) is not ProductionCompositionDependencies:
        raise ProductionBootstrapError(
            "production dependency factory returned an invalid boundary object"
        )
    register_production_dependencies(dependencies)
    return dependencies


def _load_factory(value: str) -> Callable[[], ProductionCompositionDependencies]:
    module_name, separator, attribute_name = value.partition(":")
    if (
        separator != ":"
        or not module_name
        or not attribute_name
        or ":" in attribute_name
        or any(not part.isidentifier() for part in module_name.split("."))
        or not attribute_name.isidentifier()
    ):
        raise ProductionBootstrapError(
            "production dependency factory must use dotted.module:callable"
        )
    try:
        module = import_module(module_name)
        factory = getattr(module, attribute_name)
    except Exception:
        raise ProductionBootstrapError(
            "production dependency factory could not be loaded"
        ) from None
    if not callable(factory):
        raise ProductionBootstrapError("production dependency factory is not callable")
    return factory


def bootstrap_from_environment(
    environment: Mapping[str, str] | None = None,
) -> ProductionCompositionDependencies | None:
    """Register configured dependencies, or preserve the fail-closed default.

    Absence is not an implicit development/fixture promotion.  Django will build
    its ordinary unavailable/all-false application.  A present but invalid value
    fails startup instead of silently falling back.
    """

    values = os.environ if environment is None else environment
    factory_path = values.get(PRODUCTION_DEPENDENCIES_FACTORY_ENV, "").strip()
    if not factory_path:
        return None
    return bootstrap_production_dependencies(_load_factory(factory_path))
