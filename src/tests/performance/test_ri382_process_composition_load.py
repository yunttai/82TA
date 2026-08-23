"""Local process-composition contention evidence for RI-382.

This is an in-process fixture measurement.  It is not network, PostgreSQL, model,
multi-instance, or production SLO evidence.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from unittest.mock import patch

import pytest

from routing_api.container import (
    _reset_application_composition_for_tests,
    get_application,
    register_production_dependencies,
)
from routing_api.production_composition import ProductionCompositionDependencies


def _metric(**values: object) -> None:
    print("RI382_METRIC " + json.dumps(values, sort_keys=True))


@pytest.fixture(autouse=True)
def _isolated_process_composition() -> None:
    _reset_application_composition_for_tests()
    yield
    _reset_application_composition_for_tests()


@pytest.mark.parametrize("concurrency", (10, 50, 100))
def test_cached_process_application_builds_once_under_startup_burst(
    concurrency: int,
) -> None:
    dependencies = ProductionCompositionDependencies()
    register_production_dependencies(dependencies)
    marker = object()
    build_calls = 0
    lock = Lock()

    def slow_build(*, production_dependencies=None):
        nonlocal build_calls
        with lock:
            build_calls += 1
        assert production_dependencies is dependencies
        time.sleep(0.02)
        return marker

    started = time.perf_counter()
    with patch("routing_api.container.build_application", side_effect=slow_build):
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            results = tuple(executor.map(lambda _: get_application(), range(concurrency)))
    elapsed_ms = (time.perf_counter() - started) * 1_000

    assert build_calls == 1
    assert all(result is marker for result in results)
    assert elapsed_ms < 2_000
    _metric(
        scenario="one_shot_process_composition_startup_burst",
        concurrency=concurrency,
        build_calls=build_calls,
        returned_identity_count=len({id(result) for result in results}),
        elapsed_ms=round(elapsed_ms, 4),
        evidence_scope="local_fixture_no_network_db_or_model_not_production_slo",
    )

