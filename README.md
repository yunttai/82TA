# 82TA

경기 남부↔서울의 예산 제약형·시간 의존형 복합교통 경로 추천 제품이다. 한 monorepo 안에서 두 deployable workstream을 유지한다.

- **Service Product**: React/TypeScript Web/PWA와 Django Service API
- **Routing & Intelligence**: Django private Routing API, provider adapters, mapping, optimizer, Bus Intelligence/data-model 기반
- 내부 경계: `POST /v1/routes/optimize`

현재 저장소에는 Web, Service, Routing, provider/domain package, workers, tests, generated clients, infrastructure와 GCE CD workflow가 있다. GCE는 유일한 지원 cloud compute 배포 기준이며 다른 cloud 경로와 dual-cloud parity는 유지하지 않는다. active GCE 구성에는 development/demo 성격의 설정도 있으므로, 존재 자체를 production readiness로 해석하지 않는다.

검증되지 않은 provider, mapping, ETA/Seat model capability는 disabled, unsupported 또는 `PARTIAL`로 유지한다.

## Codex harness

```text
AGENTS.md                  저장소 경계와 비례 검증 원칙
src/**/AGENTS.md           경로별 안전 조건
.codex/config.toml         프로젝트 Codex 설정
.codex/agents/*.toml       선택적 전문 역할
.agents/skills/*/SKILL.md  작업별 워크플로
_workspace/                선택적·gitignored 임시 메모
```

현재 구현이 maintenance baseline이다. 하네스는 roadmap이나 과거 문서와 다르다는 이유만으로 애플리케이션·계약·인프라를 고치지 않는다. 공유 계약 변경은 OpenAPI·DBML·event·code 전체 묶음이 아니라 실제 영향받는 producer/consumer와 artifact만 갱신한다.

## 작업 시작

별도 프롬프트를 복붙할 필요 없이 원하는 변경을 설명하면 된다. 범위에 맞는 검증을 사용한다.

```bash
# local 변경: 해당 package의 targeted test/lint/build

# harness만 점검
python src/scripts/validate_repository.py --harness-only

# layout만 점검
python src/scripts/validate_repository.py --layout-only

# 통합·릴리스 또는 전체 점검
python src/scripts/validate_repository.py
python src/scripts/verify_contract_lock.py
python src/scripts/compare_context_snapshots.py
```

`compare_context_snapshots.py`라는 기존 이름은 호환성을 위해 유지하지만, 오래된 snapshot 파일이 아니라 현재 verified `CONTRACT_LOCK.json`을 직접 비교한다. snapshot이 필요한 경우 기본적으로 각 workstream의 `00_context_snapshot_current.json` 하나만 갱신한다.

## 안전 경계

- browser → Service → Routing
- Service DB와 Routing DB 분리; Routing에 사용자 identity 없음
- strict taxi upper-budget, time propagation, `P90 >= P50`
- `null`, `unknown`, `unsupported`, 숫자 0 구분
- mapping confidence gate 전 Bus Intelligence 적용 금지
- partial failure와 provenance를 명시

## 문서

- [Codex runbook](src/docs/codex/CODEX_RUNBOOK.md)
- [Custom agent map](src/docs/codex/CUSTOM_AGENT_MAP.md)
- [Worktree and integration](src/docs/codex/WORKTREE_AND_INTEGRATION.md)
- [Harness changelog](src/docs/codex/HARNESS_CHANGELOG.md)
- [Legacy prompt archive](src/docs/codex-prompts/PROMPT_INDEX.md)
