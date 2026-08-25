# Routing & Intelligence Harness Execution Playbook

## 시작 범위

1. 현재 Routing 구현, 적용되는 `AGENTS.md`, 영향받는 테스트를 먼저 본다.
2. 공유 API·데이터 의미가 바뀔 때만 manifest/lock과 관련 producer·consumer를 추가로 본다.
3. 호출 관계가 불명확하면 CodeGraph로 affected symbol/call path를 한 번 확인하고 바로 production path를 수정한다.
4. local fix는 직접 수행한다. 위임 요청 또는 진짜 독립 작업이 있을 때만 최대 한 implementation specialist와 한 reviewer에 non-overlapping scope를 배정한다.
5. snapshot, WORKPLAN, STATUS, HANDOFF는 장기·병렬 조율에 도움이 되거나 사용자가 요청했을 때만 쓴다.

Continuation에서는 관련 source가 그대로면 이미 확인한 call path, live lock, green test를 재사용한다. 새 turn이라는 이유만으로 audit, snapshot, ledger, full suite를 반복하지 않는다. 구현 요청을 계획·CCR/ADR·release 판정으로 대체하지 않는다.

## 의존 흐름

```text
capability/fixture
→ adapter/canonical normalization
→ mapping
→ optional Bus Intelligence
→ candidate/time/cost/feasibility/ranking
→ private API
→ affected replay/security/performance/integration
```

현재 작업이 닿는 구간만 실행·검증한다. 미구현 provider, mapping, ETA/Seat model을 routine 변경의 선행조건으로 만들지 않는다. 검증되지 않은 capability는 false/unsupported/PARTIAL로 유지한다.

Pure domain/fixture-backed optimizer 작업은 live Provider key나 production approval 없이 진행할 수 있다. Optional exactification/enrichment timeout은 affected candidate를 제외하거나 기존 fallback/PARTIAL/no-feasible 의미를 사용하며, auth·schema/artifact trust 또는 strict feasibility 인증 실패와 달리 자동 hard 504가 아니다.

반복 중에는 targeted Routing test를 실행하고 diff가 안정된 뒤 관련 aggregate suite를 한 번 실행한다. Routing suite는 Routing runtime, Service consumer suite는 Service runtime, 실제 cross-boundary suite는 준비된 integration runtime에서 실행한다. `src/tests/security` 또는 `src/tests/performance` 전체를 한 runtime에 무차별 수집하지 않는다.

Service와 실제 통합할 때는 live lock parity와 generated client를 확인하고, user identity 또는 cross-database access가 없는지 검증한다. Release 요청에서만 환경별 production approval, quota, SLO, model coverage, disaster recovery evidence를 모두 판정한다.

## 완료 보고

변경 파일, 실행한 checks, 관련 contract/capability/version, partial/fallback, known data/model gap, security/cost/rollback을 작업 규모에 맞게 기록한다. 일반 source 구현에는 `GO`/`NO_GO`를 붙이지 않는다.
