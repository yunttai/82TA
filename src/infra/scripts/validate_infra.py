#!/usr/bin/env python3
"""Validate Service Product deployment artifacts without cloud credentials."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def run(command: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd or ROOT, check=True)


run([sys.executable, "-m", "unittest", "discover", "-s", "src/infra/tests", "-p", "test_*.py"])

if terraform := shutil.which("terraform"):
    run([terraform, "fmt", "-check", "-recursive", "src/infra/terraform"])
    staging = ROOT / "src" / "infra" / "terraform" / "environments" / "staging"
    run([terraform, "init", "-backend=false", "-input=false"], cwd=staging)
    run([terraform, "validate"], cwd=staging)
else:
    print("SKIP terraform fmt/validate: terraform is not installed")

if docker := shutil.which("docker"):
    run([docker, "compose", "-f", "src/infra/docker/compose.service-product.yml", "config", "--quiet"])
    run([docker, "compose", "-f", "src/infra/docker/compose.routing-e2e.yml", "config", "--quiet"])
else:
    print("SKIP docker compose config: docker is not installed")

print("INFRASTRUCTURE VALIDATION OK")
