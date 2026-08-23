"""Process-lifetime production composition and startup-race regressions."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from unittest.mock import patch

import pytest
from django.test.utils import override_settings

from provider_core.named import ProviderAdapterSuite
from routing_api.application import RoutingUnavailableError
from routing_api.container import (
    _reset_application_composition_for_tests,
    build_application,
    get_application,
    register_production_dependencies,
)
from routing_api.production_composition import (
    ProductionCompositionDependencies,
    build_injected_production_use_case,
)


@pytest.fixture(autouse=True)
def _isolated_process_composition():
    _reset_application_composition_for_tests()
    yield
    _reset_application_composition_for_tests()


def test_registration_accepts_only_the_exact_dependency_type() -> None:
    class DerivedDependencies(ProductionCompositionDependencies):
        pass

    with pytest.raises(TypeError, match="exact ProductionCompositionDependencies"):
        register_production_dependencies(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact ProductionCompositionDependencies"):
        register_production_dependencies(DerivedDependencies())
    with pytest.raises(TypeError, match="exact ProductionCompositionDependencies"):
        build_application(production_dependencies=object())

    unavailable = build_injected_production_use_case(
        object(), DerivedDependencies()  # type: ignore[arg-type]
    )
    with pytest.raises(RoutingUnavailableError):
        unavailable.execute(None, None)


def test_same_object_is_idempotent_only_before_start_and_replacement_is_rejected() -> None:
    first = ProductionCompositionDependencies()
    second = ProductionCompositionDependencies()
    marker = object()

    register_production_dependencies(first)
    register_production_dependencies(first)
    with pytest.raises(RuntimeError, match="already registered"):
        register_production_dependencies(second)

    with patch("routing_api.container.build_application", return_value=marker) as build:
        assert get_application() is marker
        assert get_application() is marker

    build.assert_called_once_with(production_dependencies=first)
    with pytest.raises(RuntimeError, match="before application startup"):
        register_production_dependencies(first)
    with pytest.raises(RuntimeError, match="before application startup"):
        register_production_dependencies(second)


def test_concurrent_distinct_registration_never_replaces_the_winner() -> None:
    dependencies = (
        ProductionCompositionDependencies(),
        ProductionCompositionDependencies(),
    )
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, object]] = []
    outcomes_lock = threading.Lock()

    def register(value: ProductionCompositionDependencies) -> None:
        barrier.wait()
        try:
            register_production_dependencies(value)
        except RuntimeError as exc:
            outcome: tuple[str, object] = ("rejected", exc)
        else:
            outcome = ("accepted", value)
        with outcomes_lock:
            outcomes.append(outcome)

    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(executor.map(register, dependencies))

    accepted = [value for state, value in outcomes if state == "accepted"]
    rejected = [value for state, value in outcomes if state == "rejected"]
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert isinstance(rejected[0], RuntimeError)

    marker = object()
    with patch("routing_api.container.build_application", return_value=marker) as build:
        assert get_application() is marker
    build.assert_called_once_with(production_dependencies=accepted[0])


def test_concurrent_cached_get_builds_once_and_returns_one_identity() -> None:
    dependencies = ProductionCompositionDependencies()
    register_production_dependencies(dependencies)
    marker = object()
    build_calls = 0
    call_lock = threading.Lock()

    def slow_build(*, production_dependencies=None):
        nonlocal build_calls
        with call_lock:
            build_calls += 1
        assert production_dependencies is dependencies
        sleep(0.03)
        return marker

    with patch("routing_api.container.build_application", side_effect=slow_build):
        with ThreadPoolExecutor(max_workers=16) as executor:
            results = tuple(executor.map(lambda _: get_application(), range(32)))

    assert build_calls == 1
    assert all(value is marker for value in results)


def test_same_thread_reentrant_startup_fails_once_and_caches_the_error() -> None:
    build_calls = 0

    def reentrant_build(*, production_dependencies=None):
        nonlocal build_calls
        build_calls += 1
        assert production_dependencies is None
        return get_application()

    with patch("routing_api.container.build_application", side_effect=reentrant_build):
        with pytest.raises(RuntimeError, match="already in progress"):
            get_application()
        assert build_calls == 1
        with pytest.raises(RuntimeError, match="previously failed"):
            get_application()
        assert build_calls == 1


def test_registration_racing_after_build_start_fails_closed() -> None:
    started = threading.Event()
    release = threading.Event()
    marker = object()
    dependencies = ProductionCompositionDependencies()

    def blocking_build(*, production_dependencies=None):
        assert production_dependencies is None
        started.set()
        assert release.wait(timeout=2)
        return marker

    with patch("routing_api.container.build_application", side_effect=blocking_build):
        with ThreadPoolExecutor(max_workers=2) as executor:
            application_future = executor.submit(get_application)
            assert started.wait(timeout=2)
            registration_future = executor.submit(
                register_production_dependencies, dependencies
            )
            sleep(0.02)
            assert not registration_future.done()
            release.set()
            assert application_future.result(timeout=2) is marker
            with pytest.raises(RuntimeError, match="before application startup"):
                registration_future.result(timeout=2)


def test_default_process_build_is_zero_call_unavailable_and_all_false() -> None:
    missing = object()
    worker_before = sys.modules.get("routing_worker", missing)
    with (
        override_settings(
            ROUTING_FIXTURE_SCENARIO="",
            ROUTING_SERVICE_JWT_SECRET="x" * 32,
        ),
        patch.object(
            ProviderAdapterSuite,
            "from_config",
            side_effect=AssertionError("default startup constructed provider suite"),
        ) as provider_suite,
    ):
        application = get_application()

    provider_suite.assert_not_called()
    assert application.readiness()["checks"]["backend"] == "unavailable"
    assert not any(application.capabilities()["features"].values())
    assert sys.modules.get("routing_worker", missing) is worker_before


def test_registered_dependencies_do_not_import_worker_and_fixture_override_wins() -> None:
    missing = object()
    worker_before = sys.modules.get("routing_worker", missing)
    register_production_dependencies(ProductionCompositionDependencies())
    with override_settings(
        ROUTING_FIXTURE_SCENARIO="R1",
        ROUTING_ALLOW_FIXTURE_BACKEND=True,
        ROUTING_RUNTIME_ENVIRONMENT="TEST",
        ROUTING_SERVICE_JWT_SECRET="x" * 32,
    ):
        application = get_application()

    assert application.readiness()["checks"]["backend"] == "fixture-only:R1"
    assert sys.modules.get("routing_worker", missing) is worker_before


def test_isolated_registered_startup_never_imports_routing_worker() -> None:
    service_root = Path(__file__).resolve().parents[2]
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("ROUTING_")
    }
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "routing_api.settings",
            "PYTHONPATH": str(service_root),
            "ROUTING_RUNTIME_ENVIRONMENT": "TEST",
            "ROUTING_SERVICE_JWT_SECRET": "ri381-Isolated-Service-Secret-7f9A2c4E",
            "ROUTING_FIXTURE_SCENARIO": "",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from routing_api.workspace_packages import activate_workspace_packages; "
                "activate_workspace_packages(); "
                "import django; django.setup(); "
                "from routing_api.container import get_application, register_production_dependencies; "
                "from routing_api.production_composition import ProductionCompositionDependencies; "
                "assert 'routing_worker' not in sys.modules; "
                "register_production_dependencies(ProductionCompositionDependencies()); "
                "app=get_application(); "
                "assert app.readiness()['checks']['backend']=='unavailable'; "
                "assert not any(app.capabilities()['features'].values()); "
                "assert 'routing_worker' not in sys.modules"
            ),
        ],
        cwd=service_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_test_reset_clears_registration_cache_and_failure_state() -> None:
    first = ProductionCompositionDependencies()
    second = ProductionCompositionDependencies()
    first_application = object()
    second_application = object()

    register_production_dependencies(first)
    with patch(
        "routing_api.container.build_application", return_value=first_application
    ) as first_build:
        assert get_application() is first_application
    first_build.assert_called_once_with(production_dependencies=first)

    _reset_application_composition_for_tests()
    register_production_dependencies(second)
    with patch(
        "routing_api.container.build_application", return_value=second_application
    ) as second_build:
        assert get_application() is second_application
    second_build.assert_called_once_with(production_dependencies=second)

    _reset_application_composition_for_tests()
    with patch("routing_api.container.build_application", side_effect=ValueError("bad")):
        with pytest.raises(ValueError, match="bad"):
            get_application()
        with pytest.raises(RuntimeError, match="previously failed"):
            get_application()
    _reset_application_composition_for_tests()


def test_reset_is_unavailable_outside_a_pytest_process() -> None:
    with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}):
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        with pytest.raises(RuntimeError, match="test-only"):
            _reset_application_composition_for_tests()
