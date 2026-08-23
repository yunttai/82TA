---
name: routing-work-planning
description: "공통 PRD를 Provider, entity mapping, route optimization, Bus Intelligence, data/model, private Django API, performance·security 작업으로 분해한다. Routing & Intelligence 기능 기획·백로그·작업 배정·부분 재실행 요청 시 사용한다."
---

# Routing Work Planning

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


## 분해 축

1. Provider capability·fixture·adapter
2. canonical transport model
3. route/stop/direction mapping
4. bounded candidate generation
5. time-dependent cost·budget·transfer
6. ETA·seat·expected wait·confidence
7. private API·cache·deadline
8. collector·data quality·model registry
9. replay·property·performance·security

각 task에는 input snapshot, output type, owned path, latency budget, failure behavior, test ID, model/data version을 기록한다.

## 금지

- 사용자 계정·저장 장소 task
- Frontend presentation JSON 설계
- raw Provider schema를 domain contract로 사용
- online request 중 training·heavy preprocessing
- 무제한 candidate/API call
