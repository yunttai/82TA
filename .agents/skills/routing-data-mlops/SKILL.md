---
name: routing-data-mlops
description: "BusCrowdRisk legacy SQLite 감사·PostgreSQL/PostGIS migration, collector·checkpoint·data quality, trip/label/feature dataset, ETA·Seat LightGBM, calibration·interval, model registry·artifact integrity·shadow·canary·rollback을 구현한다. 데이터·ML·모델 운영 작업 시 사용한다."
---

# Routing Data and MLOps

## 공통 사전 조건

작업을 시작하기 전에 반드시 다음을 수행한다.

1. `python src/scripts/validate_repository.py`를 실행한다.
2. `python src/scripts/verify_contract_lock.py`를 실행한다.
3. `src/contracts/CONTEXT_MANIFEST.json`과 `src/contracts/CONTRACT_LOCK.json`을 읽는다.
4. `src/docs/shared/PROJECT_CONTEXT.md`, `PRD.md`, 관련 canonical 계약을 읽는다.
5. 이전 `_workspace/` 산출물이 있으면 미완료·피드백·차단 사항을 확인한다.

검증 실패 시 구현을 진행하지 않는다. 공통 원본을 임의로 맞춰 쓰지 말고 drift 또는 change request로 처리한다.

## 저장 위치 규칙

- 분석·토론·중간 결과: `_workspace/{workstream}/`
- 검토가 끝난 제품 코드·문서·테스트·인프라: 반드시 `src/` 아래
- 루트에는 `.codex/`, `.agents/`, `_workspace/`, `src/`, `AGENTS.md`, `README.md`, `.gitignore`만 둔다.
- 공통 PRD·OpenAPI·ERD·enum 복사본을 workstream 폴더에 만들지 않는다.


## 데이터 원칙

- observed/valid/ingested time을 분리한다.
- trip identity로 인접 snapshot leakage를 차단한다.
- target 관측이 없으면 NULL/has_target=false다.
- train/serve feature builder와 schema version을 공유한다.
- Provider 저장 약관을 넘는 raw data를 보관하지 않는다.

## 워크플로우

1. legacy inventory·hash·row count·coverage·diagnostics를 고정한다.
2. canonical route/stop/trip/observation으로 migration한다.
3. idempotent collector/checkpoint/partition과 quality gate를 구현한다.
4. target·feature schema와 dataset snapshot을 버전화한다.
5. temporal/trip split로 ETA·Seat baseline을 학습한다.
6. ETA interval과 Seat calibration을 평가한다.
7. artifact metadata/schema/hash/model card를 등록한다.
8. VALIDATED→SHADOW→CANARY→ACTIVE lifecycle과 rollback을 구현한다.
9. delayed label·drift·slice metric을 모니터링한다.

## Release evidence

- label coverage/positive rate
- ETA MAE/P90/interval coverage
- Seat PR-AUC/Brier/ECE/reliability
- route/time/sequence slices
- inference latency
- artifact integrity and rollback test
