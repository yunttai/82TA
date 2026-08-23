# Harness Implementation Index

전체 설명: `src/docs/DUAL_HARNESS_FINAL_SPEC.md`

## 두 하네스

| 하네스 | 오케스트레이터 | 소유 |
|---|---|---|
| Service Product | `.agents/skills/service-product-orchestrator/SKILL.md` | React/PWA, Django Service, user data |
| Routing & Intelligence | `.agents/skills/routing-intelligence-orchestrator/SKILL.md` | Providers, mapping, routing, Bus/ML |

## 공통 잠금

- `src/contracts/CONTEXT_MANIFEST.json`
- `src/contracts/CONTRACT_LOCK.json`
- `shared-contract-governance`
- `integration-coherence-qa`

## 실행

```bash
python src/scripts/validate_repository.py
```

그 뒤 원하는 오케스트레이터를 트리거한다. 두 작업흐름의 최종 산출물은 각각 소유 `src/` 경로에 있고, 통합 시 같은 OpenAPI·DBML·code registry와 generated clients를 사용한다.

## Codex 실행

- root/scoped instructions: `AGENTS.md`, `src/**/AGENTS.md`
- custom agents: `.codex/agents/*.toml`
- skills: `.agents/skills/*/SKILL.md`
- config: `.codex/config.toml`
- prompt index: `src/docs/codex-prompts/PROMPT_INDEX.md`
- all prompts: `src/docs/codex-prompts/ALL_COPY_PASTE_PROMPTS.md`
- runbook: `src/docs/codex/CODEX_RUNBOOK.md`
