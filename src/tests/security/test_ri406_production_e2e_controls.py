"""RI-406 security gates for the production-shaped Service -> Routing path.

These tests deliberately stop at local source boundaries.  They prove fail-closed
assembly and operation scoping; they do not claim that a live credential, network
egress policy, Provider approval, or deployed TLS boundary exists.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import traceback
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from provider_core.capabilities import (
    Capability,
    CapabilityRegistry,
    DocumentationState,
    KeyVerificationState,
    ProductionState,
)
from provider_core.envelope import ProviderStatus
from provider_core.http import HttpRequest, HttpResponse, SensitiveValue
from provider_core.kakao_raw import KAKAO_PUBLIC_TRANSIT_SCHEMA_VERSION
from provider_core.named import (
    ProviderAdapterSuite,
    ProviderAdapterSuiteConfig,
    ProviderCall,
    ProviderOperationBinding,
    ScopedProviderCredential,
    ScopedProviderTransport,
)
from provider_core.resilience import Deadline, RetryPolicy
from provider_core.runtime import (
    ProviderRuntimeEvidenceConfig,
    RuntimeEvidence,
    RuntimeEvidenceKind,
)
from provider_core.production import (
    EVIDENCE_ENV,
    KAKAO_BASELINE_OPERATIONS,
    KAKAO_BASELINE_SCHEMA_VERSIONS,
    build_kakao_baseline_config,
)
from routing_api.production_composition import ProductionCompositionDependencies
from routing_deployment.bootstrap import (
    PRODUCTION_DEPENDENCIES_FACTORY_ENV,
    ProductionBootstrapError,
    bootstrap_from_environment,
    bootstrap_production_dependencies,
)


SRC_ROOT = Path(__file__).resolve().parents[2]
ROUTING_API_PACKAGE = SRC_ROOT / "services" / "routing-api" / "routing_api"
DATABASE_BOOTSTRAP_SCRIPT = (
    SRC_ROOT / "infra" / "docker" / "routing-api" / "database_bootstrap.py"
)
ROUTING_TERRAFORM = (
    SRC_ROOT / "infra" / "terraform" / "modules" / "routing-platform" / "main.tf"
)
DATABASE_BOOTSTRAP_WORKFLOW = (
    SRC_ROOT / "infra" / "ci" / "github-actions" / "bootstrap-routing-staging.yml"
)
NOW = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
PROVIDER = "KAKAO_PUBLIC_TRANSIT"
OPERATION = "search_current"
SECRET = "ri406-provider-secret-must-not-render"
PROBE_SCRIPT = SRC_ROOT / "scripts" / "probe_routing_providers.py"


def _terraform_resource(source: str, kind: str, name: str) -> str:
    marker = f'resource "{kind}" "{name}" {{'
    start = source.index(marker)
    end = source.find('\nresource "', start + len(marker))
    return source[start:] if end < 0 else source[start:end]


class RecordingUnavailableTransport:
    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return HttpResponse(503, "application/json", b"{}")


def _capabilities() -> CapabilityRegistry:
    return CapabilityRegistry(
        (
            Capability(
                PROVIDER,
                OPERATION,
                DocumentationState.DOCUMENTED,
                KeyVerificationState.KEY_VERIFIED,
                ProductionState.PRODUCTION_APPROVED,
                fixture_only=False,
            ),
        )
    )


def _evidence(*, schema_version: str) -> ProviderRuntimeEvidenceConfig:
    items = []
    for index, kind in enumerate(RuntimeEvidenceKind, start=1):
        version = (
            schema_version
            if kind is RuntimeEvidenceKind.RESPONSE_SCHEMA
            else f"ri406.{kind.value.lower()}.v1"
        )
        items.append(
            RuntimeEvidence(
                PROVIDER,
                OPERATION,
                kind,
                f"ri406-{kind.value.lower()}",
                f"{index:x}" * 64,
                version,
                NOW - timedelta(minutes=1),
                NOW + timedelta(minutes=5),
            )
        )
    return ProviderRuntimeEvidenceConfig(items)


def _config(
    transport: RecordingUnavailableTransport,
    *,
    schema_version: str,
) -> ProviderAdapterSuiteConfig:
    return ProviderAdapterSuiteConfig(
        bindings=(
            ProviderOperationBinding(
                ScopedProviderTransport(PROVIDER, OPERATION, transport),
                ScopedProviderCredential(
                    PROVIDER,
                    OPERATION,
                    SensitiveValue(SECRET),
                ),
            ),
        ),
        capabilities=_capabilities(),
        runtime_evidence=_evidence(schema_version=schema_version),
        clock=lambda: NOW,
        retry_policy=RetryPolicy(max_attempts=1, backoff_ms=()),
    )


def _production_evidence_document() -> dict[str, object]:
    capabilities = []
    runtime_evidence = []
    for provider, operation in KAKAO_BASELINE_OPERATIONS:
        capabilities.append(
            {
                "provider": provider,
                "operation": operation,
                "documentationState": "DOCUMENTED",
                "keyVerificationState": "KEY_VERIFIED",
                "productionState": "PRODUCTION_APPROVED",
                "fixtureOnly": False,
            }
        )
        for index, kind in enumerate(RuntimeEvidenceKind, start=1):
            runtime_evidence.append(
                {
                    "provider": provider,
                    "operation": operation,
                    "kind": kind.value,
                    "evidenceId": f"ri406-{provider.lower()}-{operation}-{kind.value.lower()}",
                    "artifactSha256": f"{index:x}" * 64,
                    "version": (
                        KAKAO_BASELINE_SCHEMA_VERSIONS[(provider, operation)]
                        if kind is RuntimeEvidenceKind.RESPONSE_SCHEMA
                        else f"ri406.{kind.value.lower()}.v1"
                    ),
                    "issuedAt": (NOW - timedelta(minutes=1)).isoformat(),
                    "expiresAt": (NOW + timedelta(minutes=5)).isoformat(),
                }
            )
    return {
        "version": "1.0",
        "capabilities": capabilities,
        "runtimeEvidence": runtime_evidence,
        "egressAttestation": {
            "evidenceId": "ri406-egress-policy",
            "artifactSha256": "a" * 64,
            "version": "ri406-egress-v1",
            "issuedAt": (NOW - timedelta(minutes=1)).isoformat(),
            "expiresAt": (NOW + timedelta(minutes=5)).isoformat(),
            "enforcement": "EXTERNAL_PROXY_OR_FIREWALL",
        },
    }


def _production_environment(document: dict[str, object]) -> dict[str, str]:
    return {
        "KAKAO_REST_API_KEY": "ri406-rest-secret",
        EVIDENCE_ENV: json.dumps(document),
    }


def test_ordinary_routing_api_modules_do_not_import_deployment_composition_root() -> None:
    offenders: list[str] = []
    for path in ROUTING_API_PACKAGE.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = (node.module or "",)
            else:
                continue
            if any(name == "routing_deployment" or name.startswith("routing_deployment.") for name in names):
                offenders.append(str(path.relative_to(ROUTING_API_PACKAGE.parent)))
    assert offenders == []


def test_bootstrap_absence_and_factory_failures_are_fail_closed_and_sanitized() -> None:
    assert bootstrap_from_environment({}) is None

    secret = "postgres://user:startup-secret@db.internal/routing"

    def failing_factory() -> ProductionCompositionDependencies:
        raise RuntimeError(secret)

    with pytest.raises(ProductionBootstrapError) as captured:
        bootstrap_production_dependencies(failing_factory)
    rendered = "".join(
        traceback.TracebackException.from_exception(captured.value).format(chain=True)
    )
    assert secret not in rendered
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True

    class ForgedDependencies(ProductionCompositionDependencies):
        pass

    with pytest.raises(ProductionBootstrapError, match="invalid boundary object"):
        bootstrap_production_dependencies(ForgedDependencies)

    with pytest.raises(ProductionBootstrapError, match="dotted.module:callable"):
        bootstrap_from_environment(
            {PRODUCTION_DEPENDENCIES_FACTORY_ENV: "attacker.invalid:factory:extra"}
        )


def test_wsgi_import_fails_startup_without_rendering_factory_identifier() -> None:
    factory_sentinel = "ri406_secret_factory_identifier"
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join(
                str(SRC_ROOT / relative)
                for relative in (
                    "services/routing-api",
                    "packages/provider-core",
                    "packages/routing-domain",
                    "packages/bus-intelligence-core",
                )
            ),
            "DJANGO_SETTINGS_MODULE": "routing_api.settings",
            "ROUTING_RUNTIME_ENVIRONMENT": "TEST",
            PRODUCTION_DEPENDENCIES_FACTORY_ENV: (
                f"{factory_sentinel}.module:build"
            ),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "import routing_deployment.wsgi"],
        cwd=SRC_ROOT.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    rendered = result.stdout + result.stderr
    assert "production dependency factory could not be loaded" in rendered
    assert factory_sentinel not in rendered


def test_schema_evidence_mismatch_stops_before_transport_and_exact_match_is_scoped() -> None:
    mismatch_transport = RecordingUnavailableTransport()
    mismatched = ProviderAdapterSuite.from_config(
        _config(mismatch_transport, schema_version="kakao.public-transit.wrong.v1")
    )
    disabled = mismatched.kakao_transit.invoke(
        OPERATION,
        ProviderCall("ri406-mismatched-evidence"),
        deadline=Deadline.after_ms(100),
    )
    assert disabled.status is ProviderStatus.DISABLED
    assert mismatch_transport.requests == []

    transport = RecordingUnavailableTransport()
    suite = ProviderAdapterSuite.from_config(
        _config(transport, schema_version=KAKAO_PUBLIC_TRANSIT_SCHEMA_VERSION)
    )
    unavailable = suite.kakao_transit.invoke(
        OPERATION,
        ProviderCall(
            "ri406-exact-evidence",
            query=(("start_x", 127.1), ("start_y", 37.2)),
        ),
        deadline=Deadline.after_ms(100),
    )
    assert unavailable.status is ProviderStatus.UNAVAILABLE
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url == "https://dapi.kakao.com/v2/routing/publictraffic"
    assert request.method == "GET"
    assert request.timeout_ms <= 1_800
    assert request.maximum_response_bytes == 1_000_000
    rendered = repr(request)
    summary = request.safe_summary()
    assert SECRET not in rendered
    assert SECRET not in repr(summary)
    assert "127.1" not in repr(summary)
    assert summary["headers"]["Authorization"] == "***"


def test_transport_and_credential_operation_scopes_cannot_be_cross_wired() -> None:
    transport = RecordingUnavailableTransport()
    with pytest.raises(ValueError, match="scopes must match exactly"):
        ProviderOperationBinding(
            ScopedProviderTransport(PROVIDER, OPERATION, transport),
            ScopedProviderCredential(
                "KAKAO_WALK",
                "route",
                SensitiveValue(SECRET),
            ),
        )


def test_production_evidence_bundle_is_exact_and_mismatches_fail_before_transport() -> None:
    document = _production_evidence_document()
    with pytest.MonkeyPatch.context() as monkeypatch:
        for key, value in _production_environment(document).items():
            monkeypatch.setenv(key, value)
        config = build_kakao_baseline_config()
    assert set(config.binding_map) == set(KAKAO_BASELINE_OPERATIONS)
    assert all(capability.enabled for capability in config.capabilities.all())
    rendered = repr(config)
    assert "ri406-rest-secret" not in rendered
    assert "ri406-mobility-secret" not in rendered

    wrong_scope = deepcopy(document)
    wrong_scope["capabilities"][0]["provider"] = "KAKAO_WALK"  # type: ignore[index]
    wrong_schema = deepcopy(document)
    schema_item = next(
        item
        for item in wrong_schema["runtimeEvidence"]  # type: ignore[union-attr]
        if item["kind"] == "RESPONSE_SCHEMA"  # type: ignore[index]
    )
    schema_item["version"] = "forged-schema-version"  # type: ignore[index]
    wrong_egress = deepcopy(document)
    wrong_egress["egressAttestation"]["enforcement"] = "PROCESS_ASSERTION"  # type: ignore[index]

    for invalid in (wrong_scope, wrong_schema, wrong_egress):
        with pytest.MonkeyPatch.context() as monkeypatch:
            for key, value in _production_environment(invalid).items():
                monkeypatch.setenv(key, value)
            with pytest.raises(ValueError):
                build_kakao_baseline_config()


def test_probe_inventory_reports_presence_only_and_never_prints_key_or_raw_payload() -> None:
    environment = os.environ.copy()
    secret = "ri406-probe-secret-never-print"
    environment.update(
        {
            "KAKAO_REST_API_KEY": secret,
        }
    )
    result = subprocess.run(
        [sys.executable, str(PROBE_SCRIPT)],
        cwd=SRC_ROOT.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert "rawPayload" not in result.stdout
    assert "rawResponse" not in result.stdout
    inventory = json.loads(result.stdout)
    assert inventory["live"] is False
    assert len(inventory["operations"]) == 3
    assert all(item["keyPresent"] is True for item in inventory["operations"])
    assert all(
        item["keyVerificationState"] == "UNVERIFIED"
        and item["productionState"] == "UNAPPROVED"
        for item in inventory["operations"]
    )


def test_database_bootstrap_binds_role_passwords_instead_of_composing_sql() -> None:
    source = DATABASE_BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    assert "sql.Literal(role_password)" not in source
    assert "WITH LOGIN PASSWORD %s" in source
    assert "(role_password,)" in source


def test_master_secret_and_deploy_authority_are_confined_to_database_bootstrap() -> None:
    source = ROUTING_TERRAFORM.read_text(encoding="utf-8")
    runtime_policy = _terraform_resource(
        source, "aws_iam_role_policy", "execution_secrets"
    )
    migration_policy = _terraform_resource(
        source, "aws_iam_role_policy", "migration_execution_secrets"
    )
    bootstrap_policy = _terraform_resource(
        source, "aws_iam_role_policy", "database_bootstrap_execution_secrets"
    )
    online_task = _terraform_resource(source, "aws_ecs_task_definition", "routing")
    bootstrap_task = _terraform_resource(
        source, "aws_ecs_task_definition", "database_bootstrap"
    )
    migration_task = _terraform_resource(
        source, "aws_ecs_task_definition", "migration"
    )
    deploy_policy = _terraform_resource(
        source, "aws_iam_role_policy", "github_deploy"
    )
    database_deploy_policy = _terraform_resource(
        source, "aws_iam_role_policy", "github_database_bootstrap"
    )

    master_secret = "aws_db_instance.routing.master_user_secret[0].secret_arn"
    assert master_secret not in runtime_policy
    assert master_secret not in migration_policy
    assert master_secret in bootstrap_policy
    assert master_secret not in online_task
    assert master_secret not in migration_task
    assert master_secret in bootstrap_task

    assert "aws_iam_role.execution.arn" in online_task
    assert "aws_iam_role.database_bootstrap_execution.arn" in bootstrap_task
    assert "aws_iam_role.migration_execution.arn" in migration_task
    assert "aws_secretsmanager_secret.migration_django.arn" in migration_task
    assert "aws_secretsmanager_secret.migration_jwt.arn" in migration_task
    assert "var.shared_jwt_secret_arn" not in migration_task

    assert "ecs:RegisterTaskDefinition" not in deploy_policy
    assert "ecs:RunTask" not in deploy_policy
    assert "iam:PassRole" not in deploy_policy
    assert 'Action   = ["ecs:UpdateService"]' in deploy_policy
    assert "local.routing_service_arn" in deploy_policy
    assert "local.ecs_cluster_arn" in deploy_policy
    assert "local.routing_task_definition_arn" in deploy_policy
    assert '"ecs:auto-assign-public-ip"  = "DISABLED"' in deploy_policy
    assert '"ecs:enable-execute-command" = "false"' in deploy_policy
    assert 'Null = { "ecs:subnet" = "false" }' in deploy_policy

    assert "ecs:RegisterTaskDefinition" not in database_deploy_policy
    assert 'Action = ["ecs:RunTask"]' in database_deploy_policy
    assert "local.bootstrap_task_definition_arn" in database_deploy_policy
    assert "local.migration_task_definition_arn" in database_deploy_policy
    assert "local.ecs_cluster_arn" in database_deploy_policy
    assert '"ecs:auto-assign-public-ip"  = "DISABLED"' in database_deploy_policy
    assert '"ecs:enable-execute-command" = "false"' in database_deploy_policy
    assert 'Null = { "ecs:subnet" = "false" }' in database_deploy_policy
    assert "aws_iam_role.database_bootstrap_execution.arn" in database_deploy_policy
    assert "aws_iam_role.migration_execution.arn" in database_deploy_policy
    assert "aws_iam_role.execution.arn" not in database_deploy_policy


def test_database_bootstrap_workflow_is_protected_and_uses_immutable_tasks() -> None:
    source = DATABASE_BOOTSTRAP_WORKFLOW.read_text(encoding="utf-8")
    assert "environment: staging-routing-database" in source
    assert "BOOTSTRAP-ROUTING-STAGING" in source
    assert "@sha256:[0-9a-f]{64}$" in source
    assert "assignPublicIp=DISABLED" in source
    assert "aws ecs register-task-definition" not in source
