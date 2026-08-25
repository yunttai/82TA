# Claude 전용 하네스 → Codex 하네스 변환

> **Historical archive:** 초기 2026-08-22 변환 기록이다. 현재 운영 방식은 `CODEX_RUNBOOK.md`와 루트 `AGENTS.md`를 따른다. 아래 durable ledger, legacy cloud 보존, prompt-library 설명은 현재 gate가 아니다.

## 목표

제품 코드와 비즈니스 계약을 건드리지 않고, 실행 제어층만 Codex-native로 바꾼다.

## 대응표

| Claude 전용 요소 | Codex 대응 |
|---|---|
| `CLAUDE.md` | 루트·하위 `AGENTS.md` |
| `.claude/skills/*/SKILL.md` | `.agents/skills/*/SKILL.md` |
| `.claude/agents/*.md` | `.codex/agents/*.toml` |
| `model: opus` | `model_reasoning_effort`와 프로젝트 기본 설정 |
| TeamCreate | primary thread의 named subagent delegation |
| TaskCreate/TaskUpdate | `_workspace/*/WORKPLAN.md`의 durable task ledger |
| SendMessage | subagent return + primary-thread handoff + HANDOFF.md |
| TeamDelete | subagent 결과 수집 후 thread 종료/정리 |
| Claude team runtime 의존 | Codex primary thread + `/agent` inspection |
| 하네스 trigger | `$skill-name` 명시 호출 + AGENTS.md |

## 보존된 항목

- React/Django/GCE 제품 결정
- Service/Routing 책임 경계
- Public/Private OpenAPI
- Service/Routing DBML·ERD
- reason/warning/error registry
- Provider·Bus Intelligence·Optimizer 설계
- 제품 PRD와 acceptance
- `src/` 산출물 원칙

## 변경된 항목

- 활성 instruction paths
- custom agent format
- orchestrator coordination wording
- durable work ledgers
- Codex prompt library
- Codex-aware repository validation
- contextVersion 1.0.1; business contractVersion remains 1.0.0

## 의도적으로 하지 않은 것

- 애플리케이션 소스 구현/수정
- OpenAPI 비즈니스 필드 변경
- DBML/ERD 변경
- 모델 알고리즘 변경
- API Provider 역할 변경

## 검증

`CODE_PRESERVATION_REPORT.md`가 보호 대상 파일의 SHA-256 일치를 증명한다.
