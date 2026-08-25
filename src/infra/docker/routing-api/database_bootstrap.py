"""Create the least-privilege Routing application role and PostGIS extension.

This module is executed only by a dedicated one-off GCE database bootstrap process. It
does not log SQL, connection details, role passwords, or secret values.
"""

from __future__ import annotations

import os

import psycopg
from psycopg import sql


_APPLICATION_ROLE = "routing_app"
_MIGRATION_ROLE = "routing_migrator"


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"required database bootstrap input is missing: {name}")
    return value


def main() -> None:
    action = os.environ.get("ROUTING_DB_BOOTSTRAP_ACTION", "prepare").strip().lower()
    if action not in {"prepare", "finalize"}:
        raise SystemExit("ROUTING_DB_BOOTSTRAP_ACTION must be prepare or finalize")
    database = _required("ROUTING_DB_ADMIN_NAME")
    app_role = _required("ROUTING_DB_APP_USER")
    if app_role != _APPLICATION_ROLE:
        raise SystemExit("Routing application role must be routing_app")
    app_password = _required("ROUTING_DB_APP_PASSWORD")
    migration_role = _required("ROUTING_DB_MIGRATION_USER")
    if migration_role != _MIGRATION_ROLE:
        raise SystemExit("Routing migration role must be routing_migrator")
    migration_password = _required("ROUTING_DB_MIGRATION_PASSWORD")

    connection = psycopg.connect(
        dbname=database,
        user=_required("ROUTING_DB_ADMIN_USER"),
        password=_required("ROUTING_DB_ADMIN_PASSWORD"),
        host=_required("ROUTING_DB_ADMIN_HOST"),
        port=_required("ROUTING_DB_ADMIN_PORT"),
        sslmode=_required("ROUTING_DB_ADMIN_SSLMODE"),
        connect_timeout=10,
        application_name="82ta-routing-database-bootstrap",
    )
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '30s'")
            cursor.execute("SET lock_timeout = '5s'")
            cursor.execute("SELECT pg_advisory_lock(hashtext('82ta-routing-database-bootstrap'))")
            try:
                app = sql.Identifier(app_role)
                migrator = sql.Identifier(migration_role)
                if action == "prepare":
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
                    for role_name, role_password in (
                        (app_role, app_password),
                        (migration_role, migration_password),
                    ):
                        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
                        role_exists = cursor.fetchone() is not None
                        role = sql.Identifier(role_name)
                        statement = "ALTER ROLE" if role_exists else "CREATE ROLE"
                        cursor.execute(
                            sql.SQL(
                                statement
                                + " {} WITH LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB "
                                "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                            ).format(role),
                            (role_password,),
                        )
                    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
                        sql.Identifier(database), app, migrator
                    ))
                    cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(app))
                    cursor.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(migrator))
                else:
                    cursor.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(migrator))
                    cursor.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(migrator))
                cursor.execute(sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
                ).format(app))
                cursor.execute(sql.SQL(
                    "REVOKE INSERT, UPDATE, DELETE ON TABLE public.spatial_ref_sys FROM {}"
                ).format(app))
                cursor.execute(sql.SQL(
                    "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {}"
                ).format(app))
            finally:
                cursor.execute("SELECT pg_advisory_unlock(hashtext('82ta-routing-database-bootstrap'))")
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except psycopg.Error:
        raise SystemExit("Routing database bootstrap failed") from None
