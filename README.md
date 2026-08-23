# 82TA

경기 남부↔서울의 예산 제약형 실시간 복합교통 경로 추천 제품을 두 작업흐름으로 개발하면서, OpenAPI·ERD·DBML·용어·코드·컨텍스트를 동일하게 유지하는 Codex용 하네스다.

## 작업흐름

1. **Service Product** — React Web/PWA + Django Service Backend
2. **Routing & Intelligence** — Provider, Mapping, Bus Intelligence, ETA, Optimizer, Data/ML

제품 기준은 React, Django, AWS, one monorepo/two deployable units, `POST /v1/routes/optimize`, P95 7초다.

## Codex 제어층

```text
AGENTS.md                  루트 저장소 지시
src/**/AGENTS.md           경로별 범위 지시
.codex/config.toml         프로젝트 Codex 설정
.codex/agents/*.toml       프로젝트 custom subagents
.agents/skills/*/SKILL.md  재사용 워크플로
_workspace/                WORKPLAN/STATUS/HANDOFF/evidence
```

Claude 전용 `CLAUDE.md`, `.claude/agents`, `.claude/skills`, TeamCreate/TaskCreate/SendMessage 전제를 사용하지 않는다.

## 시작

```bash
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
```

Codex에서 처음 열면 `src/docs/codex-prompts/00_REPOSITORY_ORIENTATION.md`의 프롬프트를 붙여넣는다.

## 주요 프롬프트

- 1번 최초 시작: `01_WORKSTREAM1_INITIAL.md`
- 2번 최초 시작: `06_WORKSTREAM2_INITIAL.md`
- 최초 통합: `20_FIRST_INTEGRATION.md`
- 반복 통합: `21_REGULAR_INTEGRATION.md`
- 병합 준비: `22_MERGE_READINESS.md`
- 세션 이어하기: `32_SESSION_RESUME.md`
- 전체 복붙판: `ALL_COPY_PASTE_PROMPTS.md`

## 변경 범위

이번 Codex판은 애플리케이션 코드와 제품 계약을 변경하지 않는다. Codex 제어 파일, 하네스 문서, 프롬프트, 작업원장, 검증 스크립트, 컨텍스트 메타데이터만 변경한다. 자세한 증거는 `src/docs/codex/CODE_PRESERVATION_REPORT.md`를 본다.

## 문서

- `src/docs/codex/CODEX_RUNBOOK.md`
- `src/docs/codex/CLAUDE_TO_CODEX_MIGRATION.md`
- `src/docs/codex/CUSTOM_AGENT_MAP.md`
- `src/docs/codex/WORKTREE_AND_INTEGRATION.md`
- `src/docs/codex-prompts/PROMPT_INDEX.md`
