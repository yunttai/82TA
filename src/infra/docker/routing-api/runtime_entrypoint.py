"""Fail-closed Routing container launcher without secret output or persistence."""

from __future__ import annotations

import os
import sys


def _deployment_environment() -> bool:
    return os.environ.get("ROUTING_RUNTIME_ENVIRONMENT", "PRODUCTION").strip().upper() in {
        "STAGING",
        "PRODUCTION",
    }


def _require_deployment_inputs() -> None:
    if not _deployment_environment():
        return
    required = (
        "ROUTING_DJANGO_SECRET_KEY",
        "ROUTING_ALLOWED_HOSTS",
        "ROUTING_SERVICE_JWT_SECRET",
        "ROUTING_SERVICE_JWT_ISSUER",
        "ROUTING_SERVICE_JWT_AUDIENCE",
        "ROUTING_DB_NAME",
        "ROUTING_DB_USER",
        "ROUTING_DB_PASSWORD",
        "ROUTING_DB_HOST",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(
            "required Routing deployment inputs are missing: " + ", ".join(sorted(missing))
        )
    if os.environ.get("ROUTING_DB_SSLMODE", "") != "verify-full":
        raise SystemExit("ROUTING_DB_SSLMODE=verify-full is required in deployment")
    if os.environ.get("ROUTING_ALLOW_FIXTURE_BACKEND", "false").lower() != "false":
        raise SystemExit("fixture backend must remain disabled in deployment")


def _require_database_bootstrap_inputs() -> None:
    required = (
        "ROUTING_DB_ADMIN_NAME",
        "ROUTING_DB_ADMIN_USER",
        "ROUTING_DB_ADMIN_PASSWORD",
        "ROUTING_DB_ADMIN_HOST",
        "ROUTING_DB_ADMIN_PORT",
        "ROUTING_DB_APP_USER",
        "ROUTING_DB_APP_PASSWORD",
        "ROUTING_DB_MIGRATION_USER",
        "ROUTING_DB_MIGRATION_PASSWORD",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(
            "required Routing database bootstrap inputs are missing: "
            + ", ".join(sorted(missing))
        )
    if os.environ.get("ROUTING_DB_ADMIN_SSLMODE", "") != "verify-full":
        raise SystemExit("ROUTING_DB_ADMIN_SSLMODE=verify-full is required")


if len(sys.argv) < 2:
    raise SystemExit("a Routing runtime command is required")

task_mode = os.environ.get("ROUTING_TASK_MODE", "api").strip().lower()
if task_mode == "database-bootstrap":
    _require_database_bootstrap_inputs()
elif task_mode in {"api", "migration"}:
    _require_deployment_inputs()
else:
    raise SystemExit("ROUTING_TASK_MODE must be api, migration, or database-bootstrap")
os.execvp(sys.argv[1], sys.argv[1:])
