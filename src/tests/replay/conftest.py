from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
for relative in (
    "src/tests/replay",
    "src/packages/provider-core",
    "src/packages/bus-intelligence-core",
    "src/packages/routing-domain",
    "src/services/routing-api",
    "src/workers",
    "src/workers/data-quality",
):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)
