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

    def test_service_and_web_images_are_multistage_non_root(self) -> None:
        for relative in ("docker/service-api/Dockerfile", "docker/web/Dockerfile"):
            dockerfile = self.read(relative)
            self.assertGreaterEqual(dockerfile.count("FROM "), 2)
            self.assertIn("USER ", dockerfile)
            self.assertIn("HEALTHCHECK", dockerfile)

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


if __name__ == "__main__":
    unittest.main()
