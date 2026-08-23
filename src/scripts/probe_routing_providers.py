#!/usr/bin/env python3
"""Report or live-probe fixed Routing Provider scopes without exposing secrets."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "packages" / "provider-core"))

from provider_core import (  # noqa: E402
    KAKAO_BASELINE_KEY_ENV,
    KAKAO_BASELINE_SCHEMA_VERSIONS,
    NetworkEgressAttestation,
    SensitiveValue,
    build_strict_https_transport,
)
from provider_core.probe import probe_kakao_operation, probe_scope_names  # noqa: E402
from provider_core.transport import EgressEnforcement  # noqa: E402


ATTESTATION_ENV = "ROUTING_PROVIDER_EGRESS_ATTESTATION_JSON"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Secret-safe Kakao Routing Provider capability probe"
    )
    parser.add_argument("--live", action="store_true", help="spend one live Provider call")
    parser.add_argument("--operation", choices=probe_scope_names())
    args = parser.parse_args(argv)
    if args.live and args.operation is None:
        parser.error("--live requires exactly one --operation")
    if not args.live:
        print(json.dumps(_inventory(), ensure_ascii=False, sort_keys=True))
        return 0
    name = args.operation
    assert name is not None
    provider, operation = _scope(name)
    key_env = KAKAO_BASELINE_KEY_ENV[(provider, operation)]
    secret = _secret(os.environ.get(key_env), key_env)
    attestation = _attestation()
    endpoint = next(
        spec.url for spec in __import__("provider_core").ENDPOINT_SPECS
        if spec.provider == provider and spec.operation == operation
    )
    if endpoint is None:
        raise SystemExit("probe endpoint is unavailable")
    transport = build_strict_https_transport((endpoint,), attestation=attestation)
    result = probe_kakao_operation(
        name, transport=transport, credential=SensitiveValue(secret)
    )
    print(json.dumps(result.as_sanitized_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if result.state.value == "KEY_VERIFIED" else 2


def _inventory() -> dict[str, object]:
    operations = []
    for name in probe_scope_names():
        provider, operation = _scope(name)
        key_env = KAKAO_BASELINE_KEY_ENV[(provider, operation)]
        operations.append({
            "name": name,
            "provider": provider,
            "operation": operation,
            "keyEnvironmentVariable": key_env,
            "keyPresent": bool(os.environ.get(key_env)),
            "documentationState": "DOCUMENTED",
            "keyVerificationState": "UNVERIFIED",
            "productionState": "UNAPPROVED",
            "schemaVersion": KAKAO_BASELINE_SCHEMA_VERSIONS[(provider, operation)],
        })
    return {
        "live": False,
        "egressAttestationEnvironmentVariable": ATTESTATION_ENV,
        "operations": operations,
    }


def _scope(name: str) -> tuple[str, str]:
    mapping = {
        "transit": ("KAKAO_PUBLIC_TRANSIT", "search_current"),
        "walk": ("KAKAO_WALK", "route"),
        "directions": ("KAKAO_DIRECTIONS", "route_current"),
    }
    return mapping[name]


def _attestation() -> NetworkEgressAttestation:
    raw = os.environ.get(ATTESTATION_ENV)
    if not raw:
        raise SystemExit(f"{ATTESTATION_ENV} is required for --live")
    if len(raw.encode("utf-8")) > 8_192:
        raise SystemExit("egress attestation exceeds the size limit")
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {
            "evidenceId", "artifactSha256", "version", "issuedAt", "expiresAt", "enforcement"
        }:
            raise ValueError
        return NetworkEgressAttestation(
            evidence_id=_text(value["evidenceId"]),
            artifact_sha256=_text(value["artifactSha256"]),
            version=_text(value["version"]),
            issued_at=_time(value["issuedAt"]),
            expires_at=_time(value["expiresAt"]),
            enforcement=EgressEnforcement(value["enforcement"]),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        raise SystemExit("egress attestation is invalid") from None


def _secret(raw: str | None, name: str) -> str:
    if raw is None or not raw.strip() or len(raw) > 512 or any(
        ord(character) < 33 or ord(character) > 126 for character in raw
    ):
        raise SystemExit(f"{name} is missing or invalid")
    return raw


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError
    return value


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
