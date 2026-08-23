# Routing data and model workers

This directory contains offline data/model primitives and a fail-closed durable worker
package. Workers are never scheduled or enabled by importing/installing the package.

## Durable package

`routing_worker` accepts an injected PostgreSQL-compatible DB-API connection factory.
It owns the transaction, requests serializable isolation, parameterizes every value,
checks conflict/row-count semantics, and rolls back any failed observation/checkpoint,
lineage, quality, registry, deployment, rollback, or prediction-audit operation.

It uses only tables already declared in the Routing DBML:

- `ingestion_checkpoint`: collector watermark, quota/freshness state, natural-key
  dedupe markers, and legacy lineage markers;
- `data_quality_run`: quality reports, sanitized DLQ evidence, and reconciliation;
- `bus_arrival_observation` / `bus_location_observation`: normalized observations;
- `model_family`, `model_version`, `model_metric`, `model_deployment`, and
  `prediction_audit`: model evidence and serving lifecycle.

There is no Service DB import, identity field, raw Provider payload, plate, dynamic SQL
identifier, built-in DSN connector, secret loader, Provider client, or scheduler.

Training metadata keeps the local labels `ETA` and `SEAT_RISK`; the persistence
boundary maps them exactly to private-API purposes `BUS_ETA` and `SEAT_RISK`.
Uppercase `DEVELOPMENT|STAGING|PRODUCTION` remains process configuration only and is
mapped explicitly to persisted `dev|staging|prod`. Persisted aliases and arbitrary
case folding are rejected. `model-vocabulary-inventory` reports distinct/count drift
and produces a non-mutating collision-safe migration plan; it never dual-reads,
dual-writes, or applies a data migration.

## Commands

From a source checkout or installed wheel:

```text
python -m routing_worker <command> --dry-run --input-json '{}'
```

Commands cover collector execution, legacy inventory/import planning, model vocabulary
inventory, quality gate,
dataset build, ETA/Seat evaluation, model registration/transition, drift audit, and
rollback. Dry-run is deterministic and makes zero network/DB calls. Non-dry execution
requires explicit worker, Routing DB, mutation, and—only for collection—Provider
production approvals plus an injected closed command executor. The installed default
has no executor and therefore exits nonzero without mutation.

The console never prints the DSN or secret values. Inline input rejects recursively
nested user identity, raw payload, plate, credential, or secret keys.

## Packaged train/serve seam

The optional `model-context` package extra declares the exact local distribution
dependency `budget-route-bus-intelligence-core==0.1.0`. Repository tests compose it
from `src/packages/bus-intelligence-core`; an offline deployment build must build and
install that local wheel alongside the worker artifacts rather than resolving an
unreviewed public package.

`routing_worker.feature_schema` owns only the full ETA/Seat feature schemas. It imports
the Bus package's family-specific context versions and ordered feature names directly;
the eight-field context projection is never copied into workers. The installed base
CLI does not import this optional module and remains default-disabled with zero
Provider/DB/scheduler calls. Model/data jobs require the optional dependency before
their feature builders can be composed.

`routing_worker.feature_builder` is the single implementation of the canonical
22-field ETA and Seat Risk vectors. `routing_worker.serving_features` supplies
separate durable feature-source ports and calls that same builder. The versioned
`routing_worker.feature_encoding` projection is also shared exactly by offline
training and native serving: strings use a deterministic SHA-256 categorical
projection, `None` becomes LightGBM missing (NaN), and zero/`False` remain observed.

The optional `model-runtime` extra adds LightGBM without enabling it. Concrete
`LightGbmEtaRuntimeLoader` and `LightGbmSeatRiskRuntimeLoader` implementations live
in `routing_worker.native_lightgbm`. They load only fixed, already hash-verified
native text artifacts, validate strict bounded feature/calibration JSON, and check
the model's internal feature order and objective metadata. ETA currently supports
only one scalar regression booster plus an attested CONFORMAL residual offset; the
one-artifact loader rejects QUANTILE until a two-booster bundle exists. Seat Risk
requires a stock four-class ordinal multiclass booster (0, 1–2, 3–5, >5), derives
cumulative threshold probabilities, then applies three bounded Platt/isotonic
calibrators. Unsupported output shapes, non-finite values, pickle/joblib, absent
dependencies, and metadata drift fail closed.

Production predictor composition must use `build_verified_eta_predictor` or
`build_verified_seat_risk_predictor` with a `VerifiedServingLifecycle` that binds an
immutable `RegistryEntry`, full-traffic ACTIVE `Deployment`, bundle manifest,
model-card/schema/calibration hashes, validation evidence, and environment before
the native loader is invoked. These factories do not discover artifact paths from a
request and do not claim that a trained or approved artifact exists.

The wheel also includes `routing_worker.data_quality`,
`routing_worker.transport_collector`, and `routing_worker.model_jobs`; the legacy
hyphenated source directories are compatibility shims and tests, not duplicate
implementations. Explicit installed scripts are `routing-worker-collector`,
`routing-worker-quality`, `routing-worker-legacy`, and `routing-worker-model`; each
remains dry-run/default-disabled unless a reviewed executor is injected.

## Production composition gate

`routing_worker.composition.ProductionRunner` is the injectable production-shaped
composition root. Its default policy is disabled and it has no credentials or
dependencies. An enabled instance requires all of the following explicitly:

- a `PostgresWorkerRepository` built from a reviewed Routing-only DB factory;
- a timezone-aware clock, distributed compare-and-delete lease, and durable atomic
  idempotency ledger;
- separate collector, quality, legacy, and model-registry job ports;
- a schema-validated normalized Provider port for collection, behind both runtime
  approval and an independent capability flag;
- an atomic scheduler adapter only when scheduler enablement and a separate activation
  approval are both present.

The runner validates the command and canonical deployment environment before durable
reservation, then acquires a bounded lease before the job can touch Provider or DB
state. Completed runs replay their sanitized stored result. Collector failure writes
only a hashed, sanitized DLQ summary. Underlying repository calls retain their own
serializable transaction boundaries, including observation+checkpoint commit and
model activation/rollback.

Schedule registration is never performed by construction or package import. The
installed `routing-worker` entry point intentionally continues to pass no executor;
deployment packaging must call `run(..., executor=reviewed_runner)` or provide an
equivalent private wrapper under `src/workers` after supplying every dependency.

Operations must still provide and verify the DB schema/migration, connection pooling,
TLS and Routing-only role, distributed idempotency/lease backend, scheduler atomicity,
retention, quota, monitoring, backup/restore, artifact signing, and WORM operator
audit. None of those external states is activated or claimed by this package.
