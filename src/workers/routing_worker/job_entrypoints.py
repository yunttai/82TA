"""Explicit installed worker job-family entrypoints.

These entrypoints only narrow the closed command set. They deliberately reuse the
fail-closed CLI, inject no executor, start no scheduler, and load no credential,
database, Provider, artifact, or model at import time.
"""

from __future__ import annotations

import json
import sys
from typing import Sequence

from .cli import main as worker_main


_COLLECTOR = frozenset({"collector-run"})
_QUALITY = frozenset({"quality-gate", "dataset-build"})
_LEGACY = frozenset({"legacy-inventory", "legacy-import-plan"})
_MODEL = frozenset(
    {
        "evaluate-eta",
        "evaluate-seat",
        "model-register",
        "model-vocabulary-inventory",
        "model-transition",
        "drift-audit",
        "model-rollback",
    }
)


def _family_main(allowed: frozenset[str], argv: Sequence[str] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in allowed:
        sys.stderr.write(
            json.dumps(
                {
                    "error": "job entrypoint requires an allowed explicit command",
                    "status": "FAIL_CLOSED",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 2
    return worker_main(arguments)


def collector_main(argv: Sequence[str] | None = None) -> int:
    return _family_main(_COLLECTOR, argv)


def quality_main(argv: Sequence[str] | None = None) -> int:
    return _family_main(_QUALITY, argv)


def legacy_main(argv: Sequence[str] | None = None) -> int:
    return _family_main(_LEGACY, argv)


def model_main(argv: Sequence[str] | None = None) -> int:
    return _family_main(_MODEL, argv)


__all__ = ["collector_main", "legacy_main", "model_main", "quality_main"]
