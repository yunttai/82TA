# Codex 실행 Runbook

## 1. Codex가 읽는 것

### 저장소 지시

- 루트 `AGENTS.md`
- 현재 작업 파일까지 경로상 존재하는 하위 `AGENTS.md`
- 하위 지시가 해당 subtree에 더 구체적으로 적용된다.

### 스킬

- 저장소의 `.agents/skills/<skill>/SKILL.md`
- 명시적으로 `$service-product-orchestrator`처럼 호출한다.

### 프로젝트 custom subagents

- `.codex/agents/*.toml`
- primary thread에 “다음 custom subagents에 독립 작업을 위임하라”고 명시한다.
- `/agent`로 실행 중인 subagent를 확인·전환한다.

## 2. 최초 실행

```bash
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
```

그 뒤 `src/docs/codex-prompts/00_REPOSITORY_ORIENTATION.md`를 붙여넣는다.

## 3. 두 사람 병렬 개발

권장:

```text
worktree/service-product
worktree/routing-intelligence
worktree/integration
```

각 worktree에서 해당 시작 프롬프트를 사용한다. 공통 계약은 별도 contract branch/PR로만 변경한다.

## 4. 작업 상태

각 세션은 대화 컨텍스트가 아니라 다음 파일을 기준으로 이어간다.

```text
_workspace/service-product/WORKPLAN.md
_workspace/service-product/STATUS.md
_workspace/service-product/HANDOFF.md
_workspace/routing-intelligence/WORKPLAN.md
_workspace/routing-intelligence/STATUS.md
_workspace/routing-intelligence/HANDOFF.md
_workspace/integration/WORKPLAN.md
```

## 5. 1번 시작

`01_WORKSTREAM1_INITIAL.md` 사용.

핵심:

- Service 소유 경로만 수정
- canonical Stub/Replay로 독립 개발
- browser→Service only
- Service→RoutingGateway only
- GBIS/Mobility/Model orchestration 금지

## 6. 2번 시작

`06_WORKSTREAM2_INITIAL.md` 사용.

핵심:

- capability/fixture→Adapter→Mapping→Bus Intelligence→Optimizer→API
- 사용자 identity 금지
- missing=0 금지
- strict taxi upper budget
- deterministic replay

## 7. 통합

1. 양쪽 handoff 작성
2. `17_CONTEXT_SYNC.md`
3. 최초라면 `20_FIRST_INTEGRATION.md`, 이후에는 `21_REGULAR_INTEGRATION.md`
4. `22_MERGE_READINESS.md`
5. context snapshot parity 확인

## 8. 계약 변경

- 아이디어만: `13_CONTRACT_CHANGE_PROPOSAL.md`
- 사용자 승인 뒤: `14_APPLY_APPROVED_CONTRACT_CHANGE.md`
- DB: `15_DATABASE_SCHEMA_CHANGE.md`
- Reason/Warning/Error: `16_CODE_REGISTRY_CHANGE.md`

공통 계약 변경 전에 lock을 갱신하지 않는다.

## 9. 새 세션

`32_SESSION_RESUME.md` 사용. Codex에게 이전 대화를 기억한다고 가정하지 말고 AGENTS, contracts, workspace, branch diff를 읽게 한다.

## 10. 완료 보고 형식

- 실제 선택 task/subagent
- 변경 파일
- product/contract 영향
- tests/evidence
- capability/model/data state
- unresolved BLOCKED/UNVERIFIED
- rollback
- context parity
- 다음 추천 프롬프트
