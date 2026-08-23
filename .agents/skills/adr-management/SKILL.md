---
name: adr-management
description: "Budget Route Platform의 아키텍처·서비스 경계·계약·DB 소유권·모델·Provider·보안 결정과 변경 사유를 ADR로 기록한다. 공통 의미 변경, 경계 변경, 새 Provider·DB·배포 전략, 기존 결정 철회 요청 시 반드시 사용한다."
---

# ADR Management

되돌리기 어려운 결정의 맥락·대안·영향·마이그레이션을 `src/docs/adr/`에 기록한다.

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


## ADR이 필요한 경우

- Public/Private API 의미 또는 major compatibility 변경
- Service와 Routing 책임·DB 소유권 변경
- 신규 Provider가 primary/fallback이 되는 결정
- 데이터 보존·위치정보·인증 정책 변경
- 모델 target·artifact·activation 정책 변경
- 두 Django 서비스를 합치거나 더 분리
- 루트 `src-only` 예외
- AWS 핵심 배포 전략 변경

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
3. 최소 두 대안을 비교한다.
4. consumer·producer·DB·운영·보안 영향을 명시한다.
5. Proposed ADR을 만들고 승인 전 구현을 강제하지 않는다.
6. Accepted 후 계약·문서·테스트·lock 변경과 연결한다.
7. 철회 시 파일 삭제가 아니라 상태와 superseding ADR을 기록한다.

## 출력

- 최종 ADR: `src/docs/adr/NNNN-*.md`
- 임시 논의: `_workspace/integration/`

## 테스트 시나리오

신규 third-party transit provider를 primary로 변경 → latency·ID·저장약관·fallback·migration을 포함한 ADR 생성.
