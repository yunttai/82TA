---
name: route-optimizer-delivery
description: "순수 Python routing domain에서 허용 멀티모달 패턴, bounded candidate generation, leg-entry-time 기반 cost, taxi strict budget, transfer feasibility, Pareto/epsilon dominance, FASTEST·STABLE·EFFICIENT·PUBLIC_TRANSIT_ONLY ranking을 구현·검증한다. 경로 알고리즘 작업 시 사용한다."
---

# Route Optimizer Delivery

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


## Domain Independence

`src/packages/routing-domain`은 Django request·ORM·settings·Provider raw JSON을 import하지 않는다. 입력은 canonical typed object와 clock/policy/model result다.

## 워크플로우

1. route pattern과 candidate bound를 설정한다.
2. transit baseline, access/egress hub, upstream, Taxi Bridge 후보를 생성한다.
3. coarse lower bound로 pruning한다.
4. 상위 후보만 exact taxi/walk/mapping/bus enrichment한다.
5. 각 leg 진입시각으로 뒤 leg를 재평가한다.
6. taxi dispatch wait와 upper fare를 별도 component로 합산한다.
7. transfer P50/P90 margin을 평가한다.
8. strict feasibility 후 Pareto/epsilon pruning한다.
9. four recommendations와 reason code를 생성한다.
10. deterministic replay와 property test를 작성한다.

## 필수 불변식

- `taxiCost.upper <= budget`
- `P90 >= P50`
- leg time non-decreasing
- 사용자 도착 전 버스 제외
- 일반버스 crowded를 기본 승차 실패 penalty로 사용하지 않음
- frontier에 완전 지배 후보 없음
- candidate/provider call 상한 존재
