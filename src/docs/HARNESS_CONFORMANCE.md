# revfactory/harness 적용 대응표

> **Historical conformance archive:** 초기 하네스 구축 당시 대응표다. 현재 active harness는 위임·workspace·snapshot을 선택 사항으로 두고 task-specific scope와 proportionate checks를 사용한다.

이 패키지는 `revfactory/harness`의 팀 아키텍처·에이전트·스킬·오케스트레이터 원칙을 프로젝트에 맞게 적용한다.

| Harness Phase | 이 패키지의 구현 |
|---|---|
| Phase 0 현황 감사 | 두 오케스트레이터 Phase 0, `harness-evolution` |
| Phase 1 도메인 분석 | 공통 PROJECT_CONTEXT/PRD와 workstream PRD |
| Phase 2 팀 아키텍처 | Service 팀과 Routing 팀을 별도 agent team으로 구성 |
| Phase 3 에이전트 정의 | `.codex/agents/*.toml` 18개 |
| Phase 4 스킬 생성 | 25개 orchestrator·shared·delivery·governance skills |
| Phase 5 오케스트레이션 | named subagent delegation·WORKPLAN·workspace·handoff·error flow |
| Codex instruction pointer | 루트 `AGENTS.md`의 trigger와 change history |
| Phase 6 검증 | trigger eval, repository/lock, incremental QA, dry run |
| Phase 7 진화 | `harness-evolution`, workspace audit, change history |

## 프로젝트 전용 변형

원본 Harness는 프로젝트 산출물 위치를 도메인에 맞게 정한다. 이 프로젝트에서는 사용자의 요구에 따라:

- Harness 제어: `.codex/ 및 .agents/`, `_workspace/`, `AGENTS.md`
- 모든 최종 제품 원본: `src/`

으로 강제한다.

## 두 하네스가 같은 컨텍스트를 유지하는 장치

1. 단일 `src/docs/shared`
2. 단일 `src/contracts`
3. `CONTEXT_MANIFEST.json`
4. SHA-256 `CONTRACT_LOCK.json`
5. `shared-contract-governance`
6. producer/consumer `integration-coherence-qa`
7. workstream machine contract 복사 금지 검증

따라서 각 작업흐름은 독립 실행되지만 API·ERD·DTO·단위·code·DB 소유권은 같은 원본을 사용한다.
