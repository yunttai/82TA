# Orchestrator Dry Runs

이 문서는 scope 판단 예시다. agent 위임이나 `_workspace` 기록 자체를 성공 조건으로 세지 않는다.

## DR-SVC-001 local UI/API patch

입력: `PARTIAL 결과 카드 문구와 projection bug를 고쳐줘`

예상:

1. 현재 component/projection과 nearby test를 읽는다.
2. 공유 field 의미가 그대로면 full PRD, DBML, snapshot을 요구하지 않는다.
3. primary가 직접 수정하고 targeted Frontend/Service test를 실행할 수 있다.
4. browser→Service→Routing 경계와 unknown/PARTIAL 의미는 보존한다.

## DR-SVC-002 shared API addition

입력: `PlaceRef에 backward-compatible 표시 field를 추가해줘`

예상: 관련 OpenAPI, example, generated client, producer/consumer test, changelog, lock만 영향 검토한다. persistence/event/code 영향이 없다면 DBML·event·registry는 바꾸지 않는다.

## DR-RT-001 isolated optimizer fix

입력: `taxi upper-cost 합산 bug를 수정해줘`

예상: routing-domain과 관련 property/replay만 수정·검증한다. Provider, mapping, ETA/Seat model, Service UI, WORKPLAN은 선행조건이 아니다.

## DR-RT-002 unverified provider

Provider live approval이 없음 → fixture 기반 adapter 작업은 가능하지만 capability는 false/unsupported/PARTIAL이다. 그 provider를 요구하지 않는 source merge는 가능하고 production claim만 `UNVERIFIED`다.

## DR-RT-003 implementation beats audit

입력: `감사 그만하고 실제 graph/time-dependent optimizer를 구현해줘`

예상:

1. affected production symbol/call path를 CodeGraph로 최대 한 번 확인한다.
2. architecture audit, CCR/ADR, release agent를 자동 호출하지 않는다.
3. 실패 counterexample/property test와 실제 구현을 만든다.
4. 일반 구현 보고에 `GO`/`NO_GO`를 붙이지 않는다.

## DR-RT-004 continuation evidence reuse

입력: `방금 구현한 optimizer를 이어서 다음 gap을 고쳐줘`; 관련 source·contract·dependency hash는 이전 green run 이후 그대로다.

예상: 기존 call-path 조사, lock 검증, 통과 suite를 재사용한다. snapshot, WORKPLAN/STATUS/HANDOFF, repository audit와 같은 suite를 새 turn이라는 이유로 다시 실행하지 않는다. 새 diff의 targeted test와 마지막 affected aggregate만 실행한다.

## DR-RT-005 optional exact deadline

입력: 선택적 exact taxi enrichment가 deadline을 초과하지만 다른 canonical 후보는 유효하다.

예상: affected candidate를 제외하거나 현재 contract의 fallback/PARTIAL을 반환한다. 보안 `fail closed`를 이유로 전체 요청을 자동 504로 바꾸지 않는다. Auth/schema/artifact 또는 strict feasibility 인증 실패는 별도로 fail closed다.

## DR-RT-006 offline algorithm without provider keys

입력: live Provider key가 없는 환경에서 canonical fixture 기반 graph search를 구현해줘.

예상: pure routing-domain 구현과 deterministic property/replay를 진행한다. Live adapter smoke와 production capability만 `UNVERIFIED`로 남고 알고리즘 구현은 block하지 않는다.

## DR-RT-007 owner-specific test runtimes

입력: optimizer/API 변경 후 security·performance regression을 확인해줘.

예상: Routing-owned test path는 Routing runtime에서 실행하고 Service-only path는 Service runtime에서 별도 실행한다. 하나의 environment로 혼합 `src/tests/security/**` 또는 `src/tests/performance/**` 전체를 수집해 collection failure를 만들지 않는다. 명시적 load/release 요청이 아니면 10/50/100 전체 benchmark를 강제하지 않는다.

## DR-RT-008 bounded delegation

입력: 한 production optimizer gap과 독립 review 하나를 처리해줘.

예상: primary가 직접 처리하거나, 사용자가 위임을 요청했다면 최대 한 implementer와 한 reviewer에 non-overlapping scope를 준다. Provider·mapping·model·architecture·contract·release 역할 전체를 fan-out하지 않는다.

## DR-INT-001 parity

서로 다른 worktree 통합 → 각 root의 `CONTRACT_LOCK.json`을 먼저 검증한 뒤 직접 비교한다. timestamp snapshot의 나이·순서를 신뢰하지 않는다.

## DR-ARCH-001 GCE-only deployment decision

GCE가 유일한 지원 cloud compute platform임을 확인한다. 다른 cloud 경로 추가는 ADR-0012를 대체하는 명시적 architecture decision 없이는 수행하지 않는다. 단, 하네스는 현재 단일 VM이나 특정 Google managed service 조합을 영구 topology로 강제하지 않는다.

## DR-GOV-001 internal algorithm is not a contract change

입력: response shape·unit·status/error 의미는 그대로이고 내부 provider call count와 graph completeness만 바뀐다.

예상: local implementation/test로 처리한다. speculative field, CCR/ADR, OpenAPI/DBML/event/code registry, contract lock 갱신을 요구하지 않는다.

## DR-LAYOUT-001 repository automation

`.github/workflows/cd-gce.yml` → 허용. 루트 `frontend/` 제품 구현 → FAIL하고 `src/apps/web/` 배치를 요구한다.
