from __future__ import annotations

import base64
import hashlib
import hmac
import json
from math import isfinite
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol


class AuthenticationError(ValueError):
    """Raised for every safe-to-report service authentication failure."""


class ServiceBearerVerifier(Protocol):
    def verify(self, authorization: str | None) -> Mapping[str, object]: ...


def _numeric_date(value: object, claim: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
    ):
        raise AuthenticationError(f"invalid service bearer {claim}")
    return float(value)


def _decode_segment(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, base64.binascii.Error) as exc:
        raise AuthenticationError("invalid service bearer") from exc


@dataclass(frozen=True)
class Hs256ServiceBearerVerifier:
    secret: bytes = field(repr=False)
    issuer: str
    audience: str
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def verify(self, authorization: str | None) -> Mapping[str, object]:
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthenticationError("service bearer required")
        if len(self.secret) < 32:
            raise AuthenticationError("service authentication is not configured")

        token = authorization.removeprefix("Bearer ").strip()
        segments = token.split(".")
        if len(segments) != 3:
            raise AuthenticationError("invalid service bearer")
        encoded_header, encoded_payload, encoded_signature = segments
        try:
            header = json.loads(_decode_segment(encoded_header))
            claims = json.loads(_decode_segment(encoded_payload))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AuthenticationError("invalid service bearer") from exc
        if not isinstance(header, dict) or header.get("alg") != "HS256":
            raise AuthenticationError("invalid service bearer")
        if not isinstance(claims, dict):
            raise AuthenticationError("invalid service bearer")

        expected = hmac.new(
            self.secret,
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        supplied = _decode_segment(encoded_signature)
        if not hmac.compare_digest(expected, supplied):
            raise AuthenticationError("invalid service bearer")

        now_seconds = self.now().astimezone(timezone.utc).timestamp()
        audience = claims.get("aud")
        audience_is_valid = (
            isinstance(audience, str)
            and bool(audience.strip())
        ) or (
            isinstance(audience, list)
            and bool(audience)
            and all(isinstance(item, str) and bool(item.strip()) for item in audience)
        )
        audience_matches = audience_is_valid and (
            audience == self.audience
            or (isinstance(audience, list) and self.audience in audience)
        )
        exp = claims.get("exp")
        jti = claims.get("jti")
        if claims.get("iss") != self.issuer or not audience_matches:
            raise AuthenticationError("invalid service bearer")
        if _numeric_date(exp, "exp") <= now_seconds:
            raise AuthenticationError("expired service bearer")
        if "nbf" in claims:
            if _numeric_date(claims["nbf"], "nbf") > now_seconds:
                raise AuthenticationError("service bearer is not active")
        if "iat" in claims:
            _numeric_date(claims["iat"], "iat")
        if not isinstance(jti, str) or not jti.strip():
            raise AuthenticationError("service bearer jti is required")
        return claims
