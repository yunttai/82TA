from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from django.conf import settings
from django.views.decorators.debug import sensitive_variables


@sensitive_variables("parts", "message")
def _digest(*parts: str) -> str:
    message = "\x00".join(parts).encode("utf-8")
    return hmac.new(
        settings.COORDINATION_HMAC_KEY,
        message,
        hashlib.sha256,
    ).hexdigest()


@sensitive_variables("raw_key")
def idempotency_key_digest(*, user_id: str, raw_key: str) -> str:
    """Return an owner-scoped digest; the caller must never persist the raw key."""

    return _digest(
        f"favorite-create-key-v{settings.FAVORITE_IDEMPOTENCY_DIGEST_KEY_VERSION}",
        user_id,
        raw_key,
    )


@sensitive_variables("payload", "normalized")
def canonical_favorite_creation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize schema defaults without retaining or mutating the request object."""

    normalized = {
        "nickname": payload["nickname"],
        "originPlace": dict(payload["originPlace"]),
        "destinationPlace": dict(payload["destinationPlace"]),
        "searchConditions": payload["searchConditions"],
    }
    normalized["originPlace"]["isSensitive"] = payload["originPlace"].get(
        "isSensitive", True
    )
    normalized["destinationPlace"]["isSensitive"] = payload[
        "destinationPlace"
    ].get("isSensitive", True)
    return normalized


@sensitive_variables("payload", "canonical")
def request_fingerprint(*, user_id: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        canonical_favorite_creation_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _digest(
        f"favorite-create-body-v{settings.FAVORITE_IDEMPOTENCY_DIGEST_KEY_VERSION}",
        user_id,
        canonical,
    )


def typed_search_conditions(value: Any, *, validator: Any) -> dict[str, Any] | None:
    """Recognize only the locked versioned schema; opaque legacy JSON fails closed."""

    if not isinstance(value, dict) or validator(value):
        return None
    return value
