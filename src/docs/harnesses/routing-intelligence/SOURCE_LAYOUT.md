# Routing & Intelligence Source Layout

## 최종 쓰기 범위

```text
src/services/routing-api/
src/packages/routing-domain/
src/packages/provider-core/
src/packages/bus-intelligence-core/
src/workers/
src/docs/harnesses/routing-intelligence/
src/tests/contracts/
src/tests/integration/
src/tests/replay/
src/tests/performance/
src/tests/security/
```

## Django private API

```text
src/services/routing-api/
├─ manage.py
├─ pyproject.toml
├─ config/
├─ routing_interface/         DRF request/response/auth/deadline
├─ application/               use-case orchestration and ports
├─ transport_mapping/         repository/application adapters
├─ model_registry/            activation/admin integration
├─ provider_admin/
└─ tests/
```

## 순수 Python package

```text
src/packages/routing-domain/
├─ routing_domain/
│  ├─ model/
│  ├─ candidate/
│  ├─ time_cost/
│  ├─ transfer/
│  ├─ pareto/
│  ├─ ranking/
│  └─ ports/
└─ tests/

src/packages/provider-core/
├─ provider_core/
│  ├─ protocols/
│  ├─ envelope/
│  ├─ canonical/
│  ├─ resilience/
│  ├─ cache/
│  └─ adapters/
└─ tests/

src/packages/bus-intelligence-core/
├─ bus_intelligence/
│  ├─ observations/
│  ├─ trip_identity/
│  ├─ features/
│  ├─ eta/
│  ├─ seat_risk/
│  ├─ expected_wait/
│  ├─ confidence/
│  └─ ports/
└─ tests/
```

순수 package는 Django ORM·request·settings와 Provider raw response를 import하지 않는다.

## Worker

```text
src/workers/
├─ transport-collector/
├─ data-quality/
└─ model-jobs/
```

online API에서 학습·대규모 materialization을 수행하지 않는다.

## 금지

- 사용자 account·saved place·history model
- Service DB 직접 조회
- Frontend presentation contract 설계
- raw Provider JSON을 routing domain에 전달
- model pickle path를 request로 수신
