from __future__ import annotations

import tomllib
from pathlib import Path

from setuptools import find_namespace_packages


def test_routing_api_distribution_discovers_mapping_runtime() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    discovery = config["tool"]["setuptools"]["packages"]["find"]
    discovered = set(
        find_namespace_packages(
            where=str(project_root),
            include=discovery["include"],
            exclude=discovery["exclude"],
        )
    )
    assert "routing_api" in discovered
    assert "routing_api.persistence" in discovered
    assert "routing_api.migrations" in discovered
    assert "transport_mapping" in discovered
    assert "routing_api.tests" not in discovered
    assert "transport_mapping.tests" not in discovered
