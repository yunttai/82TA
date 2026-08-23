from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal

import redis
from django.conf import settings
from redis.exceptions import RedisError, WatchError


class CoordinationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class IdempotencyDecision:
    state: Literal["CLAIMED", "REPLAY", "CONFLICT", "IN_PROGRESS"]
    lease_token: str | None = None
    response: dict[str, Any] | None = None


class RedisCoordination:
    """Atomic, cross-worker rate and idempotency coordination.

    Redis keys contain hashes only. Values retain a short-lived public response
    snapshot but never the raw user/guest identifier or public idempotency key.
    """

    def __init__(self, client: Any, *, prefix: str, digest_key: bytes | None = None) -> None:
        self._client = client
        self._prefix = prefix
        self._digest_key = digest_key or settings.COORDINATION_HMAC_KEY

    @classmethod
    def from_settings(cls) -> RedisCoordination:
        try:
            client_options = {
                "decode_responses": True,
                "socket_connect_timeout": settings.REDIS_SOCKET_TIMEOUT_SECONDS,
                "socket_timeout": settings.REDIS_SOCKET_TIMEOUT_SECONDS,
                "health_check_interval": 30,
                "retry_on_timeout": False,
            }
            if settings.REDIS_URL.lower().startswith("rediss://"):
                client_options.update(
                    {
                        "ssl_cert_reqs": "required",
                        "ssl_check_hostname": True,
                    }
                )
            client = redis.Redis.from_url(settings.REDIS_URL, **client_options)
        except (RedisError, ValueError) as exc:
            raise CoordinationUnavailable("Redis coordination could not be configured.") from exc
        return cls(
            client,
            prefix=settings.REDIS_KEY_PREFIX,
            digest_key=settings.COORDINATION_HMAC_KEY,
        )

    def enforce_rate_limit(self, *, scope: str, subject: str, limit: int) -> bool:
        if limit <= 0:
            return True
        window = int(time.time() // 60)
        digest = self._digest(f"{scope}:{subject}")
        key = f"{self._prefix}:rate:{digest}:{window}"
        try:
            pipeline = self._client.pipeline(transaction=True)
            pipeline.incr(key)
            pipeline.expire(key, settings.RATE_LIMIT_CACHE_TTL_SECONDS)
            count, _ = pipeline.execute()
            return int(count) <= limit
        except (RedisError, OSError, TypeError, ValueError) as exc:
            raise CoordinationUnavailable("Redis rate coordination is unavailable.") from exc

    def begin_idempotency(self, *, owner_key: str, fingerprint: str) -> IdempotencyDecision:
        key = self._idempotency_key(owner_key)
        lease_token = secrets.token_urlsafe(24)
        pending = self._encode(
            {
                "state": "PENDING",
                "fingerprint": fingerprint,
                "leaseToken": lease_token,
            }
        )
        try:
            if self._client.set(
                key,
                pending,
                nx=True,
                ex=settings.IDEMPOTENCY_LEASE_SECONDS,
            ):
                return IdempotencyDecision("CLAIMED", lease_token=lease_token)
            raw = self._client.get(key)
            if raw is None and self._client.set(
                key,
                pending,
                nx=True,
                ex=settings.IDEMPOTENCY_LEASE_SECONDS,
            ):
                return IdempotencyDecision("CLAIMED", lease_token=lease_token)
            value = self._decode(raw)
        except (RedisError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CoordinationUnavailable("Redis idempotency coordination is unavailable.") from exc

        if value.get("fingerprint") != fingerprint:
            return IdempotencyDecision("CONFLICT")
        if value.get("state") == "COMPLETE":
            response = value.get("response")
            if not isinstance(response, dict):
                raise CoordinationUnavailable("Redis idempotency response is invalid.")
            return IdempotencyDecision("REPLAY", response=response)
        if value.get("state") == "PENDING":
            return IdempotencyDecision("IN_PROGRESS")
        raise CoordinationUnavailable("Redis idempotency state is invalid.")

    def complete_idempotency(
        self,
        *,
        owner_key: str,
        fingerprint: str,
        lease_token: str,
        response: dict[str, Any],
    ) -> bool:
        key = self._idempotency_key(owner_key)
        complete = self._encode(
            {
                "state": "COMPLETE",
                "fingerprint": fingerprint,
                "response": response,
            }
        )
        try:
            with self._client.pipeline() as pipeline:
                for _ in range(3):
                    try:
                        pipeline.watch(key)
                        current = self._decode(pipeline.get(key))
                        if (
                            current.get("state") != "PENDING"
                            or current.get("fingerprint") != fingerprint
                            or current.get("leaseToken") != lease_token
                        ):
                            pipeline.unwatch()
                            return False
                        pipeline.multi()
                        pipeline.set(
                            key,
                            complete,
                            ex=settings.IDEMPOTENCY_CACHE_TTL_SECONDS,
                        )
                        pipeline.execute()
                        return True
                    except WatchError:
                        continue
        except (
            CoordinationUnavailable,
            RedisError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return False
        return False

    def abandon_idempotency(self, *, owner_key: str, lease_token: str) -> None:
        key = self._idempotency_key(owner_key)
        try:
            with self._client.pipeline() as pipeline:
                for _ in range(3):
                    try:
                        pipeline.watch(key)
                        current = self._decode(pipeline.get(key))
                        if (
                            current.get("state") != "PENDING"
                            or current.get("leaseToken") != lease_token
                        ):
                            pipeline.unwatch()
                            return
                        pipeline.multi()
                        pipeline.delete(key)
                        pipeline.execute()
                        return
                    except WatchError:
                        continue
        except (
            CoordinationUnavailable,
            RedisError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return

    def clear_for_tests(self) -> None:
        keys = list(self._client.scan_iter(match=f"{self._prefix}:*", count=1000))
        if keys:
            self._client.delete(*keys)

    def _idempotency_key(self, owner_key: str) -> str:
        return f"{self._prefix}:idempotency:{self._digest(owner_key)}"

    def _digest(self, value: str) -> str:
        return hmac.new(
            self._digest_key,
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _encode(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _decode(raw: str | bytes | None) -> dict[str, Any]:
        if raw is None:
            raise CoordinationUnavailable("Redis coordination entry disappeared.")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise CoordinationUnavailable("Redis coordination entry is invalid.")
        return value


_backend: RedisCoordination | None = None
_backend_signature: tuple[str, str, float, bytes] | None = None


def redis_coordination() -> RedisCoordination:
    global _backend, _backend_signature
    signature = (
        settings.REDIS_URL,
        settings.REDIS_KEY_PREFIX,
        settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        settings.COORDINATION_HMAC_KEY,
    )
    if _backend is None or _backend_signature != signature:
        _backend = RedisCoordination.from_settings()
        _backend_signature = signature
    return _backend


def set_redis_coordination_for_tests(value: RedisCoordination | None) -> None:
    global _backend, _backend_signature
    _backend = value
    _backend_signature = (
        settings.REDIS_URL,
        settings.REDIS_KEY_PREFIX,
        settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        settings.COORDINATION_HMAC_KEY,
    ) if value is not None else None
