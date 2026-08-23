from __future__ import annotations

import os
import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "packages/provider-core",
    "packages/routing-domain",
    "packages/bus-intelligence-core",
    "services/routing-api",
):
    path = str(SRC_ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "routing_api.settings")
os.environ.setdefault("ROUTING_RUNTIME_ENVIRONMENT", "TEST")

import django  # noqa: E402

django.setup()
