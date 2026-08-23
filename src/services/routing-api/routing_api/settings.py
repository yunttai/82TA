from __future__ import annotations

import ipaddress
import os
import re

from django.core.exceptions import ImproperlyConfigured


_RUNTIME_ENVIRONMENTS = frozenset({"PRODUCTION", "STAGING", "DEVELOPMENT", "TEST"})
_HOSTNAME = re.compile(
    r"(?=.{1,253}\Z)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\Z"
)
_SERVICE_AUTH_IDENTIFIER = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._:/-]{0,126}[A-Za-z0-9])?\Z"
)
_LOCAL_SERVICE_JWT_SECRET = (
    "routing-api-test-development-only-jwt-7Vq!4xP@9mK#2sL%6wN&8cR"
)
_LOCAL_SERVICE_JWT_ISSUER = "service-api"
_LOCAL_SERVICE_JWT_AUDIENCE = "routing-api"
_COMMON_UNSAFE_SERVICE_JWT_SECRETS = frozenset(
    {
        "change-me",
        "changeme",
        "default",
        "routing-api-secret",
        "secret",
    }
)


def _strict_boolean(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized not in {"true", "false"}:
        raise ImproperlyConfigured(f"{name} must be exactly true or false")
    return normalized == "true"


def _runtime_environment() -> str:
    value = os.environ.get("ROUTING_RUNTIME_ENVIRONMENT", "PRODUCTION").strip().upper()
    if value not in _RUNTIME_ENVIRONMENTS:
        raise ImproperlyConfigured(
            "ROUTING_RUNTIME_ENVIRONMENT must be PRODUCTION, STAGING, DEVELOPMENT, or TEST"
        )
    return value


def _strong_secret() -> str:
    value = os.environ.get("ROUTING_DJANGO_SECRET_KEY", "")
    if (
        len(value) < 50
        or len(set(value)) < 8
        or value.startswith("django-insecure-")
        or "local" in value.lower()
    ):
        raise ImproperlyConfigured(
            "ROUTING_DJANGO_SECRET_KEY must be an explicit strong deployment secret"
        )
    return value


def _valid_host(value: str) -> bool:
    if not value or value == "*" or value != value.strip() or any(
        token in value for token in ("://", "/", "\\", "@", " ")
    ):
        return False
    candidate = value[1:-1] if value.startswith("[") and value.endswith("]") else value
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return _HOSTNAME.fullmatch(value) is not None
    return True


def _deployment_hosts() -> list[str]:
    raw = os.environ.get("ROUTING_ALLOWED_HOSTS", "")
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not values or len(values) != len(set(values)) or not all(_valid_host(item) for item in values):
        raise ImproperlyConfigured(
            "ROUTING_ALLOWED_HOSTS must be an explicit unique comma-separated host allowlist"
        )
    return values


def _service_jwt_secret(*, deployment: bool) -> str:
    configured = os.environ.get("ROUTING_SERVICE_JWT_SECRET")
    if configured is None:
        if deployment:
            raise ImproperlyConfigured(
                "ROUTING_SERVICE_JWT_SECRET must be explicitly configured for deployment"
            )
        return _LOCAL_SERVICE_JWT_SECRET

    error = "ROUTING_SERVICE_JWT_SECRET must be an explicit strong service-auth secret"
    try:
        encoded = configured.encode("utf-8")
    except UnicodeEncodeError:
        raise ImproperlyConfigured(error) from None
    normalized = configured.strip().lower()
    if (
        configured != configured.strip()
        or any(ord(character) < 33 or ord(character) == 127 for character in configured)
        or not 32 <= len(encoded) <= 4096
        or len(set(configured)) < 8
        or normalized in _COMMON_UNSAFE_SERVICE_JWT_SECRETS
        or (deployment and configured == _LOCAL_SERVICE_JWT_SECRET)
    ):
        raise ImproperlyConfigured(error)
    return configured


def _service_auth_identifier(name: str, *, deployment: bool, local_default: str) -> str:
    configured = os.environ.get(name)
    if configured is None:
        if deployment:
            raise ImproperlyConfigured(f"{name} must be explicitly configured for deployment")
        return local_default
    error = f"{name} must be a bounded explicit service-auth identifier"
    try:
        encoded_length = len(configured.encode("utf-8"))
    except UnicodeEncodeError:
        raise ImproperlyConfigured(error) from None
    if (
        configured != configured.strip()
        or not 3 <= encoded_length <= 128
        or _SERVICE_AUTH_IDENTIFIER.fullmatch(configured) is None
    ):
        raise ImproperlyConfigured(error)
    return configured


ROUTING_RUNTIME_ENVIRONMENT = _runtime_environment()
_DEPLOYMENT = ROUTING_RUNTIME_ENVIRONMENT in {"STAGING", "PRODUCTION"}

if _DEPLOYMENT:
    SECRET_KEY = _strong_secret()
    ALLOWED_HOSTS = _deployment_hosts()
    if not _strict_boolean("ROUTING_SECURE_SSL_REDIRECT"):
        raise ImproperlyConfigured("ROUTING_SECURE_SSL_REDIRECT=true is required")
    if not _strict_boolean("ROUTING_TRUST_X_FORWARDED_PROTO"):
        raise ImproperlyConfigured(
            "ROUTING_TRUST_X_FORWARDED_PROTO=true is required behind the trusted internal ALB"
        )
else:
    # Explicit TEST/DEVELOPMENT only. Never accepted in a deployment runtime.
    SECRET_KEY = "routing-api-test-development-only-9fW3@qL8!vT6#kR2$zN7&xP4"
    ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1", "[::1]"]

DEBUG = False
ROOT_URLCONF = "routing_api.urls"
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
INSTALLED_APPS = ["django.contrib.contenttypes", "routing_api"]

SECURE_SSL_REDIRECT = _DEPLOYMENT
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https") if _DEPLOYMENT else None
)
SECURE_HSTS_SECONDS = 31_536_000 if _DEPLOYMENT else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = _DEPLOYMENT
SECURE_HSTS_PRELOAD = _DEPLOYMENT
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_SECURE = _DEPLOYMENT
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_SECURE = _DEPLOYMENT
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"

_routing_db_name = os.environ.get("ROUTING_DB_NAME", "").strip()
if _routing_db_name:
    _routing_db_values = {
        "USER": os.environ.get("ROUTING_DB_USER", "").strip(),
        "PASSWORD": os.environ.get("ROUTING_DB_PASSWORD", ""),
        "HOST": os.environ.get("ROUTING_DB_HOST", "").strip(),
    }
    _sslmode = os.environ.get("ROUTING_DB_SSLMODE", "require").strip()
    if _DEPLOYMENT and (
        not all(_routing_db_values.values()) or _sslmode != "verify-full"
    ):
        raise ImproperlyConfigured(
            "deployment Routing DB requires user/password/host and ROUTING_DB_SSLMODE=verify-full"
        )
    try:
        _connection_age = int(os.environ.get("ROUTING_DB_CONN_MAX_AGE", "60"))
    except ValueError as exc:
        raise ImproperlyConfigured("ROUTING_DB_CONN_MAX_AGE must be an integer") from exc
    if _connection_age < 0:
        raise ImproperlyConfigured("ROUTING_DB_CONN_MAX_AGE must be nonnegative")
    DATABASES = {
        "default": {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": _routing_db_name,
            **_routing_db_values,
            "PORT": os.environ.get("ROUTING_DB_PORT", "5432"),
            "CONN_MAX_AGE": _connection_age,
            "OPTIONS": {"sslmode": _sslmode},
        }
    }
else:
    # Metadata/local checks do not silently replace PostGIS semantics with SQLite.
    DATABASES = {"default": {"ENGINE": "django.db.backends.dummy"}}
ROUTING_DB_CONFIGURED = bool(_routing_db_name)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Asia/Seoul"
DEFAULT_CHARSET = "utf-8"

ROUTING_SERVICE_JWT_SECRET = _service_jwt_secret(deployment=_DEPLOYMENT)
ROUTING_SERVICE_JWT_ISSUER = _service_auth_identifier(
    "ROUTING_SERVICE_JWT_ISSUER",
    deployment=_DEPLOYMENT,
    local_default=_LOCAL_SERVICE_JWT_ISSUER,
)
ROUTING_SERVICE_JWT_AUDIENCE = _service_auth_identifier(
    "ROUTING_SERVICE_JWT_AUDIENCE",
    deployment=_DEPLOYMENT,
    local_default=_LOCAL_SERVICE_JWT_AUDIENCE,
)
ROUTING_BUILD_VERSION = os.environ.get("ROUTING_BUILD_VERSION", "routing-api-foundation-0.1.0")
ROUTING_FIXTURE_SCENARIO = os.environ.get("ROUTING_FIXTURE_SCENARIO", "")
ROUTING_ALLOW_FIXTURE_BACKEND = _strict_boolean(
    "ROUTING_ALLOW_FIXTURE_BACKEND", default=False
)
