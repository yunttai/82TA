#!/usr/bin/env python3
"""Probe the Docker Kakao baseline and emit short-lived, secret-free evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
PROVIDER_ROOT = ROOT / "src" / "packages" / "provider-core"
sys.path.insert(0, str(PROVIDER_ROOT))

from provider_core import (  # noqa: E402
    ENDPOINT_SPECS,
    KAKAO_BASELINE_KEY_ENV,
    KAKAO_BASELINE_OPERATIONS,
    KAKAO_BASELINE_SCHEMA_VERSIONS,
    NetworkEgressAttestation,
    PROVIDER_HTTPS_PROXY_ENV,
    ProbeState,
    RuntimeEvidenceKind,
    SensitiveValue,
    build_strict_https_transport,
    probe_kakao_operation,
)
from provider_core.transport import EgressEnforcement  # noqa: E402


DEFAULT_ENV_FILE = ROOT / "src" / "services" / "routing-api" / ".env.local"
DEFAULT_OUTPUT = (
    ROOT
    / "src"
    / "services"
    / "routing-api"
    / ".env.routing-live.generated"
)
DEFAULT_APPROVAL = (
    ROOT
    / "src"
    / "services"
    / "routing-api"
    / ".routing-live-approval.json"
)
_SCOPES = {
    "transit": ("KAKAO_PUBLIC_TRANSIT", "search_current"),
    "walk": ("KAKAO_WALK", "route"),
    "directions": ("KAKAO_DIRECTIONS", "route_current"),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate short-lived local Docker Routing Provider evidence"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--output-env-file", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--approval-artifact", type=Path, default=DEFAULT_APPROVAL)
    parser.add_argument("--proxy-url", default="http://127.0.0.1:13128")
    parser.add_argument("--ttl-minutes", type=int, default=120)
    parser.add_argument(
        "--approve-local-provider-use",
        action="store_true",
        help=(
            "acknowledge terms/quota and authorize exactly three bounded local "
            "Provider probe calls; this is not release approval"
        ),
    )
    return parser


def _read_env_file(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64_000:
        raise ValueError("local Provider env file is unavailable or invalid")
    expected = frozenset(KAKAO_BASELINE_KEY_ENV.values())
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if separator != "=" or name not in expected:
            continue
        if name in values:
            raise ValueError("local Provider env file contains a duplicate key")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if (
            not value
            or len(value) > 512
            or any(ord(character) < 33 or ord(character) > 126 for character in value)
        ):
            raise ValueError("local Provider env file contains an invalid key")
        values[name] = value
    missing = sorted(expected - values.keys())
    if missing:
        raise ValueError("required local Kakao Provider keys are missing")
    return values


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def _file_bundle_hash(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ValueError("generated local evidence target must not be a symlink")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            os.chmod(temporary_name, 0o600)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    except OSError:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise ValueError("unable to write generated local evidence") from None


def _approval_document(
    *, issued_at: datetime, expires_at: datetime, egress_hash: str
) -> dict[str, object]:
    return {
        "version": "local-docker-provider-approval-v1",
        "scope": "bounded-local-docker-live-e2e",
        "operations": [
            {"provider": provider, "operation": operation}
            for provider, operation in KAKAO_BASELINE_OPERATIONS
        ],
        "maximumProbeCalls": len(KAKAO_BASELINE_OPERATIONS),
        "releaseApproval": False,
        "issuedAt": _iso(issued_at),
        "expiresAt": _iso(expires_at),
        "egressArtifactSha256": egress_hash,
    }


def _evidence_document(
    *,
    probes: Mapping[tuple[str, str], Any],
    issued_at: datetime,
    expires_at: datetime,
    approval_hash: str,
    egress_hash: str,
) -> dict[str, object]:
    capabilities = []
    runtime = []
    for provider, operation in KAKAO_BASELINE_OPERATIONS:
        probe = probes[(provider, operation)]
        if probe.state is not ProbeState.KEY_VERIFIED:
            raise ValueError("a local Provider probe did not verify its key and schema")
        capabilities.append(
            {
                "provider": provider,
                "operation": operation,
                "documentationState": "DOCUMENTED",
                "keyVerificationState": "KEY_VERIFIED",
                # This approval is short-lived and dev-scoped; the generated
                # approval artifact explicitly denies release approval.
                "productionState": "PRODUCTION_APPROVED",
                "fixtureOnly": False,
            }
        )
        for kind in RuntimeEvidenceKind:
            if kind is RuntimeEvidenceKind.KEY_VERIFICATION:
                artifact_hash = probe.artifact_sha256
                version = "fixed-probe-v1"
            elif kind is RuntimeEvidenceKind.RESPONSE_SCHEMA:
                artifact_hash = probe.artifact_sha256
                version = KAKAO_BASELINE_SCHEMA_VERSIONS[(provider, operation)]
            else:
                artifact_hash = approval_hash
                version = "local-docker-provider-approval-v1"
            runtime.append(
                {
                    "provider": provider,
                    "operation": operation,
                    "kind": kind.value,
                    "evidenceId": (
                        f"local-{provider.lower()}-{operation.lower()}-"
                        f"{kind.value.lower()}"
                    ),
                    "artifactSha256": artifact_hash,
                    "version": version,
                    "issuedAt": _iso(issued_at),
                    "expiresAt": _iso(expires_at),
                }
            )
    return {
        "version": "1.0",
        "capabilities": capabilities,
        "runtimeEvidence": runtime,
        "egressAttestation": {
            "evidenceId": "local-docker-exact-connect-proxy",
            "artifactSha256": egress_hash,
            "version": "routing-live-proxy-v1",
            "issuedAt": _iso(issued_at),
            "expiresAt": _iso(expires_at),
            "enforcement": "EXTERNAL_PROXY_OR_FIREWALL",
        },
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.approve_local_provider_use:
        raise SystemExit("--approve-local-provider-use is required")
    if not 5 <= arguments.ttl_minutes <= 240:
        raise SystemExit("--ttl-minutes must be between 5 and 240")

    stage = "env"
    probes: dict[tuple[str, str], Any] = {}
    try:
        keys = _read_env_file(arguments.env_file.resolve(strict=True))
        stage = "egress-evidence"
        now = datetime.now(timezone.utc)
        issued_at = now - timedelta(seconds=5)
        expires_at = now + timedelta(minutes=arguments.ttl_minutes)
        egress_hash = _file_bundle_hash(
            (
                ROOT / "src" / "infra" / "docker" / "compose.routing-live.yml",
                ROOT
                / "src"
                / "infra"
                / "docker"
                / "provider-egress-proxy"
                / "Dockerfile",
                ROOT
                / "src"
                / "infra"
                / "docker"
                / "provider-egress-proxy"
                / "egress_proxy.py",
            )
        )
        approval = _approval_document(
            issued_at=issued_at,
            expires_at=expires_at,
            egress_hash=egress_hash,
        )
        approval_hash = _canonical_hash(approval)
        attestation = NetworkEgressAttestation(
            evidence_id="local-docker-exact-connect-proxy",
            artifact_sha256=egress_hash,
            version="routing-live-proxy-v1",
            issued_at=issued_at,
            expires_at=expires_at,
            enforcement=EgressEnforcement.EXTERNAL_PROXY_OR_FIREWALL,
        )
        endpoints = tuple(
            spec.url
            for spec in ENDPOINT_SPECS
            if (spec.provider, spec.operation) in KAKAO_BASELINE_OPERATIONS
            and spec.url is not None
        )
        stage = "proxy-transport"
        transport = build_strict_https_transport(
            endpoints,
            attestation=attestation,
            environment={PROVIDER_HTTPS_PROXY_ENV: arguments.proxy_url},
        )
        for name, scope in _SCOPES.items():
            stage = f"probe-{name}"
            key_name = KAKAO_BASELINE_KEY_ENV[scope]
            probes[scope] = probe_kakao_operation(
                name,
                transport=transport,
                credential=SensitiveValue(keys[key_name]),
            )
        stage = "evidence-bundle"
        evidence = _evidence_document(
            probes=probes,
            issued_at=issued_at,
            expires_at=expires_at,
            approval_hash=approval_hash,
            egress_hash=egress_hash,
        )
        rendered_evidence = json.dumps(
            evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        stage = "write-approval"
        _atomic_write(
            arguments.approval_artifact.resolve(),
            json.dumps(approval, indent=2, sort_keys=True) + "\n",
        )
        stage = "write-environment"
        _atomic_write(
            arguments.output_env_file.resolve(),
            f"ROUTING_PROVIDER_EVIDENCE_JSON={rendered_evidence}\n",
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "stage": stage,
                    "probes": [
                        value.as_sanitized_dict() for value in probes.values()
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:
        # Provider transport/parser exceptions remain deliberately opaque here; raw
        # response, endpoint internals, and credentials must not cross the CLI.
        print(
            json.dumps(
                {"status": "FAILED", "stage": stage, "probes": []},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3

    print(
        json.dumps(
            {
                "expiresAt": _iso(expires_at),
                "outputEnvFile": str(arguments.output_env_file.resolve()),
                "approvalArtifact": str(arguments.approval_artifact.resolve()),
                "secretValuesWritten": False,
                "probes": [
                    probes[scope].as_sanitized_dict()
                    for scope in KAKAO_BASELINE_OPERATIONS
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
