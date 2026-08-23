---
name: platform-release-gate
description: "Budget Route Platform의 integration, staging, beta, GA 릴리스 가능 여부를 공통 PRD·계약·보안·성능·데이터·모델·복구 evidence로 판정한다. 배포 승인, 버전 출시, 두 하네스 합류, GA 준비 요청 시 반드시 사용한다."
---

# Platform Release Gate

기능이 보인다는 이유만으로 출시하지 않고 `src/docs/shared/RELEASE_GATES.md`의 evidence를 검증한다.

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


## 입력

- target stage: Foundation, Alpha, Model Alpha, Beta, GA
- Service와 Routing release evidence
- integration QA report
- SLO·provider·model·privacy·DR 상태

## 워크플로우

1. 두 context snapshot hash 비교
2. contract and migration compatibility
3. requirements traceability completeness
4. Service·Routing·integration test
5. P95 7초·candidate/API cost bounds
6. Provider production approval·quota·fallback
7. mapping precision·model calibration·coverage
8. WAF/rate limit/secrets/privacy/delete
9. backup/restore/model rollback/provider outage runbook
10. known risk의 feature flag·owner·deadline

## 출력

- `GO`, `CONDITIONAL_GO`, `NO_GO`, `UNVERIFIED`
- 각 gate의 evidence 링크
- rollback target
- disabled capability 목록
- 다음 재평가 조건

최종 report는 `src/tests/integration/reports/` 또는 `src/docs/releases/` 아래에 둔다.
