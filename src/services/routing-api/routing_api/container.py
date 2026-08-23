from __future__ import annotations

from functools import lru_cache
import os
import sys
import threading
from typing import TYPE_CHECKING

from django.conf import settings

from routing_api.application import (
    InMemoryIdempotencyStore,
    RoutingApiApplication,
    SystemClock,
    UnavailableOptimizeRouteUseCase,
)
from routing_api.auth import Hs256ServiceBearerVerifier
from routing_api.capabilities import (
    capability_projection_from_registry,
    foundation_capability_projection,
)
from routing_api.contract import CanonicalContractValidator

if TYPE_CHECKING:
    from routing_api.production_composition import ProductionCompositionDependencies


_APPLICATION_COMPOSITION_LOCK = threading.RLock()
_registered_production_dependencies: object | None = None
_cached_application: RoutingApiApplication | None = None
_application_build_started = False
_application_build_error: BaseException | None = None


@lru_cache(maxsize=1)
def get_admin_control_plane():
    """Production default is intentionally closed.

    RI-260 does not silently substitute the RI-250 in-memory audit adapter for
    a durable operator audit or construct a registry without approved artifact
    storage. Deployments must inject an ``AdminControlPlane`` explicitly.
    """

    return None


def get_application() -> RoutingApiApplication:
    """Return the process application, freezing composition before its first build.

    Registration and construction share one lock.  This intentionally avoids the
    duplicate concurrent-miss construction permitted by ``functools.lru_cache`` and
    makes a registration racing with startup resolve in exactly one of two ways:
    either it wins before the freeze and is consumed, or it loses and fails closed.
    """

    global _application_build_error
    global _application_build_started
    global _cached_application

    with _APPLICATION_COMPOSITION_LOCK:
        if _cached_application is not None:
            return _cached_application
        if _application_build_error is not None:
            raise RuntimeError("Routing application construction previously failed") from (
                _application_build_error
            )
        if _application_build_started:
            # A different thread cannot observe this state because it waits on the
            # process lock. Reaching it therefore means same-thread reentrant
            # startup through an import hook or dependency constructor. Never
            # recurse into a second application build.
            raise RuntimeError("Routing application construction is already in progress")
        _application_build_started = True
        try:
            application = build_application(
                production_dependencies=_registered_production_dependencies
            )
        except BaseException as exc:
            # Startup stays frozen after construction begins.  A deployment may
            # restart the process, but it cannot repair or replace composition in
            # the running process after a partial build.
            _application_build_error = exc
            raise
        _cached_application = application
        return application


def register_production_dependencies(
    dependencies: ProductionCompositionDependencies,
) -> None:
    """Register exact deployment dependencies once, before application startup.

    The same object may be registered repeatedly before the first build as an
    idempotent bootstrap convenience.  A distinct object, a subclass/duck type, or
    any registration after construction starts is rejected.  Nothing is inferred
    from environment variables, and this function does not import worker code.
    """

    from routing_api.production_composition import ProductionCompositionDependencies

    if type(dependencies) is not ProductionCompositionDependencies:
        raise TypeError(
            "production dependencies must be an exact ProductionCompositionDependencies"
        )

    global _registered_production_dependencies
    with _APPLICATION_COMPOSITION_LOCK:
        if _application_build_started:
            raise RuntimeError(
                "production dependencies must be registered before application startup"
            )
        if _registered_production_dependencies is None:
            _registered_production_dependencies = dependencies
            return
        if _registered_production_dependencies is dependencies:
            return
        raise RuntimeError("production dependencies are already registered")


def _reset_application_composition_for_tests() -> None:
    """Atomically clear cached process state in a pytest process only.

    This private helper clears both the registered object and the cached/build
    state, so tests cannot leak production-shaped dependencies into later cases.
    It is deliberately unavailable to a running deployment and is not a hot-swap
    mechanism.
    """

    if "PYTEST_CURRENT_TEST" not in os.environ or "pytest" not in sys.modules:
        raise RuntimeError("application composition reset is test-only")

    global _application_build_error
    global _application_build_started
    global _cached_application
    global _registered_production_dependencies
    with _APPLICATION_COMPOSITION_LOCK:
        _registered_production_dependencies = None
        _cached_application = None
        _application_build_started = False
        _application_build_error = None


# Backward-compatible pytest-only surface for existing load/security tests that
# previously cleared functools.lru_cache.  The guard above prevents production
# hot swap, while new tests should import the explicitly named private helper.
setattr(get_application, "cache_clear", _reset_application_composition_for_tests)


def build_application(*, production_dependencies=None, clock=None) -> RoutingApiApplication:
    """Explicit Django composition seam; the cached default stays fail-closed.

    Deployment wrappers may pass a fully typed production dependency object.
    This module never derives Provider credentials or capability approval from
    environment variables.
    """

    if production_dependencies is not None:
        from routing_api.production_composition import ProductionCompositionDependencies

        if type(production_dependencies) is not ProductionCompositionDependencies:
            raise TypeError(
                "production dependencies must be an exact ProductionCompositionDependencies"
            )

    clock = clock or SystemClock()
    verifier = Hs256ServiceBearerVerifier(
        secret=settings.ROUTING_SERVICE_JWT_SECRET.encode("utf-8"),
        issuer=settings.ROUTING_SERVICE_JWT_ISSUER,
        audience=settings.ROUTING_SERVICE_JWT_AUDIENCE,
    )
    # Internal provider/domain/model wheels are deployment dependencies for an
    # enabled production composition.  The fail-closed default remains
    # importable for Django checks even when those wheels are absent.
    production_registry = None
    production_operations = frozenset()
    production_models = ()
    try:
        if production_dependencies is None:
            from routing_api.production_composition import (
                build_default_production_use_case,
            )

            use_case = build_default_production_use_case(clock)
        else:
            from routing_api.production_composition import (
                build_injected_production_use_case,
            )

            use_case = build_injected_production_use_case(
                clock, production_dependencies
            )
            production_registry = getattr(use_case, "capability_registry", None)
            production_operations = getattr(
                use_case, "executable_operations", frozenset()
            )
            production_models = getattr(use_case, "model_projection", ())
    except ModuleNotFoundError as exc:
        if exc.name not in {
            "bus_intelligence_core",
            "provider_core",
            "routing_domain",
        }:
            raise
        use_case = UnavailableOptimizeRouteUseCase()
    backend_state = (
        "production"
        if production_registry is not None and production_operations
        else "unavailable"
    )
    fixture_requested = bool(settings.ROUTING_FIXTURE_SCENARIO)
    fixture_allowed = (
        settings.ROUTING_ALLOW_FIXTURE_BACKEND
        and settings.ROUTING_RUNTIME_ENVIRONMENT in {"TEST", "DEVELOPMENT"}
    )
    if fixture_requested and fixture_allowed:
        from routing_api.fixture_integration import IntegratedFixtureOptimizeRouteUseCase
        from routing_api.fixture_scenarios import fixture_scenario

        use_case = IntegratedFixtureOptimizeRouteUseCase(
            fixture_scenario(settings.ROUTING_FIXTURE_SCENARIO),
            clock,
        )
        production_registry = None
        production_operations = frozenset()
        production_models = ()
        backend_state = f"fixture-only:{settings.ROUTING_FIXTURE_SCENARIO}"
    elif fixture_requested:
        # A stale scenario variable in staging/production must never activate
        # sanitized replay as a routing backend.
        backend_state = "fixture-blocked"
    try:
        capability_projection = (
            capability_projection_from_registry(
                production_registry,
                executable_operations=production_operations,
                models=production_models,
            )
            if production_registry is not None
            else foundation_capability_projection()
        )
    except ModuleNotFoundError as exc:
        if exc.name != "provider_core":
            raise
        # Missing internal deployment wheels must not cause an implicit source
        # checkout import. The application default is conservative/all-false.
        capability_projection = None
    try:
        from routing_domain import RankingPolicy

        ranking_policy_version = RankingPolicy().version
    except ModuleNotFoundError as exc:
        if exc.name != "routing_domain":
            raise
        ranking_policy_version = "unavailable"
    return RoutingApiApplication(
        verifier=verifier,
        contract=CanonicalContractValidator(),
        use_case=use_case,
        clock=clock,
        idempotency=InMemoryIdempotencyStore(),
        build_version=settings.ROUTING_BUILD_VERSION,
        capability_projection=capability_projection,
        backend_state=backend_state,
        ranking_policy_version=ranking_policy_version,
    )
