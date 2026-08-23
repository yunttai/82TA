# Transport Collector

GBIS·KMA·GITS와 장기 학습 데이터 수집을 checkpoint 기반으로 수행한다. 온라인 API 요청과 분리한다.

## Offline-verifiable entry points

- `routing_worker.transport_collector.foundation`: versioned trip identity, observed/valid/ingested clocks,
  and monotonic idempotent checkpoints.
- `routing_worker.transport_collector.runtime`: quota reservation, freshness/schema validation, natural-key
  dedupe, sanitized DLQ, and an atomic `commit_batch` repository port.
- `routing_worker.transport_collector.postgres_adapter`: strict normalized ARRIVAL/LOCATION projection into
  the durable Routing-owned repository. Unknown/extra/raw fields fail before SQL;
  missing seats remain SQL `NULL`.

The in-memory quota implementation is deterministic test evidence, not a distributed
production quota. A deployed collector must implement the repository transaction and
shared quota atomically (for example, PostgreSQL plus Redis) and must use only
Provider operations that have reached `KEY_VERIFIED / PRODUCTION_APPROVED`.

Files beside this README retain import compatibility for repository-local legacy
commands and tests only; the installable implementation is the `routing_worker`
package and remains unscheduled/default-disabled.
