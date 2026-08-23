import hashlib
import hmac
import ipaddress
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

ENVIRONMENT = os.environ.get("SERVICE_ENVIRONMENT", "development").lower()
_configured_secret = os.environ.get("SERVICE_SECRET_KEY")
if ENVIRONMENT == "production" and not _configured_secret:
    raise RuntimeError("SERVICE_SECRET_KEY is required in production")
if ENVIRONMENT == "production" and len(_configured_secret or "") < 32:
    raise RuntimeError("SERVICE_SECRET_KEY must contain at least 32 characters in production")
SECRET_KEY = _configured_secret or "unsafe-development-only"
DEBUG = os.environ.get("SERVICE_DEBUG", "true" if ENVIRONMENT == "development" else "false").lower() == "true"
if ENVIRONMENT == "production" and DEBUG:
    raise RuntimeError("SERVICE_DEBUG must be false in production")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("SERVICE_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if host.strip()
]


def _https_origins(raw: str) -> list[str]:
    origins: list[str] = []
    for candidate in (value.strip() for value in raw.split(",")):
        if not candidate:
            continue
        try:
            parsed = urlsplit(candidate)
            host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
            port = parsed.port
        except (UnicodeError, ValueError) as exc:
            raise RuntimeError("SERVICE_CSRF_TRUSTED_ORIGINS contains an invalid origin") from exc
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("SERVICE_CSRF_TRUSTED_ORIGINS must contain HTTPS origins only")
        authority = f"[{host}]" if ":" in host else host
        if port is not None and port != 443:
            authority = f"{authority}:{port}"
        origins.append(f"https://{authority}")
    return origins


CSRF_TRUSTED_ORIGINS = _https_origins(os.environ.get("SERVICE_CSRF_TRUSTED_ORIGINS", ""))

CONSENT_PURPOSES = (
    "SERVICE_PRIVACY",
    "SEARCH_HISTORY",
    "PRECISE_LOCATION",
    "PRODUCT_ANALYTICS",
    "ROUTING_FEEDBACK",
)
_consent_version_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_consent_document_version = os.environ.get("SERVICE_CONSENT_DOCUMENT_VERSION", "").strip()
if not _consent_document_version and ENVIRONMENT != "production":
    _consent_document_version = "local-development"
if not _consent_document_version:
    raise RuntimeError(
        "A current consent document version is required in production; configure "
        "SERVICE_CONSENT_DOCUMENT_VERSION"
    )
if _consent_version_pattern.fullmatch(_consent_document_version) is None:
    raise RuntimeError("SERVICE_CONSENT_DOCUMENT_VERSION contains an invalid consent document version")
_purpose_specific_consent_variables = tuple(
    name
    for name in (f"SERVICE_CONSENT_{purpose}_DOCUMENT_VERSION" for purpose in CONSENT_PURPOSES)
    if os.environ.get(name, "").strip()
)
if _purpose_specific_consent_variables:
    raise RuntimeError(
        "Purpose-specific consent document versions are unsupported; use one "
        "SERVICE_CONSENT_DOCUMENT_VERSION registration bundle"
    )
CONSENT_DOCUMENT_VERSIONS = {
    purpose: _consent_document_version for purpose in CONSENT_PURPOSES
}

TRUST_PROXY_HEADERS = os.environ.get("SERVICE_TRUST_PROXY_HEADERS", "false").lower() == "true"
TRUSTED_PROXY_IPS = tuple(
    address.strip()
    for address in os.environ.get("SERVICE_TRUSTED_PROXY_IPS", "").split(",")
    if address.strip()
)
if ENVIRONMENT == "production" and TRUST_PROXY_HEADERS and not TRUSTED_PROXY_IPS:
    raise RuntimeError("SERVICE_TRUSTED_PROXY_IPS is required when proxy headers are trusted")
if ENVIRONMENT == "production" and TRUST_PROXY_HEADERS:
    try:
        for address_or_cidr in TRUSTED_PROXY_IPS:
            ipaddress.ip_network(address_or_cidr, strict=False)
    except ValueError as exc:
        raise RuntimeError("SERVICE_TRUSTED_PROXY_IPS contains an invalid IP address or CIDR") from exc

ROOT_URLCONF = "service_api.urls"
INSTALLED_APPS = ["django.contrib.contenttypes", "django.contrib.sessions", "journeys"]
MIDDLEWARE = [
    "journeys.middleware.TrustedProxyHeadersMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if ENVIRONMENT == "production" and not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required in production")
if DATABASE_URL:
    if ENVIRONMENT == "production" and not DATABASE_URL.lower().startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL must use PostgreSQL in production")
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=60,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "service-api.sqlite3",
        }
    }

REDIS_URL = os.environ.get("SERVICE_REDIS_URL", "").strip()
COORDINATION_BACKEND = "redis" if REDIS_URL else "local"
if ENVIRONMENT == "production" and not REDIS_URL:
    raise RuntimeError("SERVICE_REDIS_URL is required in production")
if REDIS_URL:
    try:
        _redis_url = urlsplit(REDIS_URL)
        _redis_port = _redis_url.port
    except ValueError as exc:
        raise RuntimeError("SERVICE_REDIS_URL is invalid") from exc
    if (
        _redis_url.scheme not in ({"rediss"} if ENVIRONMENT == "production" else {"redis", "rediss"})
        or not _redis_url.hostname
        or (
            _redis_url.path not in ("", "/")
            and re.fullmatch(r"/[0-9]+", _redis_url.path) is None
        )
        or _redis_url.query
        or _redis_url.fragment
    ):
        raise RuntimeError("SERVICE_REDIS_URL must be a valid private Redis URL; production requires rediss")
    if _redis_port is not None and not 1 <= _redis_port <= 65535:
        raise RuntimeError("SERVICE_REDIS_URL contains an invalid port")

USE_TZ = True
TIME_ZONE = "Asia/Seoul"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = ENVIRONMENT == "production"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = ENVIRONMENT == "production"
CSRF_FAILURE_VIEW = "journeys.views.csrf_failure"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = ENVIRONMENT == "production"
SECURE_HSTS_SECONDS = 31_536_000 if ENVIRONMENT == "production" else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = ENVIRONMENT == "production"
SECURE_HSTS_PRELOAD = ENVIRONMENT == "production"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if TRUST_PROXY_HEADERS else None

_configured_gateway_mode = os.environ.get("SERVICE_ROUTING_GATEWAY")
if ENVIRONMENT == "production" and not (_configured_gateway_mode or "").strip():
    raise RuntimeError("SERVICE_ROUTING_GATEWAY is required in production")
ROUTING_GATEWAY_MODE = (_configured_gateway_mode or "stub").strip().lower()
if ROUTING_GATEWAY_MODE not in {"stub", "replay", "http"}:
    raise RuntimeError("SERVICE_ROUTING_GATEWAY must be stub, replay, or http")
if ENVIRONMENT == "production" and ROUTING_GATEWAY_MODE != "http":
    raise RuntimeError("SERVICE_ROUTING_GATEWAY must be http in production")

_configured_routing_api_base_url = os.environ.get("SERVICE_ROUTING_API_BASE_URL")
if ENVIRONMENT == "production" and not (_configured_routing_api_base_url or "").strip():
    raise RuntimeError("SERVICE_ROUTING_API_BASE_URL is required in production")
ROUTING_API_BASE_URL = (
    _configured_routing_api_base_url or "http://127.0.0.1:8001"
).strip()
ROUTING_SERVICE_JWT_SECRET = os.environ.get("SERVICE_ROUTING_JWT_SECRET", "")
_configured_routing_jwt_issuer = os.environ.get("SERVICE_ROUTING_JWT_ISSUER")
_configured_routing_jwt_audience = os.environ.get("SERVICE_ROUTING_JWT_AUDIENCE")
ROUTING_SERVICE_JWT_ISSUER = _configured_routing_jwt_issuer or "service-api"
ROUTING_SERVICE_JWT_AUDIENCE = _configured_routing_jwt_audience or "routing-api"
ROUTING_SERVICE_JWT_TTL_SECONDS = int(os.environ.get("SERVICE_ROUTING_JWT_TTL_SECONDS", "60"))
_routing_service_auth_identifier = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._:/-]{0,126}[A-Za-z0-9])?\Z"
)
ROUTING_VERIFY_SSL = os.environ.get("SERVICE_ROUTING_VERIFY_SSL", "true").lower() == "true"
ROUTING_API_ALLOWED_HOSTS = tuple(
    host.strip()
    for host in os.environ.get("SERVICE_ROUTING_API_ALLOWED_HOSTS", "").split(",")
    if host.strip()
)
_routing_dns_label = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)\Z")


def _normalize_routing_hostname(raw: str, *, setting: str) -> str:
    candidate = raw.strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    try:
        host = candidate.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise RuntimeError(f"{setting} contains an invalid host") from exc
    if not host or any(character in host for character in "*/@?#[]"):
        raise RuntimeError(f"{setting} contains an invalid host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or any(
            _routing_dns_label.fullmatch(label) is None for label in host.split(".")
        ):
            raise RuntimeError(f"{setting} contains an invalid host") from None
    return host


def _routing_origin_hostname(raw: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(raw)
        host = _normalize_routing_hostname(
            parsed.hostname or "",
            setting="SERVICE_ROUTING_API_BASE_URL",
        )
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise RuntimeError("SERVICE_ROUTING_API_BASE_URL is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("SERVICE_ROUTING_API_BASE_URL must be an HTTP(S) origin")
    default_port = 443 if parsed.scheme == "https" else 80
    authority = f"[{host}]" if ":" in host else host
    if port is not None and port != default_port:
        authority = f"{authority}:{port}"
    return f"{parsed.scheme}://{authority}", host


if ROUTING_GATEWAY_MODE == "http":
    ROUTING_API_BASE_URL, _routing_api_hostname = _routing_origin_hostname(
        ROUTING_API_BASE_URL
    )
    ROUTING_API_ALLOWED_HOSTS = tuple(
        _normalize_routing_hostname(
            host,
            setting="SERVICE_ROUTING_API_ALLOWED_HOSTS",
        )
        for host in ROUTING_API_ALLOWED_HOSTS
    )
    if ROUTING_API_ALLOWED_HOSTS and _routing_api_hostname not in ROUTING_API_ALLOWED_HOSTS:
        raise RuntimeError("SERVICE_ROUTING_API_BASE_URL host is not allowed")

if ENVIRONMENT == "production" and ROUTING_GATEWAY_MODE == "http":
    _routing_jwt_secret = ROUTING_SERVICE_JWT_SECRET.encode("utf-8")
    if (
        not 32 <= len(_routing_jwt_secret) <= 4096
        or _routing_jwt_secret != _routing_jwt_secret.strip()
        or any(value < 33 or value == 127 for value in _routing_jwt_secret)
        or len(set(_routing_jwt_secret)) < 8
    ):
        raise RuntimeError("SERVICE_ROUTING_JWT_SECRET must be an explicit strong secret")
    if not _configured_routing_jwt_issuer or not _configured_routing_jwt_audience:
        raise RuntimeError("Routing service JWT issuer and audience must be explicit in production")
    if (
        _routing_service_auth_identifier.fullmatch(ROUTING_SERVICE_JWT_ISSUER) is None
        or _routing_service_auth_identifier.fullmatch(ROUTING_SERVICE_JWT_AUDIENCE) is None
    ):
        raise RuntimeError("Routing service JWT issuer and audience are invalid")
    if not ROUTING_API_ALLOWED_HOSTS:
        raise RuntimeError("SERVICE_ROUTING_API_ALLOWED_HOSTS is required for the HTTP RoutingGateway")
    if not ROUTING_API_BASE_URL.startswith("https://"):
        raise RuntimeError("SERVICE_ROUTING_API_BASE_URL must use HTTPS in production")
    if not ROUTING_VERIFY_SSL:
        raise RuntimeError("SERVICE_ROUTING_VERIFY_SSL must be true in production")
PUBLIC_RATE_LIMIT_PER_MINUTE = int(os.environ.get("SERVICE_RATE_LIMIT_PER_MINUTE", "60"))
GUEST_SESSION_RATE_LIMIT_PER_MINUTE = int(
    os.environ.get("SERVICE_GUEST_SESSION_RATE_LIMIT_PER_MINUTE", "10")
)
AUTH_RATE_LIMIT_PER_MINUTE = int(os.environ.get("SERVICE_AUTH_RATE_LIMIT_PER_MINUTE", "10"))
AUTH_SESSION_TTL_SECONDS = int(os.environ.get("SERVICE_AUTH_SESSION_TTL_SECONDS", "1209600"))
if not 300 <= AUTH_SESSION_TTL_SECONDS <= 2_592_000:
    raise RuntimeError("SERVICE_AUTH_SESSION_TTL_SECONDS must be between 300 and 2592000")
PLACE_RATE_LIMIT_PER_MINUTE = int(os.environ.get("SERVICE_PLACE_RATE_LIMIT_PER_MINUTE", "60"))
PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS = int(
    os.environ.get("SERVICE_PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS", "7000")
)
ROUTING_DEADLINE_MILLISECONDS = int(os.environ.get("SERVICE_ROUTING_DEADLINE_MILLISECONDS", "6500"))
ROUTING_NETWORK_MARGIN_MILLISECONDS = (
    PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS - ROUTING_DEADLINE_MILLISECONDS
)
if not 15 <= ROUTING_SERVICE_JWT_TTL_SECONDS <= 300:
    raise RuntimeError("SERVICE_ROUTING_JWT_TTL_SECONDS must be between 15 and 300")
if not 1 <= PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS <= 7000:
    raise RuntimeError(
        "SERVICE_PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS must be between 1 and 7000"
    )
if not 1 <= ROUTING_DEADLINE_MILLISECONDS <= 6500:
    raise RuntimeError(
        "SERVICE_ROUTING_DEADLINE_MILLISECONDS must be between 1 and 6500"
    )
if ROUTING_NETWORK_MARGIN_MILLISECONDS < 500:
    raise RuntimeError(
        "Service route-search budget must preserve at least 500ms after the Routing deadline"
    )
ROUTING_CAPABILITIES_CACHE_TTL_SECONDS = int(
    os.environ.get("SERVICE_ROUTING_CAPABILITIES_CACHE_TTL_SECONDS", "60")
)
if ROUTING_CAPABILITIES_CACHE_TTL_SECONDS <= 0:
    raise RuntimeError("SERVICE_ROUTING_CAPABILITIES_CACHE_TTL_SECONDS must be positive")
ROUTING_MAX_RESPONSE_BYTES = int(
    os.environ.get("SERVICE_ROUTING_MAX_RESPONSE_BYTES", str(2 * 1024 * 1024))
)
if not 1024 <= ROUTING_MAX_RESPONSE_BYTES <= 16 * 1024 * 1024:
    raise RuntimeError("SERVICE_ROUTING_MAX_RESPONSE_BYTES must be between 1024 and 16777216")
IDEMPOTENCY_CACHE_MAX_ENTRIES = int(os.environ.get("SERVICE_IDEMPOTENCY_CACHE_MAX_ENTRIES", "10000"))
IDEMPOTENCY_CACHE_TTL_SECONDS = int(os.environ.get("SERVICE_IDEMPOTENCY_CACHE_TTL_SECONDS", "600"))
RATE_LIMIT_CACHE_MAX_ENTRIES = int(os.environ.get("SERVICE_RATE_LIMIT_CACHE_MAX_ENTRIES", "10000"))
RATE_LIMIT_CACHE_TTL_SECONDS = int(os.environ.get("SERVICE_RATE_LIMIT_CACHE_TTL_SECONDS", "120"))
if ENVIRONMENT == "production" and any(
    limit <= 0
    for limit in (
        PUBLIC_RATE_LIMIT_PER_MINUTE,
        GUEST_SESSION_RATE_LIMIT_PER_MINUTE,
        AUTH_RATE_LIMIT_PER_MINUTE,
        PLACE_RATE_LIMIT_PER_MINUTE,
    )
):
    raise RuntimeError("Service production rate limits must be positive")
if COORDINATION_BACKEND == "redis" and RATE_LIMIT_CACHE_TTL_SECONDS < 60:
    raise RuntimeError("SERVICE_RATE_LIMIT_CACHE_TTL_SECONDS must cover the one-minute rate window")
if IDEMPOTENCY_CACHE_TTL_SECONDS <= 0:
    raise RuntimeError("SERVICE_IDEMPOTENCY_CACHE_TTL_SECONDS must be positive")
if COORDINATION_BACKEND == "local" and (
    IDEMPOTENCY_CACHE_MAX_ENTRIES <= 0 or RATE_LIMIT_CACHE_MAX_ENTRIES <= 0
):
    raise RuntimeError("Local coordination cache bounds must be positive")
REDIS_KEY_PREFIX = os.environ.get("SERVICE_REDIS_KEY_PREFIX", "82ta:service:1.1").strip()
if re.fullmatch(r"[A-Za-z0-9:._-]{1,64}", REDIS_KEY_PREFIX) is None:
    raise RuntimeError("SERVICE_REDIS_KEY_PREFIX contains unsupported characters")
_configured_coordination_secret = os.environ.get(
    "SERVICE_REDIS_KEY_DERIVATION_SECRET", ""
).strip()
if _configured_coordination_secret and len(_configured_coordination_secret) < 32:
    raise RuntimeError("SERVICE_REDIS_KEY_DERIVATION_SECRET must contain at least 32 characters")
COORDINATION_HMAC_KEY = hmac.new(
    (_configured_coordination_secret or SECRET_KEY).encode("utf-8"),
    b"82ta-service-redis-coordination-v1",
    hashlib.sha256,
).digest()
REDIS_SOCKET_TIMEOUT_SECONDS = float(
    os.environ.get("SERVICE_REDIS_SOCKET_TIMEOUT_SECONDS", "0.25")
)
if REDIS_SOCKET_TIMEOUT_SECONDS <= 0 or REDIS_SOCKET_TIMEOUT_SECONDS > 5:
    raise RuntimeError("SERVICE_REDIS_SOCKET_TIMEOUT_SECONDS must be greater than 0 and at most 5")
IDEMPOTENCY_LEASE_SECONDS = int(
    os.environ.get("SERVICE_IDEMPOTENCY_LEASE_SECONDS", "15")
)
if IDEMPOTENCY_LEASE_SECONDS <= 0:
    raise RuntimeError("SERVICE_IDEMPOTENCY_LEASE_SECONDS must be positive")
if IDEMPOTENCY_CACHE_TTL_SECONDS <= IDEMPOTENCY_LEASE_SECONDS:
    raise RuntimeError("SERVICE_IDEMPOTENCY_CACHE_TTL_SECONDS must exceed the lease duration")
if ENVIRONMENT == "production" and IDEMPOTENCY_LEASE_SECONDS * 1000 <= ROUTING_DEADLINE_MILLISECONDS:
    raise RuntimeError("SERVICE_IDEMPOTENCY_LEASE_SECONDS must exceed the Routing deadline")
GUEST_SESSION_TTL_SECONDS = int(os.environ.get("SERVICE_GUEST_SESSION_TTL_SECONDS", "86400"))
ROUTE_RESULT_TTL_SECONDS = int(os.environ.get("SERVICE_ROUTE_RESULT_TTL_SECONDS", "600"))
MEMBER_HISTORY_RETENTION_DAYS = int(os.environ.get("SERVICE_MEMBER_HISTORY_RETENTION_DAYS", "90"))

_configured_data_rights_artifact_backend = os.environ.get(
    "SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND", ""
).strip()
if ENVIRONMENT == "production" and not _configured_data_rights_artifact_backend:
    raise RuntimeError("SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND is required in production")
DATA_RIGHTS_ARTIFACT_BACKEND = _configured_data_rights_artifact_backend or "disabled"
if DATA_RIGHTS_ARTIFACT_BACKEND not in {"disabled", "encrypted-filesystem"}:
    raise RuntimeError(
        "SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND must be disabled or encrypted-filesystem"
    )
DATA_RIGHTS_ARTIFACT_DIRECTORY = os.environ.get(
    "SERVICE_DATA_RIGHTS_ARTIFACT_DIRECTORY", ""
).strip()
DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY = os.environ.get(
    "SERVICE_DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY", ""
).strip()
if DATA_RIGHTS_ARTIFACT_BACKEND == "encrypted-filesystem":
    if not DATA_RIGHTS_ARTIFACT_DIRECTORY:
        raise RuntimeError(
            "SERVICE_DATA_RIGHTS_ARTIFACT_DIRECTORY is required for encrypted-filesystem"
        )
    if ENVIRONMENT == "production" and not Path(DATA_RIGHTS_ARTIFACT_DIRECTORY).is_absolute():
        raise RuntimeError(
            "SERVICE_DATA_RIGHTS_ARTIFACT_DIRECTORY must be absolute in production"
        )
    if not DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY:
        raise RuntimeError(
            "SERVICE_DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY is required for encrypted-filesystem"
        )
DATA_RIGHTS_EXPORT_TTL_SECONDS = int(
    os.environ.get("SERVICE_DATA_RIGHTS_EXPORT_TTL_SECONDS", "900")
)
if DATA_RIGHTS_EXPORT_TTL_SECONDS <= 0:
    raise RuntimeError("SERVICE_DATA_RIGHTS_EXPORT_TTL_SECONDS must be positive")
KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")
if ENVIRONMENT == "production" and not KAKAO_REST_API_KEY:
    raise RuntimeError("KAKAO_REST_API_KEY is required in production")
KAKAO_LOCAL_BASE_URL = "https://dapi.kakao.com"
KAKAO_LOCAL_TIMEOUT_SECONDS = float(os.environ.get("KAKAO_LOCAL_TIMEOUT_SECONDS", "2.0"))
KAKAO_LOCAL_MAX_RESPONSE_BYTES = int(
    os.environ.get("SERVICE_KAKAO_LOCAL_MAX_RESPONSE_BYTES", str(512 * 1024))
)
if not 1024 <= KAKAO_LOCAL_MAX_RESPONSE_BYTES <= 2 * 1024 * 1024:
    raise RuntimeError("SERVICE_KAKAO_LOCAL_MAX_RESPONSE_BYTES must be between 1024 and 2097152")
PLACE_CACHE_TTL_SECONDS = int(os.environ.get("SERVICE_PLACE_CACHE_TTL_SECONDS", "300"))
PLACE_CACHE_MAX_ENTRIES = int(os.environ.get("SERVICE_PLACE_CACHE_MAX_ENTRIES", "2000"))
