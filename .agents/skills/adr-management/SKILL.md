---
name: adr-management
description: "Budget Route Platform의 되돌리기 어려운 아키텍처·서비스 경계·DB 소유권·모델·Provider·보안·production 배포 전략 결정을 ADR로 기록한다. 일반 구현 수정이나 문서와 구현의 단순 불일치에는 사용하지 않는다."
---

# ADR Management

되돌리기 어려운 결정의 맥락·대안·영향·마이그레이션을 `src/docs/adr/`에 기록한다.

Local implementation bugs, cache/layout cleanup, test expectation drift, current code-versus-old-document mismatch, and work that follows an accepted decision are not ADR work. Do not divert an implementation request into a proposed ADR when the code can proceed under the current boundary and semantics.

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


## ADR이 필요한 경우

- Public/Private API 의미 또는 major compatibility 변경
- Service와 Routing 책임·DB 소유권 변경
- 신규 Provider가 primary/fallback이 되는 결정
- 데이터 보존·위치정보·인증 정책 변경
- 모델 target·artifact·activation 정책 변경
- 두 Django 서비스를 합치거나 더 분리
- 루트 `src-only` 예외
- active production 배포 플랫폼 또는 핵심 배포 전략 변경

## 형식

```markdown
# ADR-NNNN: 제목

- 상태: Proposed | Accepted | Superseded | Rejected
- 날짜:
- 결정자:
- 관련 요구사항:
- 관련 계약:

## Context
## Decision
## Alternatives Considered
## Consequences
## Security / Privacy / Cost
## Migration and Rollback
## Verification
## Supersedes / Superseded By
```

## 절차

1. 다음 번호를 확인한다.
2. 사용자 요구와 현재 canonical contract의 충돌을 기술한다.
3. 의사결정에 실제로 존재하는 대안을 비교한다. 의미 없는 두 번째 대안을 채우기 위해 만들지 않는다.
4. consumer·producer·DB·운영·보안 영향을 명시한다.
5. 사용자가 ADR 기록을 요청했거나 요청한 구현을 막는 되돌리기 어려운 결정이 있을 때만 Proposed ADR을 만든다. 그 외 구현은 현행 결정 아래 계속한다.
6. Accepted 후 계약·문서·테스트·lock 변경과 연결한다.
7. 철회 시 파일 삭제가 아니라 상태와 superseding ADR을 기록한다.

## 출력

- 최종 ADR: `src/docs/adr/NNNN-*.md`
- 임시 논의: `_workspace/integration/`

## 테스트 시나리오

신규 third-party transit provider를 primary로 변경 → latency·ID·저장약관·fallback·migration을 포함한 ADR 생성. 기존 provider adapter의 timeout bug 수정 → ADR 없이 구현·검증.
