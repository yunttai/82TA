---
name: service-data-lifecycle
description: "Service DBML을 Django model·migration·repository로 구현하고 사용자 계정·정확한 위치·저장 장소·검색 이력·동의·피드백의 보존, 삭제, export, audit를 설계·검증한다. Service DB·migration·privacy data 작업 시 사용한다."
---

# Service Data Lifecycle

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


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
