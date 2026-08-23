from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INFRA = ROOT / "src" / "infra"


class InfrastructureContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (INFRA / relative).read_text(encoding="utf-8")

    def test_src_docker_context_excludes_generated_runtime_debris(self) -> None:
        dockerignore = (ROOT / "src" / ".dockerignore").read_text(encoding="utf-8")
        for excluded in (
            "**/__pycache__/",
            "**/.pytest_cache/",
            "**/.venv/",
            "**/node_modules/",
            "**/.terraform/",
            "**/terraform.tfstate",
            "**/*.py[cod]",
            "**/.env.*",
        ):
            self.assertIn(excluded, dockerignore)
        self.assertIn("!**/.env.example", dockerignore)
        for required in ("contracts/", "generated/", "**/migrations/"):
            self.assertNotIn(required, dockerignore)

    def test_service_and_web_images_are_multistage_non_root(self) -> None:
        for relative in ("docker/service-api/Dockerfile", "docker/web/Dockerfile"):
            dockerfile = self.read(relative)
            self.assertGreaterEqual(dockerfile.count("FROM "), 2)
            self.assertIn("USER ", dockerfile)
            self.assertIn("HEALTHCHECK", dockerfile)

    def test_routing_image_bootstraps_before_wsgi_and_is_non_root(self) -> None:
        dockerfile = self.read("docker/routing-api/Dockerfile")
        entrypoint = self.read("docker/routing-api/runtime_entrypoint.py")
        self.assertGreaterEqual(dockerfile.count("FROM "), 2)
        self.assertIn("USER 10002:10002", dockerfile)
        self.assertIn("routing_deployment.wsgi:application", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("ROUTING_ALLOW_FIXTURE_BACKEND", entrypoint)
        self.assertNotIn("print(", entrypoint)

    def test_routing_e2e_keeps_browser_on_service_http_boundary(self) -> None:
        compose = self.read("docker/compose.routing-e2e.yml")
        self.assertIn("SERVICE_ROUTING_GATEWAY: http", compose)
        self.assertIn("SERVICE_ROUTING_API_BASE_URL: http://routing-api:8000", compose)
        self.assertIn("routing_deployment.wsgi:application", compose)
        self.assertIn("ROUTING_ALLOW_FIXTURE_BACKEND: \"false\"", compose)
        self.assertIn(
            "ROUTING_PRODUCTION_DEPENDENCIES_FACTORY: ${ROUTING_PRODUCTION_DEPENDENCIES_FACTORY:-}",
            compose,
        )
        self.assertNotIn(
            "${ROUTING_PRODUCTION_DEPENDENCIES_FACTORY:-routing_deployment.baseline:build_dependencies}",
            compose,
        )
        self.assertIn("KAKAO_REST_API_KEY: ${KAKAO_REST_API_KEY:-}", compose)
        for key in (
            "KAKAO_JS_API_KEY",
            "GBIS_SERVICE_KEY",
            "GITS_API_KEY",
            "TMAP_APP_KEY",
            "ODSAY_API_KEY",
        ):
            self.assertIn(key, compose)
        for legacy_key in (
            "KAKAO_LOCAL_REST_KEY",
            "KAKAO_MOBILITY_REST_API_KEY",
            "KMA_SERVICE_KEY",
            "VITE_KAKAO_MAP_APP_KEY",
        ):
            self.assertNotIn(legacy_key, compose)
        routing_block = compose.split("  routing-api:", 1)[1].split("  service-api:", 1)[0]
        self.assertNotIn("ports:", routing_block)

    def test_routing_live_overlay_enforces_exact_proxy_and_dev_provenance(self) -> None:
        overlay = self.read("docker/compose.routing-live.yml")
        proxy = self.read("docker/provider-egress-proxy/egress_proxy.py")
        dockerfile = self.read("docker/provider-egress-proxy/Dockerfile")
        self.assertIn("ROUTING_RUNTIME_ENVIRONMENT: DEVELOPMENT", overlay)
        self.assertIn('ROUTING_LOCAL_LIVE_E2E: "true"', overlay)
        self.assertIn(
            "ROUTING_PRODUCTION_DEPENDENCIES_FACTORY: routing_deployment.baseline:build_dependencies",
            overlay,
        )
        self.assertIn("ROUTING_PROVIDER_HTTPS_PROXY_URL: http://routing-egress-proxy:3128", overlay)
        self.assertIn("routing-private:\n    internal: true", overlay)
        self.assertIn("dapi.kakao.com,apis-navi.kakaomobility.com", overlay)
        self.assertIn("cap_drop: [ALL]", overlay)
        self.assertIn("read_only: true", overlay)
        self.assertIn("USER 65534:65534", dockerfile)
        self.assertIn('fields[0] != "CONNECT"', proxy)
        self.assertIn('port != "443"', proxy)
        self.assertIn("ipaddress.ip_address(value).is_global", proxy)
        self.assertNotIn("print(", proxy)

    def test_routing_terraform_is_private_and_fail_closed(self) -> None:
        routing = self.read("terraform/modules/routing-platform/main.tf")
        staging = self.read("terraform/environments/staging/main.tf")
        self.assertIn('internal                   = true', routing)
        self.assertIn("referenced_security_group_id = var.service_security_group_id", routing)
        self.assertIn("provider_firewall_endpoint_ids", routing)
        self.assertIn("vpc_endpoint_id = var.provider_firewall_endpoint_ids", routing)
        self.assertIn("routing_return_through_firewall", routing)
        self.assertIn("ROUTING_PROVIDER_EVIDENCE_JSON", routing)
        self.assertIn("ROUTING_PRODUCTION_DEPENDENCIES_FACTORY", routing)
        self.assertIn("routing_deployment.wsgi:application", routing)
        self.assertIn('ROUTING_ALLOW_FIXTURE_BACKEND", value = "false"', routing)
        self.assertRegex(routing, r"publicly_accessible\s*=\s*false")
        self.assertIn('transit_encryption_enabled = true', routing)
        self.assertIn('module "routing_intelligence"', staging)
        self.assertIn("service_routing_deployment_coherence", staging)

    def test_routing_deployment_entrypoint_fails_without_secret_values(self) -> None:
        launcher = INFRA / "docker" / "routing-api" / "runtime_entrypoint.py"
        env = os.environ.copy()
        for key in tuple(env):
            if key.startswith("ROUTING_"):
                del env[key]
        env["ROUTING_RUNTIME_ENVIRONMENT"] = "PRODUCTION"
        result = subprocess.run(
            [sys.executable, str(launcher), sys.executable, "-c", "raise SystemExit(99)"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required Routing deployment inputs are missing", result.stderr)

    def test_routing_database_bootstrap_is_separate_and_secret_safe(self) -> None:
        launcher = INFRA / "docker" / "routing-api" / "runtime_entrypoint.py"
        bootstrap = self.read("docker/routing-api/database_bootstrap.py")
        terraform = self.read("terraform/modules/routing-platform/main.tf")
        workflow = self.read("ci/github-actions/bootstrap-routing-staging.yml")
        self.assertIn('CREATE EXTENSION IF NOT EXISTS postgis', bootstrap)
        self.assertIn('_APPLICATION_ROLE = "routing_app"', bootstrap)
        self.assertIn('_MIGRATION_ROLE = "routing_migrator"', bootstrap)
        self.assertIn("pg_advisory_lock", bootstrap)
        self.assertIn("NOSUPERUSER", bootstrap)
        self.assertIn("NOLOGIN", bootstrap)
        self.assertIn("WITH LOGIN PASSWORD %s", bootstrap)
        self.assertIn("(role_password,)", bootstrap)
        self.assertNotIn("sql.Literal", bootstrap)
        self.assertNotIn("print(", bootstrap)
        self.assertIn('resource "aws_ecs_task_definition" "database_bootstrap"', terraform)
        self.assertIn('resource "aws_ecs_task_definition" "migration"', terraform)
        self.assertIn(
            "execution_role_arn       = aws_iam_role.database_bootstrap_execution.arn",
            terraform,
        )
        self.assertIn(
            "execution_role_arn       = aws_iam_role.migration_execution.arn",
            terraform,
        )
        migration_task = terraform.split(
            'resource "aws_ecs_task_definition" "migration"', 1
        )[1].split('resource "aws_ecs_service" "routing"', 1)[0]
        self.assertIn("aws_secretsmanager_secret.migration_django.arn", migration_task)
        self.assertIn("aws_secretsmanager_secret.migration_jwt.arn", migration_task)
        self.assertNotIn("var.shared_jwt_secret_arn", migration_task)
        self.assertNotIn("aws_secretsmanager_secret.django.arn", migration_task)
        self.assertIn(':username::', terraform)
        self.assertIn(':password::', terraform)
        self.assertNotIn('aws_secretsmanager_secret_version', terraform)
        self.assertIn("environment: staging-routing-database", workflow)
        self.assertIn("ROUTING_AWS_DATABASE_BOOTSTRAP_ROLE_ARN", workflow)
        self.assertLess(
            workflow.index("Run least-privilege role and PostGIS bootstrap"),
            workflow.index("Run Routing-owned migrations as routing_migrator"),
        )
        self.assertLess(
            workflow.index("Run Routing-owned migrations as routing_migrator"),
            workflow.index("Finalize runtime grants and revoke migrator schema creation"),
        )

        env = os.environ.copy()
        for key in tuple(env):
            if key.startswith("ROUTING_"):
                del env[key]
        env["ROUTING_TASK_MODE"] = "database-bootstrap"
        result = subprocess.run(
            [sys.executable, str(launcher), sys.executable, "-c", "raise SystemExit(99)"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required Routing database bootstrap inputs are missing", result.stderr)

    def test_routing_github_roles_cannot_mutate_unrelated_ecs_resources(self) -> None:
        terraform = self.read("terraform/modules/routing-platform/main.tf")
        deploy_policy = terraform.split(
            'resource "aws_iam_role_policy" "github_deploy"', 1
        )[1].split('resource "aws_iam_role" "github_database_bootstrap"', 1)[0]
        database_policy = terraform.split(
            'resource "aws_iam_role_policy" "github_database_bootstrap"', 1
        )[1]

        self.assertNotIn('"ecs:RegisterTaskDefinition"', terraform)
        self.assertNotIn('"ecs:RunTask"', deploy_policy)
        self.assertNotIn('"iam:PassRole"', deploy_policy)
        self.assertIn("Resource = local.routing_service_arn", deploy_policy)
        self.assertIn('"ecs:task-definition" = local.routing_task_definition_arn', deploy_policy)
        self.assertIn('"ecs:auto-assign-public-ip"  = "DISABLED"', deploy_policy)
        self.assertIn('"ecs:enable-execute-command" = "false"', deploy_policy)
        self.assertEqual(deploy_policy.count('Resource = "*"'), 2)

        self.assertIn('Action = ["ecs:RunTask"]', database_policy)
        self.assertIn("local.bootstrap_task_definition_arn", database_policy)
        self.assertIn("local.migration_task_definition_arn", database_policy)
        self.assertIn('"ecs:cluster" = local.ecs_cluster_arn', database_policy)
        self.assertIn('"ecs:subnet" = aws_subnet.routing[*].id', database_policy)
        self.assertIn('"ecs:auto-assign-public-ip"  = "DISABLED"', database_policy)
        self.assertIn('"ecs:enable-execute-command" = "false"', database_policy)
        self.assertIn('Null = { "ecs:subnet" = "false" }', database_policy)
        self.assertIn("Resource = local.routing_task_arn", database_policy)
        self.assertIn("aws_iam_role.database_bootstrap_execution.arn", database_policy)
        self.assertIn("aws_iam_role.migration_execution.arn", database_policy)
        self.assertNotIn("aws_iam_role.execution.arn", database_policy)
        self.assertNotIn("aws_iam_role.task.arn", database_policy)
        self.assertIn('"iam:PassedToService" = "ecs-tasks.amazonaws.com"', database_policy)
        self.assertEqual(database_policy.count('Resource = "*"'), 1)

    def test_routing_operational_alarms_fail_closed_on_missing_metrics(self) -> None:
        terraform = self.read("terraform/modules/routing-platform/main.tf")
        for metric in (
            "TargetResponseTime",
            "DeadlineExceededCount",
            "ProviderRateLimitedCount",
            "PartialResponseRate",
            "ProviderQuotaUtilization",
            "ProviderCostUsd",
        ):
            self.assertIn(metric, terraform)
        self.assertIn('"cloudwatch:PutMetricData"', terraform)
        self.assertIn('"cloudwatch:namespace" = "82TA/Routing"', terraform)
        custom_alarm_tail = terraform.split(
            'resource "aws_cloudwatch_metric_alarm" "routing_deadline_exhausted"', 1
        )[1]
        self.assertGreaterEqual(custom_alarm_tail.count('treat_missing_data  = "breaching"'), 5)

    def test_browser_never_targets_routing(self) -> None:
        compose = self.read("docker/compose.service-product.yml")
        nginx = self.read("docker/web/default.conf.template")
        self.assertNotIn("routing-api", compose)
        self.assertNotIn("/v1/routes/optimize", nginx)
        self.assertIn("proxy_pass http://${SERVICE_UPSTREAM}", nginx)

    def test_exact_coordinate_request_lines_are_not_logged(self) -> None:
        marker = "127.123456,37.654321"
        nginx = self.read("docker/web/default.conf.template")
        service_dockerfile = self.read("docker/service-api/Dockerfile")
        compose = self.read("docker/compose.service-product.yml")
        terraform = self.read("terraform/modules/service-platform/main.tf")
        self.assertIn("location /api/", nginx)
        self.assertIn("access_log off", nginx)
        self.assertIn('--access-logfile", "/dev/null"', service_dockerfile)
        self.assertIn('"python", "-m", "gunicorn"', service_dockerfile)
        self.assertIn("--access-logfile /dev/null", compose)
        self.assertNotIn("access_logs {", terraform)
        self.assertIn("redacted_fields {", terraform)
        self.assertIn("query_string {}", terraform)
        self.assertIn('single_header { name = "x-guest-token" }', terraform)
        self.assertIn('single_header { name = "x-csrftoken" }', terraform)
        self.assertNotIn("sampled_requests_enabled   = true", terraform)
        self.assertNotIn(marker, nginx + service_dockerfile + compose + terraform)

    def test_task_has_database_routing_proxy_and_ephemeral_controls(self) -> None:
        terraform = self.read("terraform/modules/service-platform/main.tf")
        entrypoint = self.read("docker/service-api/runtime_entrypoint.py")
        for expected in (
            "SERVICE_DATABASE_PASSWORD",
            "SERVICE_ROUTING_API_ALLOWED_HOSTS",
            "SERVICE_ROUTING_JWT_SECRET",
            "SERVICE_ROUTING_JWT_ISSUER",
            "SERVICE_ROUTING_JWT_AUDIENCE",
            "SERVICE_ROUTING_JWT_TTL_SECONDS",
            "SERVICE_PUBLIC_ROUTE_SEARCH_BUDGET_MILLISECONDS",
            "SERVICE_ROUTING_DEADLINE_MILLISECONDS",
            "SERVICE_TRUST_PROXY_HEADERS",
            "SERVICE_TRUSTED_PROXY_IPS",
            "SERVICE_CSRF_TRUSTED_ORIGINS",
            "SERVICE_CONSENT_DOCUMENT_VERSION",
            "SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND",
            "SERVICE_DATA_RIGHTS_ARTIFACT_DIRECTORY",
            "SERVICE_DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY",
            "SERVICE_REDIS_KEY_PREFIX",
            "SERVICE_REDIS_SOCKET_TIMEOUT_SECONDS",
            "SERVICE_RATE_LIMIT_CACHE_TTL_SECONDS",
            "SERVICE_IDEMPOTENCY_CACHE_TTL_SECONDS",
            "SERVICE_IDEMPOTENCY_LEASE_SECONDS",
            "readonlyRootFilesystem = true",
            'containerPath = "/tmp"',
            "aws_lb.service.dns_name",
            'path                = "/infra/healthz"',
            'origin_protocol_policy = "https-only"',
            "alb_origin_domain_name",
            "plaintext CloudFront-to-ALB is forbidden",
            'resource "aws_route53_record" "alb_origin"',
            'command = ["python", "manage.py", "process_data_rights_jobs", "--limit", "100"]',
            'command = ["python", "manage.py", "purge_service_data"]',
            'transit_encryption = "ENABLED"',
            'iam             = "ENABLED"',
            'backup_policy { status = "DISABLED" }',
        ):
            self.assertIn(expected, terraform)
        self.assertIn('os.environ["DATABASE_URL"] = generated_url', entrypoint)
        self.assertIn("?sslmode=require", entrypoint)
        self.assertNotIn('value = "1000000"', terraform)
        self.assertIn('value = "rediss://${aws_elasticache_replication_group.service.primary_endpoint_address}:6379/0"', terraform)
        self.assertIn("transit_encryption_enabled = true", terraform)
        self.assertNotIn("SERVICE_ROUTING_SERVICE_TOKEN", terraform)

    def test_application_rate_limits_are_bounded_and_configurable(self) -> None:
        variables = self.read("terraform/modules/service-platform/variables.tf")
        terraform = self.read("terraform/modules/service-platform/main.tf")
        expected = {
            "SERVICE_RATE_LIMIT_PER_MINUTE": "var.service_rate_limit_per_minute",
            "SERVICE_GUEST_SESSION_RATE_LIMIT_PER_MINUTE": "var.service_guest_session_rate_limit_per_minute",
            "SERVICE_PLACE_RATE_LIMIT_PER_MINUTE": "var.service_place_rate_limit_per_minute",
        }
        for environment_name, variable_expression in expected.items():
            self.assertIn(environment_name, terraform)
            self.assertIn(variable_expression, terraform)
        for marker in (
            "service_rate_limit_per_minute >= 1",
            "service_rate_limit_per_minute <= 600",
            "service_guest_session_rate_limit_per_minute >= 1",
            "service_guest_session_rate_limit_per_minute <= 120",
            "service_place_rate_limit_per_minute >= 1",
            "service_place_rate_limit_per_minute <= 1200",
            "rate_limit_cache_ttl_seconds >= 60",
        ):
            self.assertIn(marker, variables)

    def test_trusted_proxy_chain_resolves_viewer_not_cloudfront_pop(self) -> None:
        terraform = self.read("terraform/modules/service-platform/main.tf")
        runbook = self.read("aws/STAGING_RUNBOOK.md")
        self.assertIn("data.aws_ec2_managed_prefix_list.cloudfront.entries", terraform)
        self.assertIn("concat(aws_subnet.public[*].cidr_block", terraform)
        self.assertIn("nearest untrusted", terraform)
        self.assertNotIn('SERVICE_TRUSTED_PROXY_IPS", value = "0.0.0.0/0"', terraform)
        self.assertIn("viewer-supplied X-Forwarded-For", runbook)
        self.assertIn("CloudFront-managed origin-facing", runbook)

    def test_runtime_database_url_is_constructed_without_output(self) -> None:
        launcher = INFRA / "docker" / "service-api" / "runtime_entrypoint.py"
        env = os.environ.copy()
        env.update(
            {
                "SERVICE_ENVIRONMENT": "production",
                "SERVICE_DATABASE_HOST": "service.internal",
                "SERVICE_DATABASE_PORT": "5432",
                "SERVICE_DATABASE_NAME": "service",
                "SERVICE_DATABASE_USER": "service user",
                "SERVICE_DATABASE_PASSWORD": "not-a-real secret/with spaces",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                str(launcher),
                sys.executable,
                "-c",
                "import os; assert os.environ['DATABASE_URL'].startswith('postgresql://service%20user:')",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_waf_has_sensitive_path_limits(self) -> None:
        terraform = self.read("terraform/modules/service-platform/main.tf")
        for path in (
            "/api/v1/places/",
            "/api/v1/guest-sessions",
            "/api/v1/route-searches",
        ):
            self.assertIn(path, terraform)

    def test_migration_precedes_service_update(self) -> None:
        workflow = self.read("ci/github-actions/deploy-staging.yml")
        migrate = workflow.index("Run one-off migration gate")
        deploy = workflow.index("Deploy Service and wait")
        self.assertLess(migrate, deploy)
        self.assertIn("tasks-stopped", workflow)
        self.assertIn("exit_code", workflow)
        self.assertIn('test "$task_policy_version" = "$PRIVACY_DOCUMENT_VERSION"', workflow)

    def test_active_gce_cd_matches_build_certificate_and_deploy_sequence(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "cd-gce.yml").read_text(
            encoding="utf-8"
        )
        for dockerfile in (
            "src/infra/docker/web/Dockerfile",
            "src/infra/docker/service-api/Dockerfile",
            "src/infra/docker/routing-api/Dockerfile",
        ):
            self.assertIn(dockerfile, workflow)
        self.assertIn('branches: ["main"]', workflow)
        self.assertIn('tags: ["v*.*.*"]', workflow)
        self.assertIn("StrictHostKeyChecking=yes", workflow)
        self.assertNotIn("StrictHostKeyChecking=no", workflow)
        self.assertNotIn("ssh-keyscan", workflow)
        self.assertIn("HTTP health check timed out", workflow)
        self.assertIn("HTTPS health check timed out", workflow)
        self.assertLess(workflow.index("Start HTTP-only stack"), workflow.index("Issue / Renew SSL"))
        self.assertLess(workflow.index("Issue / Renew SSL"), workflow.index("Upload HTTPS Nginx template"))
        self.assertLess(workflow.index("service-migrate"), workflow.index("up -d --remove-orphans"))

    def test_gce_compose_preserves_private_routing_and_canonical_provider_names(self) -> None:
        compose = self.read("gce/docker-compose.prod.yml")
        routing = compose.split("  routing-api:", 1)[1].split("  service-migrate:", 1)[0]
        self.assertNotIn("ports:", routing)
        self.assertIn("routing-private:\n    internal: true", compose)
        self.assertIn("SERVICE_ROUTING_API_BASE_URL: https://routing.internal:8443", compose)
        self.assertIn('SERVICE_ROUTING_VERIFY_SSL: "true"', compose)
        self.assertIn('ROUTING_ALLOW_FIXTURE_BACKEND: "false"', compose)
        for key in (
            "KAKAO_REST_API_KEY",
            "GBIS_SERVICE_KEY",
            "GITS_API_KEY",
            "TMAP_APP_KEY",
            "ODSAY_API_KEY",
        ):
            self.assertIn(key, compose)
        for legacy in (
            "KAKAO_LOCAL_REST_KEY",
            "KAKAO_MOBILITY_REST_API_KEY",
            "KMA_SERVICE_KEY",
            "VITE_KAKAO_MAP_APP_KEY",
        ):
            self.assertNotIn(legacy, compose)


if __name__ == "__main__":
    unittest.main()
