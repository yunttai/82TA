import json

from routing_worker.data_quality.dataset_foundation import build_target_stop_labels
from routing_worker.data_quality.quality_gate import evaluate_quality
from routing_worker.job_entrypoints import (
    collector_main,
    legacy_main,
    model_main,
    quality_main,
)
from routing_worker.model_jobs.evaluation import evaluate_eta
from routing_worker.model_jobs.registry import transition
from routing_worker.transport_collector.runtime import collect_batch


def test_runtime_foundations_are_real_packaged_imports() -> None:
    assert callable(build_target_stop_labels)
    assert callable(evaluate_quality)
    assert callable(evaluate_eta)
    assert callable(transition)
    assert callable(collect_batch)


def test_explicit_job_entrypoints_are_dry_run_only_without_composition(
    capsys,
) -> None:
    entrypoints = (
        (collector_main, "collector-run"),
        (legacy_main, "legacy-inventory"),
        (quality_main, "quality-gate"),
        (model_main, "model-vocabulary-inventory"),
    )
    for entrypoint, command in entrypoints:
        assert entrypoint([command, "--dry-run"]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["command"] == command
        assert output["dryRun"] is True
        assert output["networkCalls"] == 0
        assert output["scheduled"] is False


def test_job_entrypoints_reject_cross_family_and_uncomposed_execution(
    monkeypatch, capsys,
) -> None:
    assert collector_main(["evaluate-eta", "--dry-run"]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "FAIL_CLOSED"

    monkeypatch.setenv("ROUTING_WORKER_ENVIRONMENT", "STAGING")
    monkeypatch.setenv("ROUTING_WORKER_ENABLED", "true")
    monkeypatch.setenv("ROUTING_WORKER_DB_APPROVED", "true")
    monkeypatch.setenv("ROUTING_WORKER_MUTATION_APPROVED", "true")
    monkeypatch.setenv("ROUTING_WORKER_PROVIDER_PRODUCTION_APPROVED", "true")
    monkeypatch.setenv("ROUTING_WORKER_DB_DSN", "redacted-in-test")
    payload = '{"sourceId":"source","partitionKey":"p","observations":[]}'
    assert collector_main(["collector-run", "--input-json", payload]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error == {
        "error": "approved worker executor is not composed",
        "status": "FAIL_CLOSED",
    }
