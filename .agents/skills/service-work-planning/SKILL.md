---
name: service-work-planning
description: "공통 PRD를 React Web/PWA와 Django Service Backend의 구현 slice, dependency, acceptance, mock, security, QA 작업으로 분해한다. Service Product 기능 기획·백로그·작업 배정·부분 재실행 요청 시 사용한다."
---

# Service Work Planning

Service 범위만 계획하며 Routing 알고리즘을 Service 작업으로 가져오지 않는다.

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


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
