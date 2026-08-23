from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from routing_worker.cli import CommandError, RuntimeConfig
from routing_worker.composition import (
    LeaseGrant,
    ProductionJobs,
    ProductionRunner,
    RunReservation,
    RunnerPolicy,
    ScheduledJob,
)


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def approved_config(*, provider: bool = True) -> RuntimeConfig:
    return RuntimeConfig(
        environment="STAGING",
        worker_enabled=True,
        db_approved=True,
        mutation_approved=True,
        provider_approved=provider,
        db_dsn="postgresql://must-never-appear",
    )


class FakeClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW + timedelta(microseconds=self.calls)


class FakeLease:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.acquired = []
        self.released = []

    def acquire(self, **values):
        self.acquired.append(values)
        if not self.available:
            return None
        return LeaseGrant(
            values["run_key"], values["owner_id"], "opaque-token",
            values["acquired_at"] + timedelta(seconds=values["ttl_seconds"]),
        )

    def release(self, grant, *, released_at):
        self.released.append((grant.run_key, released_at))


class FakeIdempotency:
    def __init__(self) -> None:
        self.completed = {}
        self.in_progress = set()
        self.reservations = []
        self.abandoned = []

    def reserve(self, **values):
        self.reservations.append(values)
        key = values["run_key"]
        if key in self.completed:
            return RunReservation("COMPLETED", self.completed[key])
        if key in self.in_progress:
            return RunReservation("IN_PROGRESS")
        self.in_progress.add(key)
        return RunReservation("STARTED")

    def complete(self, **values):
        self.in_progress.remove(values["run_key"])
        self.completed[values["run_key"]] = dict(values["result"])

    def abandon(self, **values):
        self.in_progress.discard(values["run_key"])
        self.abandoned.append(values)


class FakeProvider:
    def __init__(self, enabled: bool = True) -> None:
        self.capability_enabled = enabled
        self.calls = []

    def fetch_normalized(self, source_id, partition_key, at):
        self.calls.append((source_id, partition_key, at))
        return ()


class FakeRepository:
    def __init__(self) -> None:
        self.checkpoint_commits = []
        self.dead_letters = []
        self.atomic_model_actions = []

    def commit_normalized_checkpoint(self, source_id, partition_key, observations, at):
        self.checkpoint_commits.append((source_id, partition_key, observations, at))

    def write_dead_letter(self, **values):
        self.dead_letters.append(values)
        return "quality-run-id"

    def atomic_model_action(self, command, environment):
        self.atomic_model_actions.append((command, environment))


class RecordingJob:
    def __init__(self, kind: str, *, fail: bool = False) -> None:
        self.kind = kind
        self.fail = fail
        self.calls = []

    def run(self, command, payload, context):
        self.calls.append((command, dict(payload), context))
        if self.kind == "collector":
            observations = context.provider.fetch_normalized(
                payload["sourceId"], payload["partitionKey"], context.started_at,
            )
            context.repository.commit_normalized_checkpoint(
                payload["sourceId"], payload["partitionKey"], observations,
                context.started_at,
            )
        if self.kind == "model" and command in {"model-transition", "model-rollback"}:
            context.repository.atomic_model_action(command, context.deployment_environment)
        if self.fail:
            raise RuntimeError("postgresql://credential-that-must-not-be-recorded")
        return {"jobKind": self.kind, "processed": 1}


class FakeScheduler:
    def __init__(self) -> None:
        self.activations = []

    def activate(self, invocations):
        self.activations.append(invocations)


def build_runner(
    *,
    policy: RunnerPolicy | None = None,
    collector: RecordingJob | None = None,
    provider: FakeProvider | None = None,
    lease: FakeLease | None = None,
    scheduler: FakeScheduler | None = None,
):
    repository = FakeRepository()
    clock = FakeClock()
    idempotency = FakeIdempotency()
    lease = lease or FakeLease()
    provider = provider or FakeProvider()
    jobs = ProductionJobs(
        collector=collector or RecordingJob("collector"),
        quality=RecordingJob("quality"),
        legacy=RecordingJob("legacy"),
        model_registry=RecordingJob("model"),
    )
    runner = ProductionRunner(
        policy=policy or RunnerPolicy(enabled=True, provider_enabled=True, owner_id="worker-1"),
        repository=repository,
        provider=provider,
        clock=clock,
        lease=lease,
        idempotency=idempotency,
        scheduler=scheduler,
        jobs=jobs,
    )
    return runner, repository, provider, clock, lease, idempotency, jobs


class ProductionCompositionTest(unittest.TestCase):
    def test_default_runner_is_disabled_and_has_no_dependencies(self):
        runner = ProductionRunner()
        summary = runner.safe_summary()
        self.assertFalse(summary["enabled"])
        self.assertFalse(summary["databaseComposed"])
        with self.assertRaisesRegex(CommandError, "disabled"):
            runner.execute("model-vocabulary-inventory", {}, approved_config())

    def test_enabled_runner_requires_durable_dependencies_before_any_work(self):
        with self.assertRaisesRegex(CommandError, "dependencies are absent"):
            ProductionRunner(policy=RunnerPolicy(enabled=True, owner_id="worker-1"))

    def test_collector_uses_normalized_provider_checkpoint_and_replays_cached_result(self):
        runner, repository, provider, _clock, lease, idempotency, jobs = build_runner()
        payload = {"sourceId": "gbis", "partitionKey": "route-1", "observations": []}
        first = runner.execute("collector-run", payload, approved_config())
        second = runner.execute("collector-run", payload, approved_config())
        self.assertEqual(first, second)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(repository.checkpoint_commits), 1)
        self.assertEqual(len(jobs.collector.calls), 1)
        self.assertEqual(len(lease.acquired), 1)
        self.assertEqual(len(lease.released), 1)
        self.assertEqual(len(idempotency.reservations), 2)

    def test_disabled_provider_or_capability_fails_before_reservation_and_job(self):
        for policy_enabled, capability in ((False, True), (True, False)):
            with self.subTest(policy_enabled=policy_enabled, capability=capability):
                runner, _repo, provider, _clock, _lease, idem, jobs = build_runner(
                    policy=RunnerPolicy(
                        enabled=True, provider_enabled=policy_enabled, owner_id="worker-1"
                    ),
                    provider=FakeProvider(capability),
                )
                with self.assertRaises(CommandError):
                    runner.execute(
                        "collector-run",
                        {"sourceId": "gbis", "partitionKey": "route-1", "observations": []},
                        approved_config(),
                    )
                self.assertEqual(idem.reservations, [])
                self.assertEqual(jobs.collector.calls, [])
                self.assertEqual(provider.calls, [])

    def test_lease_denial_abandons_reservation_before_provider_or_database(self):
        denied = FakeLease(available=False)
        runner, repository, provider, _clock, _lease, idem, jobs = build_runner(lease=denied)
        with self.assertRaisesRegex(CommandError, "lease is unavailable"):
            runner.execute(
                "collector-run",
                {"sourceId": "gbis", "partitionKey": "route-1", "observations": []},
                approved_config(),
            )
        self.assertEqual(len(idem.abandoned), 1)
        self.assertEqual(provider.calls, [])
        self.assertEqual(repository.checkpoint_commits, [])
        self.assertEqual(jobs.collector.calls, [])

    def test_collector_failure_records_only_sanitized_dlq_and_releases_lease(self):
        failing = RecordingJob("collector", fail=True)
        runner, repository, _provider, _clock, lease, idem, _jobs = build_runner(collector=failing)
        with self.assertRaises(CommandError) as raised:
            runner.execute(
                "collector-run",
                {"sourceId": "gbis", "partitionKey": "route-1", "observations": []},
                approved_config(),
            )
        self.assertNotIn("credential", str(raised.exception))
        self.assertEqual(len(repository.dead_letters), 1)
        dlq = repository.dead_letters[0]
        self.assertEqual(dlq["reason"], "COLLECTOR_JOB_FAILED")
        self.assertNotIn("credential", repr(dlq))
        self.assertEqual(len(idem.abandoned), 1)
        self.assertEqual(len(lease.released), 1)

    def test_job_families_are_closed_and_non_collector_context_has_no_provider(self):
        runner, repository, _provider, _clock, _lease, _idem, jobs = build_runner()
        cases = (
            ("legacy-inventory", {"sourcePath": "legacy.sqlite", "tableSpecs": []}, jobs.legacy),
            ("quality-gate", {"sourceId": "gbis", "datasetVersion": "dq-v1", "observations": []}, jobs.quality),
            ("model-vocabulary-inventory", {}, jobs.model_registry),
            (
                "model-transition",
                {"version": "eta-v1", "expectedState": "REGISTERED", "targetState": "VALIDATED", "environment": "staging"},
                jobs.model_registry,
            ),
            (
                "model-rollback",
                {"failedVersion": "eta-v2", "restoreVersion": "eta-v1", "environment": "staging"},
                jobs.model_registry,
            ),
        )
        for command, payload, expected_job in cases:
            with self.subTest(command=command):
                runner.execute(command, payload, approved_config())
                self.assertIsNone(expected_job.calls[-1][2].provider)
        self.assertEqual(
            repository.atomic_model_actions,
            [("model-transition", "staging"), ("model-rollback", "staging")],
        )

    def test_eta_seat_split_calibration_and_safe_artifact_gate_precede_reservation(self):
        runner, _repository, _provider, _clock, _lease, idem, jobs = build_runner()
        base = {
            "family": "ETA",
            "version": "eta-v1",
            "artifactUri": "s3://models/eta-v1.pkl",
            "artifactSha256": "a" * 64,
            "featureSchemaVersion": "seat-risk-feature-v1",
            "trainingScope": {
                "calibrationSha256": "b" * 64,
                "datasetSha256": "c" * 64,
                "missingTargetPolicy": "EXCLUDE_UNOBSERVED",
                "modelCardSha256": "d" * 64,
                "splitPolicy": "TEMPORAL_TRIP_GROUP_PURGED",
            },
        }
        for replacement in (
            {},
            {"featureSchemaVersion": "eta-feature-v1"},
        ):
            payload = dict(base)
            payload.update(replacement)
            with self.subTest(replacement=replacement):
                with self.assertRaises(CommandError):
                    runner.execute("model-register", payload, approved_config())
        self.assertEqual(idem.reservations, [])
        self.assertEqual(jobs.model_registry.calls, [])

    def test_scheduler_is_inactive_by_default_and_explicit_activation_only_registers(self):
        runner, *_ = build_runner()
        schedule = ScheduledJob("quality-hourly", "quality-gate", {
            "sourceId": "gbis", "datasetVersion": "dq-v1", "observations": [],
        })
        with self.assertRaisesRegex(CommandError, "scheduler is disabled"):
            runner.activate_schedules((schedule,), approved_config(), activation_approved=True)

        scheduler = FakeScheduler()
        runner, _repo, _provider, _clock, _lease, _idem, jobs = build_runner(
            policy=RunnerPolicy(
                enabled=True, provider_enabled=True, scheduler_enabled=True,
                owner_id="worker-1",
            ),
            scheduler=scheduler,
        )
        with self.assertRaisesRegex(CommandError, "not explicitly approved"):
            runner.activate_schedules((schedule,), approved_config())
        self.assertEqual(scheduler.activations, [])
        runner.activate_schedules((schedule,), approved_config(), activation_approved=True)
        self.assertEqual(len(scheduler.activations), 1)
        self.assertEqual(jobs.quality.calls, [])
        scheduler.activations[0][0].invoke()
        self.assertEqual(len(jobs.quality.calls), 1)

    def test_invalid_schedule_batch_is_rejected_before_atomic_scheduler_call(self):
        scheduler = FakeScheduler()
        runner, *_ = build_runner(
            policy=RunnerPolicy(
                enabled=True, provider_enabled=True, scheduler_enabled=True,
                owner_id="worker-1",
            ),
            scheduler=scheduler,
        )
        duplicate = ScheduledJob("same", "model-vocabulary-inventory", {})
        with self.assertRaisesRegex(CommandError, "unique ids"):
            runner.activate_schedules(
                (duplicate, duplicate), approved_config(), activation_approved=True,
            )
        self.assertEqual(scheduler.activations, [])


if __name__ == "__main__":
    unittest.main()
