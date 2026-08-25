# Codex 실행 Runbook

## 기본 원칙

Codex는 루트와 수정 경로의 `AGENTS.md`를 읽고, 현재 구현과 diff에서 시작한다. PRD·아키텍처·과거 snapshot은 해당 작업의 요구나 evidence일 때만 추가로 읽는다. 문서와 구현의 불일치는 자동 수정 지시가 아니다.

구현·bugfix·continuation 요청은 실제 구현을 결과로 내야 한다. 관계 확인이 필요하면 CodeGraph를 affected symbol/call path로 한 번 제한해 사용한 뒤 수정한다. Audit, plan, ADR/CCR, workspace 기록, release verdict는 요청된 구현을 대신하지 않는다.

## 작업 규모별 흐름

### Local patch

1. 영향받는 source와 nearby test 확인
2. 직접 수정
3. targeted test/lint/build
4. 실제 contract·security 영향과 known gap 보고

전체 repository 검증, snapshot, WORKPLAN, subagent, release gate는 필요하지 않다.

같은 task를 이어갈 때 관련 source·dependency가 그대로면 기존 call-path 조사와 green test를 재사용한다. Routing과 Service test는 각 runtime에서 실행하고, 반복 중 targeted check 후 안정된 diff에 대해 관련 aggregate suite를 한 번만 실행한다.

### Shared boundary

1. live manifest/lock과 관련 canonical artifact 확인
2. producer·consumer와 compatibility 영향 식별
3. 관련 OpenAPI/client/test, DBML/migration 또는 event/code만 갱신
4. affected contract/integration test와 lock 검증

CCR/ADR은 breaking 의미, DB/서비스 소유권, production cloud/provider 전략, privacy/security 정책처럼 되돌리기 어려운 결정에 사용한다.

### Integration or release

1. `python src/scripts/compare_context_snapshots.py`로 live lock parity 확인
2. 변경된 producer-consumer 경계와 대표 replay/E2E 확인
3. release에서 주장하는 capability에 한해 provider/model/performance/security/rollback evidence 확인

optional capability가 disabled/unsupported/PARTIAL이면 그 `UNVERIFIED` 상태는 무관한 source merge를 막지 않는다.

`GO`/`NO_GO`는 사용자가 deployment/release readiness를 요청한 경우에만 사용한다. 일반 구현 QA는 affected assertion과 regression만 보고한다.

## Agents and workspace

`.codex/agents/*.toml`은 전문 역할이다. 경로 목록은 소유권이 아니며, 실제 write scope는 각 task가 정한다. 독립 작업이 여러 개이거나 사용자가 요청했을 때만 위임하고, 같은 파일을 동시에 배정하지 않는다.

Focused task는 primary가 직접 수행하거나, 위임이 명시적으로 허용되고 유용할 때 최대 한 implementation specialist와 한 independent reviewer만 사용한다. Local implementation에 architecture/contract/integration/security/release role을 자동으로 붙이지 않는다.

`_workspace/`는 선택적·gitignored 메모다. 비어 있거나 오래되어도 정상이고, session resume는 git diff, current source, tests, live lock을 기준으로 한다.

## Context snapshot

```bash
# 명시적으로 필요할 때만 current 파일 갱신
python src/scripts/snapshot_context.py service-product

# 감사 이력이 꼭 필요할 때만 timestamp copy 추가
python src/scripts/snapshot_context.py service-product --archive

# 실제 parity는 live lock으로 확인
python src/scripts/compare_context_snapshots.py
```

## 완료 보고

변경 결과를 먼저 말하고, changed files, product/contract impact, 실행한 checks, known risk/TBD, rollback을 작업 규모에 맞게 보고한다.

## Routing failure/test 기준

- Auth, SSRF/schema trust, artifact integrity, strict feasibility 인증은 fail closed다.
- Optional exactification/enrichment timeout은 기존 candidate-drop/fallback/PARTIAL/no-feasible 의미를 따르며 blanket 504가 아니다.
- Live Provider key/approval 부재는 해당 production claim만 막고 offline domain/fixture 구현은 막지 않는다.
- Routing package/private API, Service consumer, cross-workstream tests는 각각 Routing, Service, prepared integration runtime에서 실행한다.
