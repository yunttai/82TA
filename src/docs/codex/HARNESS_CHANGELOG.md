# Harness Changelog

## 2026-08-25 — current implementation first

- 현재 source, tests, migrations, active deployment workflow를 maintenance baseline으로 정의했다.
- GCE를 유일한 cloud compute 기준으로 고정하되 exact managed-service topology와 production readiness는 구현 evidence 없이 강제하지 않게 했다.
- `_workspace`와 context snapshot을 선택적·gitignored 진단 자료로 내렸다.
- snapshot 기본 동작을 timestamp 누적에서 단일 `00_context_snapshot_current.json` overwrite로 바꿨다.
- parity 검사를 오래된 snapshot 비교에서 live verified `CONTRACT_LOCK.json` 비교로 바꿨다.
- custom agent path를 standing ownership이 아닌 expertise hint로 정의하고, routine role effort와 concurrency 기본값을 낮췄다.
- contract governance를 전 artifact 일괄 변경에서 실제 영향면 기반 변경으로 전환했다.
- routine patch, boundary change, integration/release의 완료·QA gate를 분리했다.
- filesystem의 agent/skill을 active source로 삼고 locked v1 registry를 historical/non-authoritative record로 내렸다.
- skill eval metadata의 문자열 존재가 아니라 trigger matrix의 positive/negative coverage를 검증하게 했다.
- `.github`와 conventional repository control을 source-layout 정책에 맞게 허용했다.
- 초기 copy-paste prompt 39개와 과거 alignment/validation 기록을 historical reference로 표시했다.
- product source, business contracts, migrations, infrastructure implementation은 변경하지 않았다.

### Linked Routing task conflict follow-up

- 구현 요청을 audit/plan/CCR/ADR/release verdict로 대체하지 못하도록 implementation-first 규칙을 추가했다.
- CodeGraph discovery를 affected call path 한 번으로 제한하고 continuation에서 unchanged findings와 green evidence를 재사용하게 했다.
- focused task의 agent fan-out을 primary 또는 최대 한 implementer + 한 reviewer로 제한하고 기본 동시성 상한을 2로 낮췄다.
- Routing, Service, integration test를 owner runtime별로 분리하고 mixed test tree collection과 slice마다 반복되는 full suite를 금지했다.
- auth/schema/artifact/strict-feasibility fail-closed와 optional exactification/enrichment의 candidate-drop/PARTIAL/no-feasible semantics를 분리했다.
- live Provider key·approval 부재가 pure-domain/fixture algorithm 구현을 막지 않도록 했다.
- 내부 graph completeness, cache, provider-call accounting 변화가 public 의미를 바꾸지 않으면 contract/ADR 작업을 자동 유발하지 않게 했다.
- ordinary implementation 보고에서 `GO`/`NO_GO`를 금지하고 explicit deployment/release gate에만 남겼다.

### Focused Service task bottleneck follow-up

- 기존 production path에 대응하는 가장 좁은 요청 slice를 기본값으로 삼고, 인접 기능의 미결정을 blocker가 아닌 out-of-scope/TBD로 처리하게 했다.
- rate-limit/idempotency Redis coordination이 Kakao Local·Routing Provider 응답 캐싱, TTL·약관·좌표 key 정책, cloud rollout을 자동 요구하지 않게 했다.
- `src/infra/**` 등 shared path 자체의 승인 gate를 없애고 현재 diff와 active writer의 실제 overlap만 조율하게 했다.
- working PR CI 요청에서 repository-local workflow 활성화를 routine implementation으로 분류하고, secret·permission·배포·비용·외부 상태 변화에만 추가 권한을 요구하게 했다.
- local/PR-CI/GCE 완료 증거를 분리하고 제거된 AWS·ElastiCache 경로가 질문이나 선행조건으로 되살아나지 않게 했다.
- 사용자가 속도·최소 검증을 명시하면 변경된 경계와 실제로 유발된 필수 안전·계약 검사만 수행하게 했다.
- Redis coordination dry-run과 narrow-scope/shared-path 구조 assertion을 추가했다.
