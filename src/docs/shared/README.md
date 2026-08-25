# Shared Source of Truth

두 하네스가 반드시 같은 컨텍스트를 사용하도록 공통 문서를 한 곳에만 둔다.

## 읽기 순서

1. `PROJECT_CONTEXT.md` — 제품 맥락·확정값·책임 경계
2. `PRD.md` — 기능·비기능 요구사항과 비즈니스 규칙
3. `GLOSSARY.md` — 공통 용어·단위·상태
4. `CONTEXT_MAP.md` — 두 bounded context와 데이터 소유권
5. `SYSTEM_ARCHITECTURE.md` — 전체 구성·요청 흐름·배포 단위
6. `ERD.md` — Service DB와 Routing DB
7. `API_CONTRACT_GUIDE.md` — Public·Private API 규칙
8. `DATA_MODEL_AND_OWNERSHIP.md` — canonical model·저장 원칙
9. `REQUIREMENTS_TRACEABILITY.md` — PRD→계약→구현→테스트 추적
10. `DECISION_AND_CHANGE_CONTROL.md` — 공통 변경·호환성·drift 절차
11. `NON_FUNCTIONAL_REQUIREMENTS.md` — 성능·가용성·확장성
12. `SECURITY_PRIVACY.md` — 위치·계정·모델·비용 공격 통제
13. `TEST_ACCEPTANCE.md` — 검증 계층과 GA 수용 기준
14. `PROVIDER_CAPABILITY_MATRIX.md` — 외부 API 역할·검증 상태
15. `INTEGRATION_PLAYBOOK.md` — 두 작업흐름 합류 절차
16. `RELEASE_GATES.md` — Foundation·Alpha·Beta·GA·V2 gate
17. `SOURCE_LAYOUT_POLICY.md` — 모든 제품 산출물의 `src/` 배치 규칙
18. `GCE_DEPLOYMENT.md`, `OBSERVABILITY_RUNBOOKS.md` — 배포·관측성 기준

기계 판독 계약은 `src/contracts/`에 있다. 공통 파일 목록과 SHA-256은 `src/contracts/CONTEXT_MANIFEST.json`, `src/contracts/CONTRACT_LOCK.json`에서 관리한다.

## 변경 원칙

- workstream별 복사본 금지
- ADR와 compatibility 검토
- producer·consumer contract test
- 양쪽 QA 승인
- 마지막에 version·changelog·contract lock 갱신
