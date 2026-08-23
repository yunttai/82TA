---
name: transport-mapping-delivery
description: "Kakao·TMAP·ODsay의 transit route/stop 표시를 GBIS와 canonical route·stop·direction·sequence로 식별하고 score·grade·version·validity·gold set·review queue를 구현한다. 노선·정류장 매핑 작업 시 사용한다."
---

# Transport Mapping Delivery

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


## 입력 신호

- normalized route name/type
- boarding/alighting names and coordinates
- route stop sequence and direction
- origin/destination terminals
- route geometry proximity
- current GBIS vehicle existence
- provider/local BIS identifiers when available

## 워크플로우

1. canonical normalization과 fingerprint를 정의한다.
2. candidate route/stop을 PostGIS proximity로 찾는다.
3. direction·sequence·branch·turning point를 검증한다.
4. signal breakdown과 score를 계산한다.
5. `HIGH`, `MEDIUM`, `LOW` 정책을 적용한다.
6. gold set과 review queue, validity/version을 저장한다.
7. LOW에서는 Bus Intelligence를 차단한다.
8. precision-first mapping test를 실행한다.

## 불변식

- route number만으로 HIGH 금지
- stop name만으로 동일 정류장 확정 금지
- 반대 방향과 A/B branch 혼합 금지
- mapping version 없이 cache 재사용 금지
