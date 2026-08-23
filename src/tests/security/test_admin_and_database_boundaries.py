from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.test import Client, override_settings

from routing_api.container import get_application
from routing_api.persistence.admin_services import (
    ModelActivationCommand,
    ModelRollbackCommand,
    OperatorClaims,
)
from routing_api.tests.test_admin_api import _control, _token


def _admin_post(path: str, body: bytes | str, token: str | None):
    headers = {} if token is None else {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    return Client().post(path, data=body, content_type="application/json", **headers)


def test_admin_service_identity_is_separate_from_operator_role_and_environment() -> None:
    control, cache, audit, _ = _control()
    with patch("routing_api.views.get_admin_control_plane", return_value=control):
        unauthenticated = _admin_post(
            "/internal/admin/cache/invalidate",
            json.dumps({"namespace": "provider-routes"}),
            None,
        )
        service_only = _admin_post(
            "/internal/admin/cache/invalidate",
            json.dumps({"namespace": "provider-routes"}),
            _token(roles=("service-api",)),
        )
        wrong_environment = _admin_post(
            "/internal/admin/cache/invalidate",
            json.dumps({"namespace": "provider-routes"}),
            _token(environments=("prod",)),
        )
        accepted = _admin_post(
            "/internal/admin/cache/invalidate",
            json.dumps({"namespace": "provider-routes", "fingerprint": "a" * 64}),
            _token(),
        )

    assert unauthenticated.status_code == 401
    assert service_only.status_code == wrong_environment.status_code == 403
    assert accepted.status_code == 202
    assert cache.calls == [("provider-routes", "a" * 64)]
    assert len(audit.events) == 1
    assert audit.events[0].environment == "staging"
    assert audit.events[0].operator_subject == "operator-123"


def test_admin_json_namespace_and_fingerprint_fail_closed_before_side_effect() -> None:
    control, cache, audit, _ = _control()
    with patch("routing_api.views.get_admin_control_plane", return_value=control):
        responses = (
            _admin_post(
                "/internal/admin/cache/invalidate",
                b'{"namespace":"unknown","namespace":"provider-routes"}',
                _token(),
            ),
            _admin_post(
                "/internal/admin/cache/invalidate",
                json.dumps({"namespace": "not-allowlisted"}),
                _token(),
            ),
            _admin_post(
                "/internal/admin/cache/invalidate",
                json.dumps({"namespace": "provider-routes", "fingerprint": "../all"}),
                _token(),
            ),
        )
    assert all(response.status_code == 400 for response in responses)
    assert cache.calls == []
    assert audit.events == ()


def test_admin_model_body_lifecycle_rollback_and_audit_are_bounded() -> None:
    control, _, audit, registry = _control()
    with patch("routing_api.views.get_admin_control_plane", return_value=control):
        malformed = (
            _admin_post(
                "/internal/admin/models/eta-1.0.0/activate",
                b'{"purpose":"SEAT_RISK","purpose":"BUS_ETA","environment":"staging"}',
                _token(),
            ),
            _admin_post(
                "/internal/admin/models/eta-1.0.0/activate",
                b'{"purpose":"BUS_ETA","environment":"staging","trafficFraction":NaN}',
                _token(),
            ),
        )
    assert all(response.status_code == 400 for response in malformed)
    assert registry.transitions == []
    assert audit.events == ()

    claims = OperatorClaims(
        "operator-123", frozenset({"routing-admin"}), frozenset({"staging"})
    )
    control.model_service.activate(
        ModelActivationCommand("BUS_ETA", "eta-1.0.0", "staging", 0), claims
    )
    control.model_service.activate(
        ModelActivationCommand("BUS_ETA", "eta-1.0.0", "staging", 0.1), claims
    )
    control.model_service.activate(
        ModelActivationCommand("BUS_ETA", "eta-1.0.0", "staging", 1), claims
    )
    rolled_back = control.model_service.rollback(
        ModelRollbackCommand("BUS_ETA", "eta-1.0.0", "staging"), claims
    )
    assert rolled_back.state == "ACTIVE"
    assert registry.rollbacks == ["eta-1.0.0"]
    assert [event.action for event in audit.events] == [
        "MODEL_TRANSITIONED",
        "MODEL_TRANSITIONED",
        "MODEL_TRANSITIONED",
        "MODEL_ROLLED_BACK",
    ]


def test_routing_database_is_postgis_or_dummy_only_and_contains_no_user_identity() -> None:
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.dummy"
    assert settings.ROUTING_DB_CONFIGURED is False
    assert "sqlite" not in repr(settings.DATABASES).lower()

    forbidden = {
        "user",
        "user_id",
        "email",
        "phone",
        "phone_number",
        "social_id",
        "saved_place",
        "saved_place_label",
    }
    field_names = {
        field.name.lower()
        for model in apps.get_app_config("routing_api").get_models()
        for field in model._meta.get_fields()
    }
    assert field_names.isdisjoint(forbidden)


def test_service_database_environment_cannot_reconfigure_routing_database() -> None:
    service_root = Path(__file__).resolve().parents[2] / "services" / "routing-api"
    environment = dict(os.environ)
    environment.pop("ROUTING_DB_NAME", None)
    environment.update(
        {
            "SERVICE_DB_NAME": "service_owned",
            "DATABASE_URL": "sqlite:///service.sqlite3",
            "PYTHONPATH": str(service_root),
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            (
                "import routing_api.settings as s; "
                "assert s.ROUTING_DB_CONFIGURED is False; "
                "assert s.DATABASES['default']['ENGINE']=='django.db.backends.dummy'; "
                "assert 'sqlite' not in repr(s.DATABASES).lower()"
            ),
        ],
        cwd=str(service_root),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_fixture_backend_needs_explicit_opt_in_and_nonproduction_environment() -> None:
    configurations = (
        ({"ROUTING_FIXTURE_SCENARIO": "R1"}, "fixture-blocked"),
        (
            {
                "ROUTING_FIXTURE_SCENARIO": "R1",
                "ROUTING_ALLOW_FIXTURE_BACKEND": True,
                "ROUTING_RUNTIME_ENVIRONMENT": "PRODUCTION",
            },
            "fixture-blocked",
        ),
        (
            {
                "ROUTING_FIXTURE_SCENARIO": "R1",
                "ROUTING_ALLOW_FIXTURE_BACKEND": True,
                "ROUTING_RUNTIME_ENVIRONMENT": "TEST",
            },
            "fixture-only:R1",
        ),
    )
    try:
        for overrides, expected in configurations:
            with override_settings(**overrides):
                get_application.cache_clear()
                assert get_application().readiness()["checks"]["backend"] == expected
    finally:
        get_application.cache_clear()
