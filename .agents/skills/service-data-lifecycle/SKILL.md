---
name: service-data-lifecycle
description: "Service DBML을 Django model·migration·repository로 구현하고 사용자 계정·정확한 위치·저장 장소·검색 이력·동의·피드백의 보존, 삭제, export, audit를 설계·검증한다. Service DB·migration·privacy data 작업 시 사용한다."
---

# Service Data Lifecycle

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


## 규칙

- 원본은 `src/contracts/database/service-db.dbml`이다.
- Routing DB entity·FK·query를 만들지 않는다.
- 저장 장소와 이동 관계는 고민감 데이터다.
- null, soft delete, hard delete, backup retention을 구분한다.

## 워크플로우

1. DBML entity와 Django model mapping 표를 만든다.
2. key·unique·check·index·FK·ownership을 구현한다.
3. expand/contract migration과 rollback을 작성한다.
4. guest/user ownership과 IDOR 방어를 테스트한다.
5. retention job, delete orchestration, export를 구현한다.
6. cache·analytics·backup에서 삭제가 반영되는 정책을 연결한다.
7. public snapshot 금지 필드를 검사한다.
8. migration·data lifecycle QA를 요청한다.

## 출력

- 코드/migration: `src/services/service-api/**`
- privacy/runbook 변경: 관련 `src/docs/` 또는 `src/tests/`
- DBML 의미 변경은 governance 전용
