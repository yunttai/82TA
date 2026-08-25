from __future__ import annotations

import os
import re
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
            "**/*.sqlite3",
            "**/.env.*",
        ):
            self.assertIn(excluded, dockerignore)
        self.assertIn("!**/.env.example", dockerignore)
        for required in ("contracts/", "generated/", "**/migrations/"):
            self.assertNotIn(required, dockerignore)

    def test_images_are_multistage_non_root_and_health_checked(self) -> None:
        for relative in (
            "docker/service-api/Dockerfile",
            "docker/web/Dockerfile",
            "docker/routing-api/Dockerfile",
        ):
            dockerfile = self.read(relative)
            self.assertGreaterEqual(dockerfile.count("FROM "), 2)
            self.assertIn("USER ", dockerfile)
            self.assertIn("HEALTHCHECK", dockerfile)

    def test_routing_e2e_keeps_browser_on_service_http_boundary(self) -> None:
        compose = self.read("docker/compose.routing-e2e.yml")
        self.assertIn("SERVICE_ROUTING_GATEWAY: http", compose)
        self.assertIn("SERVICE_ROUTING_API_BASE_URL: http://routing-api:8000", compose)
        self.assertIn("routing_deployment.wsgi:application", compose)
        self.assertIn('ROUTING_ALLOW_FIXTURE_BACKEND: "false"', compose)
        routing_block = compose.split("  routing-api:", 1)[1].split(
            "  service-api:", 1
        )[0]
        self.assertNotIn("ports:", routing_block)

    def test_routing_live_overlay_enforces_exact_proxy_and_dev_provenance(self) -> None:
        overlay = self.read("docker/compose.routing-live.yml")
        proxy = self.read("docker/provider-egress-proxy/egress_proxy.py")
        self.assertIn("ROUTING_RUNTIME_ENVIRONMENT: DEVELOPMENT", overlay)
        self.assertIn('ROUTING_LOCAL_LIVE_E2E: "true"', overlay)
        self.assertIn(
            "ROUTING_PROVIDER_HTTPS_PROXY_URL: http://routing-egress-proxy:3128",
            overlay,
        )
        self.assertIn("routing-private:\n    internal: true", overlay)
        self.assertIn('fields[0] != "CONNECT"', proxy)
        self.assertIn('port != "443"', proxy)
        self.assertNotIn("print(", proxy)

    def test_only_gce_cloud_deployment_is_present(self) -> None:
        legacy_provider = "a" + "w" + "s"
        legacy_directory = INFRA / legacy_provider
        self.assertFalse(
            any(path.is_file() for path in legacy_directory.rglob("*"))
            if legacy_directory.exists()
            else False
        )
        for legacy_module in (
            "service" + "-platform",
            "routing" + "-platform",
        ):
            module_directory = INFRA / "terraform/modules" / legacy_module
            self.assertFalse(
                any(path.is_file() for path in module_directory.rglob("*"))
                if module_directory.exists()
                else False
            )
        active_workflows = sorted(
            path.name for path in (ROOT / ".github/workflows").glob("*.yml")
        )
        self.assertEqual(active_workflows, ["cd-gce.yml"])

        deployment_text = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in INFRA.rglob("*")
            if (
                path.is_file()
                and "tests" not in path.parts
                and ".terraform" not in path.parts
            )
        )
        forbidden = (
            "hashicorp/" + legacy_provider,
            'resource "' + legacy_provider + '_',
            'provider "' + legacy_provider + '"',
            'backend "s' + '3"',
            "arn:" + legacy_provider + ":",
            "s" + "3://",
        )
        for marker in forbidden:
            self.assertNotIn(marker, deployment_text)

    def test_gce_terraform_provisions_current_platform_boundary(self) -> None:
        module = self.read("terraform/modules/gce-platform/main.tf")
        variables = self.read("terraform/modules/gce-platform/variables.tf")
        staging = self.read("terraform/environments/staging/main.tf")
        versions = self.read("terraform/environments/staging/versions.tf")
        backend = self.read("terraform/environments/staging/backend.hcl.example")

        for resource in (
            'resource "google_compute_instance" "platform"',
            'resource "google_compute_network" "platform"',
            'resource "google_compute_subnetwork" "platform"',
            'resource "google_compute_address" "platform"',
            'resource "google_compute_firewall" "web"',
            'resource "google_compute_firewall" "ssh"',
            'resource "google_service_account" "runtime"',
            'resource "google_storage_bucket" "model_artifacts"',
        ):
            self.assertIn(resource, module)
        self.assertIn('source  = "hashicorp/google"', versions)
        self.assertIn('backend "gcs"', versions)
        self.assertIn('bucket = "REPLACE_WITH_VERSIONED_TERRAFORM_STATE_BUCKET"', backend)
        self.assertIn('enable-oslogin         = "TRUE"', module)
        self.assertIn("shielded_instance_config", module)
        self.assertIn("public_access_prevention    = \"enforced\"", module)
        self.assertIn("uniform_bucket_level_access = true", module)
        self.assertIn("versioning {", module)
        self.assertIn('role   = "roles/storage.objectViewer"', module)
        self.assertNotIn("google_service_account_key", module)
        self.assertIn("length(var.ssh_source_ranges) > 0", variables)
        self.assertNotIn("bootstrap-host.sh", staging + module)
        self.assertNotIn("metadata_startup_script", module)

    def test_gce_terraform_does_not_store_application_secrets(self) -> None:
        terraform = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (INFRA / "terraform").rglob("*.tf")
        )
        for secret_name in (
            "KAKAO_REST_API_KEY",
            "GBIS_SERVICE_KEY",
            "SERVICE_SECRET_KEY",
            "ROUTING_DJANGO_SECRET_KEY",
            "SSH_KEY",
        ):
            self.assertNotIn(secret_name, terraform)
        self.assertNotIn("private_key", terraform)

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

    def test_database_bootstrap_binds_passwords_and_fails_closed(self) -> None:
        launcher = INFRA / "docker" / "routing-api" / "runtime_entrypoint.py"
        bootstrap = self.read("docker/routing-api/database_bootstrap.py")
        self.assertIn("CREATE EXTENSION IF NOT EXISTS postgis", bootstrap)
        self.assertIn('_APPLICATION_ROLE = "routing_app"', bootstrap)
        self.assertIn('_MIGRATION_ROLE = "routing_migrator"', bootstrap)
        self.assertIn("WITH LOGIN PASSWORD %s", bootstrap)
        self.assertIn("(role_password,)", bootstrap)
        self.assertNotIn("sql.Literal", bootstrap)
        self.assertNotIn("print(", bootstrap)

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

    def test_browser_never_targets_routing_and_api_request_lines_are_not_logged(self) -> None:
        compose = self.read("docker/compose.service-product.yml")
        nginx = self.read("docker/web/default.conf.template")
        service_dockerfile = self.read("docker/service-api/Dockerfile")
        self.assertNotIn("routing-api", compose)
        self.assertNotIn("/v1/routes/optimize", nginx)
        self.assertIn("proxy_pass http://${SERVICE_UPSTREAM}", nginx)
        self.assertIn("location /api/", nginx)
        self.assertIn("access_log off", nginx)
        self.assertIn('"--access-logfile", "/dev/null"', service_dockerfile)

    def test_service_product_redis_is_private_persistent_and_required(self) -> None:
        compose = self.read("docker/compose.service-product.yml")
        redis_block = compose.split("  service-redis:", 1)[1].split("  service-api:", 1)[0]
        service_block = compose.split("  service-api:", 1)[1].split("  web:", 1)[0]

        self.assertIn("image: redis:7.4-alpine", redis_block)
        self.assertIn(
            '["redis-server", "--appendonly", "yes", "--appendfsync", "everysec"]',
            redis_block,
        )
        self.assertIn("restart: unless-stopped", redis_block)
        self.assertIn('["CMD", "redis-cli", "ping"]', redis_block)
        self.assertIn("service-redis-data:/data", redis_block)
        self.assertNotIn("ports:", redis_block)
        self.assertIn("service-coordination:\n    internal: true", compose)

        self.assertIn("SERVICE_REDIS_URL: redis://service-redis:6379/0", service_block)
        self.assertIn("service-redis:\n        condition: service_healthy", service_block)
        self.assertIn("- service-coordination", service_block)
        self.assertNotIn("SERVICE_SINGLE_NODE_MODE", compose)

        secret = re.search(
            r"SERVICE_REDIS_KEY_DERIVATION_SECRET:\s*([^\s]+)",
            service_block,
        )
        self.assertIsNotNone(secret)
        self.assertGreaterEqual(len(secret.group(1)), 32)

    def test_active_gce_cd_matches_build_certificate_and_deploy_sequence(self) -> None:
        workflow = (ROOT / ".github/workflows/cd-gce.yml").read_text(encoding="utf-8")
        for dockerfile in (
            "src/infra/docker/web/Dockerfile",
            "src/infra/docker/service-api/Dockerfile",
            "src/infra/docker/routing-api/Dockerfile",
            "src/infra/docker/provider-egress-proxy/Dockerfile",
        ):
            self.assertIn(dockerfile, workflow)
        self.assertIn('branches: ["main"]', workflow)
        self.assertIn('tags: ["v*.*.*"]', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("StrictHostKeyChecking=yes", workflow)
        self.assertNotIn("StrictHostKeyChecking=no", workflow)
        self.assertNotIn("ssh-keyscan", workflow)
        self.assertIn("Bootstrap the blank server", workflow)
        self.assertIn("bootstrap-host.sh", workflow)
        self.assertIn("82ta-refresh-provider-evidence", workflow)
        self.assertIn("82ta-certificate-renew.timer", workflow)
        self.assertIn("HTTP health check timed out", workflow)
        self.assertIn("HTTPS health check timed out", workflow)
        self.assertLess(
            workflow.index("Bootstrap the blank server"),
            workflow.index("Start bootstrap provider egress proxy"),
        )
        self.assertLess(
            workflow.index("Start bootstrap provider egress proxy"),
            workflow.index("Probe Providers and create runtime evidence"),
        )
        self.assertLess(
            workflow.index("Probe Providers and create runtime evidence"),
            workflow.index("Start HTTP stack in dependency order"),
        )
        self.assertLess(
            workflow.index("Start HTTP stack in dependency order"),
            workflow.index("Issue certificate and switch Nginx to HTTPS"),
        )

    def test_gce_compose_preserves_private_routing_and_honest_runtime_flags(self) -> None:
        compose = self.read("gce/docker-compose.prod.yml")
        routing = compose.split("\n  routing-api:\n", 1)[1].split(
            "\n  provider-evidence:\n", 1
        )[0]
        self.assertNotIn("ports:", routing)
        self.assertIn("routing-private:\n    internal: true", compose)
        self.assertIn("SERVICE_ROUTING_API_BASE_URL: http://routing-api:8000", compose)
        self.assertIn('SERVICE_ROUTING_VERIFY_SSL: "false"', compose)
        self.assertIn("SERVICE_ENVIRONMENT: development", compose)
        self.assertIn("ROUTING_RUNTIME_ENVIRONMENT: DEVELOPMENT", compose)
        self.assertIn('ROUTING_LOCAL_LIVE_E2E: "true"', compose)
        self.assertIn('ROUTING_ALLOW_FIXTURE_BACKEND: "false"', compose)
        self.assertIn("routing-db:\n    image: postgis/postgis:16-3.4", compose)
        self.assertIn("routing-redis:\n    image: redis:7.4-alpine", compose)

    def test_gce_blank_server_bootstrap_generates_runtime_and_refresh_jobs(self) -> None:
        bootstrap = self.read("gce/bootstrap-host.sh")
        refresh = self.read("gce/refresh-provider-evidence.sh")
        example = self.read("gce/.env.example")
        self.assertIn("remote_dir=/opt/82ta", bootstrap)
        self.assertIn("docker-compose-plugin", bootstrap)
        self.assertIn("openssl rand -hex", bootstrap)
        self.assertIn("service-data/service-api.sqlite3", bootstrap)
        self.assertIn("82ta-provider-evidence-refresh.timer", bootstrap)
        self.assertIn("82ta-certificate-renew.timer", bootstrap)
        self.assertIn(".runtime/provider-evidence.env", refresh)
        self.assertIn("# DATABASE_URL=", example)
        self.assertIn("ROUTING_DB_HOST=routing-db", example)


if __name__ == "__main__":
    unittest.main()
