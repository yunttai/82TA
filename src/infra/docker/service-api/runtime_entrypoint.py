"""Construct secret-bearing runtime configuration without writing it to disk."""

from __future__ import annotations

import os
import sys
from urllib.parse import quote


def _database_url_from_environment() -> str | None:
    required = (
        "SERVICE_DATABASE_HOST",
        "SERVICE_DATABASE_PORT",
        "SERVICE_DATABASE_NAME",
        "SERVICE_DATABASE_USER",
        "SERVICE_DATABASE_PASSWORD",
    )
    if not all(os.environ.get(name) for name in required):
        return None
    user = quote(os.environ["SERVICE_DATABASE_USER"], safe="")
    password = quote(os.environ["SERVICE_DATABASE_PASSWORD"], safe="")
    host = os.environ["SERVICE_DATABASE_HOST"]
    port = os.environ["SERVICE_DATABASE_PORT"]
    database = quote(os.environ["SERVICE_DATABASE_NAME"], safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode=require"


if not os.environ.get("DATABASE_URL"):
    generated_url = _database_url_from_environment()
    if generated_url:
        os.environ["DATABASE_URL"] = generated_url

if os.environ.get("SERVICE_ENVIRONMENT", "development").lower() == "production" and not os.environ.get(
    "DATABASE_URL"
):
    raise SystemExit("DATABASE_URL inputs are required in production")

os.execvp(sys.argv[1], sys.argv[1:])
