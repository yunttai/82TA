from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


SERVICE_ROOT = Path(__file__).resolve().parents[2]
STRONG_SECRET = "Prod-Routing-Secret!9xQ@7mK#4vT$2pL%8sW&6nR*3zC_2026"
SERVICE_AUTH_SECRET = "Synthetic-Service-Auth!7vQ@2mK#9xP$4sL%8wN&6cR"
SERVICE_AUTH_ISSUER = "service-api.synthetic.internal"
SERVICE_AUTH_AUDIENCE = "routing-api.synthetic.internal"


def _deployment_values(environment: str = "PRODUCTION") -> dict[str, str]:
    return {
        "ROUTING_RUNTIME_ENVIRONMENT": environment,
        "ROUTING_DJANGO_SECRET_KEY": STRONG_SECRET,
        "ROUTING_ALLOWED_HOSTS": "routing.internal.example",
        "ROUTING_SECURE_SSL_REDIRECT": "true",
        "ROUTING_TRUST_X_FORWARDED_PROTO": "true",
        "ROUTING_SERVICE_JWT_SECRET": SERVICE_AUTH_SECRET,
        "ROUTING_SERVICE_JWT_ISSUER": SERVICE_AUTH_ISSUER,
        "ROUTING_SERVICE_JWT_AUDIENCE": SERVICE_AUTH_AUDIENCE,
    }


def _settings_process(code: str, **values: str) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("ROUTING_")
    }
    environment.update(values)
    environment["PYTHONPATH"] = str(SERVICE_ROOT)
    environment["DJANGO_SETTINGS_MODULE"] = "routing_api.settings"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=SERVICE_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _manage_process(*arguments: str, **values: str) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("ROUTING_")
    }
    environment.update(values)
    environment["PYTHONPATH"] = str(SERVICE_ROOT)
    environment["DJANGO_SETTINGS_MODULE"] = "routing_api.settings"
    return subprocess.run(
        [sys.executable, "manage.py", *arguments],
        cwd=SERVICE_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"ROUTING_RUNTIME_ENVIRONMENT": "PRODUCTION"},
        {
            "ROUTING_RUNTIME_ENVIRONMENT": "PRODUCTION",
            "ROUTING_DJANGO_SECRET_KEY": "weak",
        },
        {
            "ROUTING_RUNTIME_ENVIRONMENT": "PRODUCTION",
            "ROUTING_DJANGO_SECRET_KEY": STRONG_SECRET,
            "ROUTING_ALLOWED_HOSTS": "*",
            "ROUTING_SECURE_SSL_REDIRECT": "true",
            "ROUTING_TRUST_X_FORWARDED_PROTO": "true",
        },
        {
            "ROUTING_RUNTIME_ENVIRONMENT": "PRODUCTION",
            "ROUTING_DJANGO_SECRET_KEY": STRONG_SECRET,
            "ROUTING_ALLOWED_HOSTS": "routing.internal.example",
            "ROUTING_SECURE_SSL_REDIRECT": "false",
            "ROUTING_TRUST_X_FORWARDED_PROTO": "true",
        },
    ],
)
def test_unsafe_deployment_settings_fail_initialization(values: dict[str, str]) -> None:
    completed = _settings_process("import routing_api.settings", **values)
    assert completed.returncode != 0
    assert "ImproperlyConfigured" in completed.stderr


def test_explicit_test_runtime_uses_local_dummy_database_and_security_middleware() -> None:
    completed = _settings_process(
        "import routing_api.settings as s; "
        "assert s.ROUTING_RUNTIME_ENVIRONMENT == 'TEST'; "
        "assert s.DATABASES['default']['ENGINE'] == 'django.db.backends.dummy'; "
        "assert s.ROUTING_DB_CONFIGURED is False; "
        "assert 'django.middleware.security.SecurityMiddleware' in s.MIDDLEWARE; "
        "assert 'django.middleware.csrf.CsrfViewMiddleware' in s.MIDDLEWARE; "
        "assert 'django.middleware.clickjacking.XFrameOptionsMiddleware' in s.MIDDLEWARE",
        ROUTING_RUNTIME_ENVIRONMENT="TEST",
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("runtime_environment", ["STAGING", "PRODUCTION"])
@pytest.mark.parametrize(
    ("name", "unsafe_value"),
    [
        ("ROUTING_SERVICE_JWT_SECRET", None),
        ("ROUTING_SERVICE_JWT_SECRET", ""),
        ("ROUTING_SERVICE_JWT_SECRET", "weak"),
        ("ROUTING_SERVICE_JWT_SECRET", "x" * 64),
        (
            "ROUTING_SERVICE_JWT_SECRET",
            "routing-api-test-development-only-jwt-7Vq!4xP@9mK#2sL%6wN&8cR",
        ),
        ("ROUTING_SERVICE_JWT_ISSUER", None),
        ("ROUTING_SERVICE_JWT_ISSUER", ""),
        ("ROUTING_SERVICE_JWT_ISSUER", " issuer-with-space "),
        ("ROUTING_SERVICE_JWT_ISSUER", "i" * 129),
        ("ROUTING_SERVICE_JWT_AUDIENCE", None),
        ("ROUTING_SERVICE_JWT_AUDIENCE", ""),
        ("ROUTING_SERVICE_JWT_AUDIENCE", "audience with space"),
        ("ROUTING_SERVICE_JWT_AUDIENCE", "a" * 129),
    ],
)
def test_deployment_service_auth_requires_explicit_strong_bounded_material(
    runtime_environment: str,
    name: str,
    unsafe_value: str | None,
) -> None:
    values = _deployment_values(runtime_environment)
    if unsafe_value is None:
        del values[name]
    else:
        values[name] = unsafe_value
    completed = _settings_process("import routing_api.settings", **values)
    assert completed.returncode != 0
    assert "ImproperlyConfigured" in completed.stderr
    assert SERVICE_AUTH_SECRET not in completed.stdout + completed.stderr


@pytest.mark.parametrize(
    ("name", "unsafe_value"),
    [
        ("ROUTING_SERVICE_JWT_SECRET", None),
        ("ROUTING_SERVICE_JWT_SECRET", "weak"),
        (
            "ROUTING_SERVICE_JWT_SECRET",
            "routing-api-test-development-only-jwt-7Vq!4xP@9mK#2sL%6wN&8cR",
        ),
        ("ROUTING_SERVICE_JWT_ISSUER", None),
        ("ROUTING_SERVICE_JWT_AUDIENCE", None),
    ],
)
def test_django_deploy_check_rejects_unsafe_service_auth_material(
    name: str,
    unsafe_value: str | None,
) -> None:
    values = _deployment_values()
    if unsafe_value is None:
        del values[name]
    else:
        values[name] = unsafe_value
    completed = _manage_process("check", "--deploy", **values)
    assert completed.returncode != 0
    assert "ImproperlyConfigured" in completed.stderr
    assert SERVICE_AUTH_SECRET not in completed.stdout + completed.stderr


def test_explicit_local_runtimes_have_safe_nonempty_service_auth_defaults() -> None:
    for runtime_environment in ("TEST", "DEVELOPMENT"):
        completed = _settings_process(
            "import routing_api.settings as s; "
            "assert len(s.ROUTING_SERVICE_JWT_SECRET.encode('utf-8')) >= 32; "
            "assert s.ROUTING_SERVICE_JWT_ISSUER == 'service-api'; "
            "assert s.ROUTING_SERVICE_JWT_AUDIENCE == 'routing-api'",
            ROUTING_RUNTIME_ENVIRONMENT=runtime_environment,
        )
        assert completed.returncode == 0, completed.stderr


def test_provider_credentials_are_optional_bounded_configuration_only() -> None:
    secret = "provider-credential-test-value"
    completed = _settings_process(
        "import routing_api.settings as s; "
        "assert s.KAKAO_MOBILITY_REST_API_KEY == 'provider-credential-test-value'; "
        "assert s.GBIS_SERVICE_KEY == ''",
        ROUTING_RUNTIME_ENVIRONMENT="TEST",
        KAKAO_MOBILITY_REST_API_KEY=secret,
    )
    assert completed.returncode == 0, completed.stderr
    assert secret not in completed.stdout + completed.stderr

    invalid = _settings_process(
        "import routing_api.settings",
        ROUTING_RUNTIME_ENVIRONMENT="TEST",
        KAKAO_MOBILITY_REST_API_KEY=" credential-with-spaces ",
    )
    assert invalid.returncode != 0
    assert "KAKAO_MOBILITY_REST_API_KEY" in invalid.stderr
    assert "credential-with-spaces" not in invalid.stdout + invalid.stderr


def test_explicit_production_settings_trust_only_the_internal_alb_header_contract() -> None:
    completed = _settings_process(
        "import routing_api.settings as s; "
        "assert s.ALLOWED_HOSTS == ['routing.internal.example']; "
        "assert s.SECURE_SSL_REDIRECT is True; "
        "assert s.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https'); "
        "assert s.SECURE_HSTS_SECONDS == 31536000; "
        "assert s.SECURE_HSTS_INCLUDE_SUBDOMAINS and s.SECURE_HSTS_PRELOAD; "
        "assert s.CSRF_COOKIE_SECURE and s.SESSION_COOKIE_SECURE; "
        "assert s.SECURE_CONTENT_TYPE_NOSNIFF; "
        "assert s.SECURE_REFERRER_POLICY == 'same-origin'; "
        "assert s.X_FRAME_OPTIONS == 'DENY'",
        ROUTING_RUNTIME_ENVIRONMENT="PRODUCTION",
        ROUTING_DJANGO_SECRET_KEY=STRONG_SECRET,
        ROUTING_ALLOWED_HOSTS="routing.internal.example",
        ROUTING_SECURE_SSL_REDIRECT="true",
        ROUTING_TRUST_X_FORWARDED_PROTO="true",
        ROUTING_SERVICE_JWT_SECRET=SERVICE_AUTH_SECRET,
        ROUTING_SERVICE_JWT_ISSUER=SERVICE_AUTH_ISSUER,
        ROUTING_SERVICE_JWT_AUDIENCE=SERVICE_AUTH_AUDIENCE,
    )
    assert completed.returncode == 0, completed.stderr


def test_deployment_database_requires_postgis_credentials_and_verify_full_tls() -> None:
    completed = _settings_process(
        "import routing_api.settings",
        ROUTING_RUNTIME_ENVIRONMENT="STAGING",
        ROUTING_DJANGO_SECRET_KEY=STRONG_SECRET,
        ROUTING_ALLOWED_HOSTS="routing-staging.internal.example",
        ROUTING_SECURE_SSL_REDIRECT="true",
        ROUTING_TRUST_X_FORWARDED_PROTO="true",
        ROUTING_SERVICE_JWT_SECRET=SERVICE_AUTH_SECRET,
        ROUTING_SERVICE_JWT_ISSUER=SERVICE_AUTH_ISSUER,
        ROUTING_SERVICE_JWT_AUDIENCE=SERVICE_AUTH_AUDIENCE,
        ROUTING_DB_NAME="routing",
        ROUTING_DB_USER="routing_owner",
        ROUTING_DB_PASSWORD="secret",
        ROUTING_DB_HOST="routing-db.internal",
        ROUTING_DB_SSLMODE="require",
    )
    assert completed.returncode != 0
    assert "ROUTING_DB_SSLMODE=verify-full" in completed.stderr


def test_django_deploy_check_has_no_security_warning_under_explicit_deploy_config() -> None:
    completed = _manage_process("check", "--deploy", **_deployment_values())
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "System check identified no issues" in completed.stdout
    assert "WARNINGS" not in completed.stdout + completed.stderr


def test_container_verifier_uses_the_validated_settings_without_secret_repr() -> None:
    completed = _settings_process(
        "from routing_api import settings as s; "
        "from routing_api.container import get_application; "
        "app = get_application(); verifier = app._verifier; "
        "assert verifier.secret == s.ROUTING_SERVICE_JWT_SECRET.encode('utf-8'); "
        "assert verifier.issuer == s.ROUTING_SERVICE_JWT_ISSUER; "
        "assert verifier.audience == s.ROUTING_SERVICE_JWT_AUDIENCE; "
        "assert s.ROUTING_SERVICE_JWT_SECRET not in repr(verifier)",
        **_deployment_values(),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert SERVICE_AUTH_SECRET not in completed.stdout + completed.stderr
