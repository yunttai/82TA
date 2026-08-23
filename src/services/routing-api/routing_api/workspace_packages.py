"""Explicit source-checkout package activation for local fixture composition.

Deployed integration should install internal wheels. This helper is intentionally
called only by local fixture tooling/tests; the fail-closed production default has
no source-tree import dependency.
"""

from __future__ import annotations

import sys
from pathlib import Path


def activate_workspace_packages() -> tuple[Path, ...]:
    src_root = Path(__file__).resolve().parents[3]
    candidates = (
        src_root / "packages" / "provider-core",
        src_root / "packages" / "bus-intelligence-core",
        src_root / "packages" / "routing-domain",
    )
    activated: list[Path] = []
    for candidate in candidates:
        if not candidate.is_dir():
            raise RuntimeError(f"required local integration package is missing: {candidate.name}")
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)
        activated.append(candidate)
    return tuple(activated)
