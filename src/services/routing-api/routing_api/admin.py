"""Internal admin HTTP application over RI-250 service primitives.

Construction requires explicit durable dependencies.  The default container
does not create this object and therefore exposes neither in-memory audit nor
an unapproved model registry as a production control plane.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from routing_api.application import (
    ApiResult,
    _problem,
    _reject_duplicate_keys,
    _reject_json_constant,
)
from routing_api.auth import AuthenticationError, ServiceBearerVerifier
from routing_api.persistence.admin_services import (
    AdminAuthorizationError,
    AdminConflictError,
    AdminValidationError,
    CacheInvalidationCommand,
    CacheInvalidationService,
    ModelActivationCommand,
    ModelActivationService,
    OperatorClaims,
)


def _operator_claims(value: Mapping[str, object]) -> OperatorClaims:
    subject = value.get("sub")
    roles = value.get("roles")
    environments = value.get("environments")
    if (
        not isinstance(subject, str)
        or not subject.strip()
        or not isinstance(roles, list)
        or not all(isinstance(item, str) and item.strip() for item in roles)
        or not isinstance(environments, list)
        or not all(isinstance(item, str) and item.strip() for item in environments)
    ):
        raise AdminAuthorizationError("operator claims are incomplete")
    return OperatorClaims(subject, frozenset(roles), frozenset(environments))


def _body(raw_body: bytes) -> Mapping[str, object]:
    if len(raw_body) > 16_384:
        raise AdminValidationError("admin request is too large")
    try:
        value = json.loads(
            raw_body,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise AdminValidationError("admin request must be JSON") from exc
    if not isinstance(value, dict):
        raise AdminValidationError("admin request must be an object")
    return value


@dataclass(frozen=True, slots=True)
class AdminControlPlane:
    verifier: ServiceBearerVerifier
    cache_service: CacheInvalidationService
    model_service: ModelActivationService
    cache_environment: str

    def _authenticate(
        self, authorization: str | None, correlation_id: str
    ) -> OperatorClaims | ApiResult:
        try:
            return _operator_claims(self.verifier.verify(authorization))
        except AuthenticationError:
            return _problem(
                401,
                "SERVICE_AUTH_REQUIRED",
                "Service authentication required",
                correlation_id,
            )
        except AdminAuthorizationError:
            return _problem(
                403,
                "FORBIDDEN",
                "Operator authorization required",
                correlation_id,
            )

    def invalidate_cache(
        self,
        *,
        authorization: str | None,
        correlation_id: str,
        raw_body: bytes,
    ) -> ApiResult:
        claims = self._authenticate(authorization, correlation_id)
        if isinstance(claims, ApiResult):
            return claims
        try:
            value = _body(raw_body)
            if set(value) - {"namespace", "fingerprint"}:
                raise AdminValidationError("unknown cache invalidation field")
            namespace = value.get("namespace")
            fingerprint = value.get("fingerprint")
            if not isinstance(namespace, str) or not namespace.strip():
                raise AdminValidationError("namespace is required")
            if fingerprint is not None and not isinstance(fingerprint, str):
                raise AdminValidationError("fingerprint must be a string or null")
            self.cache_service.invalidate(
                CacheInvalidationCommand(
                    namespace=namespace,
                    environment=self.cache_environment,
                    fingerprint=fingerprint,
                ),
                claims,
            )
        except AdminAuthorizationError:
            return _problem(403, "FORBIDDEN", "Operator is not authorized", correlation_id)
        except AdminValidationError:
            return _problem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid cache invalidation request", correlation_id)
        return ApiResult(202, {"status": "accepted"}, correlation_id=correlation_id)

    def activate_model(
        self,
        *,
        authorization: str | None,
        correlation_id: str,
        version: str,
        raw_body: bytes,
    ) -> ApiResult:
        claims = self._authenticate(authorization, correlation_id)
        if isinstance(claims, ApiResult):
            return claims
        try:
            value = _body(raw_body)
            if set(value) - {"purpose", "environment", "trafficFraction"}:
                raise AdminValidationError("unknown model activation field")
            purpose = value.get("purpose")
            environment = value.get("environment")
            traffic = value.get("trafficFraction", 1)
            if (
                not isinstance(version, str)
                or not version.strip()
                or not isinstance(purpose, str)
                or not isinstance(environment, str)
                or not isinstance(traffic, (int, float))
                or isinstance(traffic, bool)
            ):
                raise AdminValidationError("invalid model activation fields")
            deployment = self.model_service.activate(
                ModelActivationCommand(
                    purpose=purpose,
                    version=version,
                    environment=environment,
                    traffic_fraction=float(traffic),
                ),
                claims,
            )
        except AdminAuthorizationError:
            return _problem(403, "FORBIDDEN", "Operator is not authorized", correlation_id)
        except AdminValidationError:
            return _problem(400, "CONSTRAINT_OUT_OF_RANGE", "Invalid model activation request", correlation_id)
        except AdminConflictError:
            # The registry has no 409 model-lifecycle code. Keep the registered
            # MODEL_NOT_READY semantics instead of locally inventing a code;
            # the handoff records the OpenAPI response gap.
            return _problem(503, "MODEL_NOT_READY", "Model lifecycle transition is not ready", correlation_id, retryable=True)
        return ApiResult(
            202,
            {"status": "accepted", "state": deployment.state},
            correlation_id=correlation_id,
        )
