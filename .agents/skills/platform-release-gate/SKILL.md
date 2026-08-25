---
name: platform-release-gate
description: "Budget Route Platform의 명시적인 integration 환경 배포, staging, beta, GA 릴리스 가능 여부를 환경별 계약·보안·성능·데이터·모델·복구 evidence로 판정한다. 일반 소스 병합이나 로컬 수정에는 사용하지 않는다."
---

# Platform Release Gate

명시적으로 요청된 배포 단계에 대해 현재 구현과 `src/docs/shared/RELEASE_GATES.md`의 해당 evidence를 검증한다. 목표 아키텍처 문구만으로 현재 GCE 배포를 AWS로 바꾸거나 환경을 production-ready라고 승격하지 않는다.

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


## 입력

- target stage: Foundation, Alpha, Model Alpha, Beta, GA
- Service와 Routing release evidence
- integration QA report
- SLO·provider·model·privacy·DR 상태

## 워크플로우

1. 두 live verified contract lock 비교
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

최종 report는 요청된 릴리스에서 필요할 때 `src/tests/integration/reports/` 또는 `src/docs/releases/` 아래에 둔다. 이 판정은 일반 source merge gate가 아니다.
