# 00. 저장소 최초 점검

> **역사 자료:** 초기 하네스 구축 당시의 복붙 레시피다. 현재 활성 지시나 완료 gate가 아니며, 현재 구현·적용되는 `AGENTS.md`·작업 관련 skill을 우선한다.

**사용 시점:** Codex에서 저장소를 처음 열었을 때

```text
저장소를 수정하지 말고 먼저 구조와 현재 상태를 점검해줘.

1. 루트 AGENTS.md와 현재 작업 디렉터리까지 적용되는 모든 하위 AGENTS.md를 읽어라.
2. .codex/config.toml, .codex/agents, .agents/skills 구조를 확인하라.
3. 다음을 실행하라.
   - python src/scripts/validate_repository.py
   - python src/scripts/verify_contract_lock.py
4. CONTEXT_MANIFEST, CONTRACT_LOCK, harness registry, shared PRD, Context Map, OpenAPI, DBML, code registry를 읽어라.
5. Service Product와 Routing & Intelligence의 소유 경계, 금지 의존성, contextVersion/contractVersion/aggregateSha256을 요약하라.
6. _workspace의 WORKPLAN, STATUS, HANDOFF를 읽고 DONE/PENDING/BLOCKED/UNVERIFIED를 정리하라.
7. 제품 코드·계약·문서를 아직 수정하지 마라.

최종 출력: 활성 instruction files, 검증 결과, 두 작업흐름 상태, 계약 상태, 위험/drift, 다음 추천 지시 3개.
```
