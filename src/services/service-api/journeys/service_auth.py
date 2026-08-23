from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable


_SERVICE_AUTH_IDENTIFIER = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._:/-]{0,126}[A-Za-z0-9])?\Z"
)
_NOT_BEFORE_CLOCK_SKEW_SECONDS = 5


def _encode_segment(value: dict[str, object]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


@dataclass(slots=True)
class Hs256ServiceJwtIssuer:
    """Mint short-lived Routing service JWTs without retaining them in client reprs."""

    secret: bytes = field(repr=False)
    issuer: str
    audience: str
    ttl_seconds: int = 60
    now: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC),
        repr=False,
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _cached_token: str | None = field(default=None, init=False, repr=False)
    _cached_expires_at: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            not 32 <= len(self.secret) <= 4096
            or self.secret != self.secret.strip()
            or any(value < 33 or value == 127 for value in self.secret)
            or len(set(self.secret)) < 8
        ):
            raise ValueError("service JWT secret is invalid")
        if _SERVICE_AUTH_IDENTIFIER.fullmatch(self.issuer) is None:
            raise ValueError("service JWT issuer is invalid")
        if _SERVICE_AUTH_IDENTIFIER.fullmatch(self.audience) is None:
            raise ValueError("service JWT audience is invalid")
        if not 15 <= self.ttl_seconds <= 300:
            raise ValueError("service JWT TTL must be between 15 and 300 seconds")

    def authorization_header(self) -> str:
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("service JWT clock must return a timezone-aware datetime")
        now_seconds = int(now.astimezone(UTC).timestamp())
        refresh_before_seconds = min(10, max(1, self.ttl_seconds // 3))
        with self._lock:
            if (
                self._cached_token is None
                or self._cached_expires_at - now_seconds <= refresh_before_seconds
            ):
                self._cached_token, self._cached_expires_at = self._mint(now_seconds)
            return f"Bearer {self._cached_token}"

    def _mint(self, now_seconds: int) -> tuple[str, int]:
        expires_at = now_seconds + self.ttl_seconds
        header = _encode_segment({"alg": "HS256", "typ": "JWT"})
        payload = _encode_segment(
            {
                "aud": self.audience,
                "exp": expires_at,
                "iat": now_seconds,
                "iss": self.issuer,
                "jti": secrets.token_urlsafe(18),
                # A small, fixed backdate tolerates ordinary clock skew between
                # independently deployed Service and Routing tasks. Expiry stays
                # short and is never extended by this allowance.
                "nbf": now_seconds - _NOT_BEFORE_CLOCK_SKEW_SECONDS,
            }
        )
        signature = hmac.new(
            self.secret,
            f"{header}.{payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
        return f"{header}.{payload}.{encoded_signature}", expires_at
