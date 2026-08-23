# Data Quality Worker

수집 지연, 중복, station sequence 역행, 결측, schema drift, label coverage와 분포 변화를 검사한다.

## Offline-verifiable entry points

- `routing_worker.data_quality.legacy_sqlite`: immutable read-only inventory, file hash, schema/row/date/
  coverage diagnostics, and destination-agnostic idempotent lineage import ports.
- `routing_worker.data_quality.dataset_foundation`: future-only nullable target labels and purged temporal-trip
  split. Missing target observations remain `has_target=false / value=None`. Seat
  thresholds and the canonical ordinal training class (0, 1–2, 3–5, >5 seats) are
  derived from the same first future observation, are all-present or all-missing,
  and cannot be constructed with inconsistent timestamps or nesting.
- `routing_worker.feature_builder`: the single versioned ETA/Seat feature builder for training and
  serving plus content-addressed dataset snapshot metadata. Each family consumes its
  own public Bus-core context builder/policy at an explicit timezone-aware `query_at`;
  future, stale, schema-mismatched, and absent context stays null with flags, while
  observed numeric zero and `False` remain observed values.
- `routing_worker.data_quality.quality_gate`: duplicate, clock, lag, station sequence, and ETA/Seat label
  coverage gates. Any failed period has `training_eligible=false`.
- `routing_worker.data_quality.postgres_adapter`: injected-clock lineage and quality sinks backed
  by the durable Routing worker repository.

No legacy database or production dataset is bundled, so this code does not claim a
completed migration or adequate route/date/positive-label coverage. KMA/GITS context
presence in the schema does not claim live collection, corridor aggregation, feature
value, trained-model adoption, or production capability.

Files beside this README retain import compatibility for repository-local legacy
commands and tests only; the installable implementation is the `routing_worker`
package and is included in the worker wheel.
