# `src/` — 제품 원본 영역

이 디렉터리는 실제 제품을 구성하는 모든 산출물의 유일한 저장 위치다.

## 구조

```text
src/
├─ apps/
│  └─ web/                         React Web App / PWA
├─ services/
│  ├─ service-api/                 Django 사용자 서비스 API
│  └─ routing-api/                 Django 비공개 Routing API
├─ packages/
│  ├─ routing-domain/              Django 독립 순수 라우팅 도메인
│  ├─ bus-intelligence-core/       ETA·좌석·실질 대기 계산
│  ├─ provider-core/               Provider Adapter 계약과 공통 정책
│  └─ observability/               로그·추적·메트릭 규칙
├─ workers/
│  ├─ transport-collector/         GBIS·KMA·GITS 수집
│  ├─ data-quality/                품질 검사
│  └─ model-jobs/                  학습·평가·등록
├─ contracts/                      두 하네스가 공유하는 계약 원본
├─ docs/                           PRD·ERD·ADR·Runbook
├─ infra/                          AWS·CI/CD·컨테이너·IaC
├─ tests/                          Contract·Integration·Replay·E2E·Harness eval
├─ scripts/                        저장소·계약·하네스 검증 도구
├─ generated/                      계약에서 생성된 client·DTO
└─ ops/                            저장소 운영 템플릿
```

## 소유권

| 영역 | 기본 소유자 | 상대 작업흐름 접근 |
|---|---|---|
| `apps/web` | Service Product | 읽기 가능, 수정은 공동 요청 필요 |
| `services/service-api` | Service Product | 읽기 가능 |
| `services/routing-api` | Routing & Intelligence | 읽기 가능 |
| `packages/routing-domain` | Routing & Intelligence | 읽기 가능 |
| `packages/bus-intelligence-core` | Routing & Intelligence | 읽기 가능 |
| `packages/provider-core` | Routing & Intelligence | 읽기 가능 |
| `contracts` | 공동 | 양쪽 승인 필수 |
| `docs/shared` | 공동 | 양쪽 승인 필수 |
| `infra`, `tests/integration` | 공동 | 양쪽 승인 필수 |

## 금지

- 루트에 `frontend/`, `backend/`, `api/`, `docs/`, `infra/`, `tests/`를 새로 만들지 않는다.
- 각 하네스에 공통 DTO·OpenAPI·ERD 복사본을 만들지 않는다.
- 상대 서비스 DB를 직접 조회하는 코드나 ORM 모델을 만들지 않는다.
- Provider raw response 타입을 Service Product 영역으로 누출하지 않는다.


## 실행 진입점

```bash
python src/scripts/validate_repository.py
python src/scripts/snapshot_context.py service-product
python src/scripts/snapshot_context.py routing-intelligence
python src/scripts/compare_context_snapshots.py
```

실제 구현은 각 workstream `SOURCE_LAYOUT.md`와 오케스트레이터를 따른다.
