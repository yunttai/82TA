---
name: routing-incremental-qa
description: "Routing module 완료 직후 Provider fixture↔adapter↔canonical model, mapping↔gold set, algorithm↔invariants/replay, feature/label↔model runtime, private API↔generated Service client를 교차 검증한다. Provider·매핑·알고리즘·모델 변경과 Routing 릴리스 전에 사용한다."
---

# Routing Incremental QA

## 공통 사전 조건

작업을 시작하기 전에 반드시 다음을 수행한다.

1. `python src/scripts/validate_repository.py`를 실행한다.
2. `python src/scripts/verify_contract_lock.py`를 실행한다.
3. `src/contracts/CONTEXT_MANIFEST.json`과 `src/contracts/CONTRACT_LOCK.json`을 읽는다.
4. `src/docs/shared/PROJECT_CONTEXT.md`, `PRD.md`, 관련 canonical 계약을 읽는다.
5. 이전 `_workspace/` 산출물이 있으면 미완료·피드백·차단 사항을 확인한다.

검증 실패 시 구현을 진행하지 않는다. 공통 원본을 임의로 맞춰 쓰지 말고 drift 또는 change request로 처리한다.

## 저장 위치 규칙

- 분석·토론·중간 결과: `_workspace/{workstream}/`
- 검토가 끝난 제품 코드·문서·테스트·인프라: 반드시 `src/` 아래
- 루트에는 `.codex/`, `.agents/`, `_workspace/`, `src/`, `AGENTS.md`, `README.md`, `.gitignore`만 둔다.
- 공통 PRD·OpenAPI·ERD·enum 복사본을 workstream 폴더에 만들지 않는다.


## 영역

- Adapter schema/resilience/freshness
- Mapping direction/branch/precision
- Routing property and deterministic replay
- Bus candidate/ETA/seat/wait
- data leakage/null labels/train-serve parity
- model calibration/artifact/runtime
- private API/generated client
- performance/security/cost

## 증명해야 할 것

- raw fixture가 같은 canonical output을 생성
- LOW mapping에서 enrichment 차단
- strict budget/P90/time monotonic/Pareto invariants
- model unavailable 시 안전 fallback
- provider partial failure가 semantic PARTIAL로 연결
- Service client가 private response를 정확히 소비

각 finding은 input snapshot, version, expected, actual, severity, owner, retest를 갖는다.
