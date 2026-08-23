from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from routing_worker.cli import COMMANDS, InjectedCommandExecutor, RuntimeConfig, run


WORKERS = Path(__file__).parents[1]


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, command, payload, config):
        self.calls.append((command, payload, config.safe_summary()))
        return {"accepted": 1}


class SecretFailingExecutor:
    def execute(self, command, payload, config):
        raise RuntimeError("postgresql://secret-value-that-must-not-print")


def approved_environment():
    return {
        "ROUTING_WORKER_ENVIRONMENT": "STAGING",
        "ROUTING_WORKER_ENABLED": "true",
        "ROUTING_WORKER_DB_APPROVED": "true",
        "ROUTING_WORKER_MUTATION_APPROVED": "true",
        "ROUTING_WORKER_PROVIDER_PRODUCTION_APPROVED": "true",
        "ROUTING_WORKER_DB_DSN": "postgresql://secret-value-that-must-not-print",
    }


class CliTest(unittest.TestCase):
    def test_every_command_has_deterministic_unscheduled_dry_run(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                argv = (command, "--dry-run", "--input-json", '{"version":"v1"}')
                first_out, first_err = StringIO(), StringIO()
                second_out, second_err = StringIO(), StringIO()
                self.assertEqual(run(argv, environ={}, executor=None, stdout=first_out, stderr=first_err), 0)
                self.assertEqual(run(argv, environ={}, executor=None, stdout=second_out, stderr=second_err), 0)
                self.assertEqual(first_out.getvalue(), second_out.getvalue())
                result = json.loads(first_out.getvalue())
                self.assertFalse(result["scheduled"])
                self.assertEqual(result["networkCalls"], 0)

    def test_subprocess_dry_run_redacts_dsn_and_does_not_need_connector(self):
        environment = os.environ.copy()
        environment.update(approved_environment())
        process = subprocess.run(
            [sys.executable, "-B", "-m", "routing_worker", "collector-run", "--dry-run"],
            cwd=WORKERS, env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn("secret-value", process.stdout + process.stderr)
        self.assertTrue(json.loads(process.stdout)["config"]["dbConfigured"])

    def test_missing_config_fails_before_executor(self):
        executor = RecordingExecutor()
        stdout, stderr = StringIO(), StringIO()
        code = run(
            (
                "model-transition", "--input-json",
                '{"version":"eta-v1","expectedState":"REGISTERED","targetState":"VALIDATED","environment":"staging"}',
            ),
            environ={}, executor=executor,
            stdout=stdout, stderr=stderr,
        )
        self.assertEqual(code, 2)
        self.assertEqual(executor.calls, [])
        self.assertEqual(json.loads(stderr.getvalue())["status"], "FAIL_CLOSED")

    def test_provider_approval_absent_fails_before_executor(self):
        environment = approved_environment()
        environment["ROUTING_WORKER_PROVIDER_PRODUCTION_APPROVED"] = "false"
        executor = RecordingExecutor()
        stderr = StringIO()
        code = run(
            (
                "collector-run", "--input-json",
                '{"sourceId":"gbis","partitionKey":"route-1","observations":[]}',
            ),
            environ=environment, executor=executor,
            stdout=StringIO(), stderr=stderr,
        )
        self.assertEqual(code, 2)
        self.assertEqual(executor.calls, [])
        self.assertIn("Provider production approval", stderr.getvalue())

    def test_fully_approved_injected_executor_runs_without_disclosing_dsn(self):
        executor = RecordingExecutor()
        stdout, stderr = StringIO(), StringIO()
        code = run(
            (
                "model-transition", "--input-json",
                '{"version":"eta-v1","expectedState":"REGISTERED","targetState":"VALIDATED","environment":"staging"}',
            ),
            environ=approved_environment(), executor=executor, stdout=stdout, stderr=stderr,
        )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(len(executor.calls), 1)
        self.assertNotIn("secret-value", stdout.getvalue() + stderr.getvalue() + repr(executor.calls))

    def test_closed_injected_dispatch_rejects_unknown_or_missing_handlers(self):
        with self.assertRaises(ValueError):
            InjectedCommandExecutor({"unknown-command": lambda payload, config: {}})
        executor = InjectedCommandExecutor({"quality-gate": lambda payload, config: {"rows": 1}})
        stderr = StringIO()
        code = run(
            (
                "model-transition", "--input-json",
                '{"version":"eta-v1","expectedState":"REGISTERED","targetState":"VALIDATED","environment":"staging"}',
            ),
            environ=approved_environment(), executor=executor,
            stdout=StringIO(), stderr=stderr,
        )
        self.assertEqual(code, 2)
        self.assertIn("handler is not composed", stderr.getvalue())

    def test_nested_identity_secret_or_raw_input_is_rejected(self):
        for key in ("email", "plateNumber", "rawPayload", "apiKey", "User-ID"):
            executor = RecordingExecutor()
            code = run(
                ("quality-gate", "--dry-run", "--input-json", json.dumps({"nested": {key: "x"}})),
                environ={}, executor=executor, stdout=StringIO(), stderr=StringIO(),
            )
            self.assertEqual(code, 2)
            self.assertEqual(executor.calls, [])

    def test_approved_config_still_fails_closed_when_main_has_no_composed_executor(self):
        environment = os.environ.copy()
        environment.update(approved_environment())
        process = subprocess.run(
            [
                sys.executable, "-B", "-m", "routing_worker", "model-transition",
                "--input-json",
                '{"version":"eta-v1","expectedState":"REGISTERED","targetState":"VALIDATED","environment":"staging"}',
            ],
            cwd=WORKERS, env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("executor is not composed", process.stderr)
        self.assertNotIn("secret-value", process.stdout + process.stderr)

    def test_cli_rejects_noncanonical_state_and_cross_family_schema_even_in_dry_run(self):
        cases = (
            (
                "model-transition",
                {"version": "eta-v1", "expectedState": "ACTIVE", "targetState": "ROLLED_BACK"},
            ),
            (
                "model-register",
                {"family": "SEAT_RISK", "featureSchemaVersion": "eta-feature-foundation-v1"},
            ),
        )
        for command, payload in cases:
            with self.subTest(command=command):
                code = run(
                    (command, "--dry-run", "--input-json", json.dumps(payload)),
                    environ={}, executor=None, stdout=StringIO(), stderr=StringIO(),
                )
                self.assertEqual(code, 2)

    def test_runtime_environment_maps_without_changing_safe_summary(self):
        expected = {
            "DEVELOPMENT": "dev",
            "STAGING": "staging",
            "PRODUCTION": "prod",
        }
        for runtime, persisted in expected.items():
            with self.subTest(runtime=runtime):
                config = RuntimeConfig.from_environ(
                    {"ROUTING_WORKER_ENVIRONMENT": runtime}
                )
                self.assertEqual(config.safe_summary()["environment"], runtime)
                self.assertEqual(config.deployment_environment, persisted)

    def test_cli_rejects_persisted_aliases_and_unsupported_worker_purposes(self):
        cases = (
            ("model-register", {"family": "BUS_ETA"}),
            ("model-register", {"family": "CALIBRATION"}),
            ("model-register", {"family": "TAXI_DISPATCH_WAIT"}),
            ("model-transition", {"environment": "STAGING"}),
            ("model-rollback", {"environment": "PRODUCTION"}),
        )
        for command, payload in cases:
            with self.subTest(command=command, payload=payload):
                code = run(
                    (command, "--dry-run", "--input-json", json.dumps(payload)),
                    environ={}, executor=None, stdout=StringIO(), stderr=StringIO(),
                )
                self.assertEqual(code, 2)

    def test_runtime_and_persisted_environment_mismatch_fails_before_executor(self):
        executor = RecordingExecutor()
        code = run(
            (
                "model-transition",
                "--input-json",
                '{"version":"eta-v1","expectedState":"REGISTERED",'
                '"targetState":"VALIDATED","environment":"prod"}',
            ),
            environ=approved_environment(),
            executor=executor,
            stdout=StringIO(),
            stderr=StringIO(),
        )
        self.assertEqual(code, 2)
        self.assertEqual(executor.calls, [])

    def test_executor_exception_is_sanitized(self):
        stderr = StringIO()
        code = run(
            (
                "model-transition", "--input-json",
                '{"version":"eta-v1","expectedState":"REGISTERED","targetState":"VALIDATED","environment":"staging"}',
            ),
            environ=approved_environment(), executor=SecretFailingExecutor(),
            stdout=StringIO(), stderr=stderr,
        )
        self.assertEqual(code, 3)
        self.assertNotIn("secret-value", stderr.getvalue())
        self.assertIn("execution failed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
