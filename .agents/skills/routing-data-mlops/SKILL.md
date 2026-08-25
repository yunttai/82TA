---
name: routing-data-mlops
description: "BusCrowdRisk legacy SQLite 감사·PostgreSQL/PostGIS migration, collector·checkpoint·data quality, trip/label/feature dataset, ETA·Seat LightGBM, calibration·interval, model registry·artifact integrity·shadow·canary·rollback을 구현한다. 데이터·ML·모델 운영 작업 시 사용한다."
---

# Routing Data and MLOps

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


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
