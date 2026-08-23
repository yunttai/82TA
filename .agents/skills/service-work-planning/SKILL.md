---
name: service-work-planning
description: "공통 PRD를 React Web/PWA와 Django Service Backend의 구현 slice, dependency, acceptance, mock, security, QA 작업으로 분해한다. Service Product 기능 기획·백로그·작업 배정·부분 재실행 요청 시 사용한다."
---

# Service Work Planning

Service 범위만 계획하며 Routing 알고리즘을 Service 작업으로 가져오지 않는다.

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


## 절차

1. 요청을 PRD requirement ID와 Public/Private contract에 연결한다.
2. 사용자 journey 한 개를 vertical slice로 정한다.
3. UX, Public API, DB, Routing mock, Frontend, security, QA 작업으로 분해한다.
4. 각 task에 owner path, input contract, output, acceptance, test ID, dependency를 기록한다.
5. Routing 미완료 영역은 Stub/Replay contract로 대체한다.
6. 공통 변경 필요 시 구현 task를 만들지 않고 change request를 만든다.

## Task 형식

```yaml
id: SVC-...
requirementIds: []
ownerAgent: service-...
writePaths: []
readContracts: []
dependsOn: []
acceptance: []
tests: []
securityPrivacy: []
contractImpact: none|proposed
```

## 완료 조건

- Frontend와 Backend가 같은 example/DTO를 사용
- Routing 내부 세부사항이 task에 없음
- incremental QA가 module 완료 직후 배치됨
- final artifacts가 모두 `src/` 경로를 가짐
