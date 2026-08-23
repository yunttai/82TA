---
name: bus-intelligence-delivery
description: "사용자 승차 정류장 도착시각 이후 후보 차량의 공식·자체 ETA, 목표 정류장 좌석 부족·저좌석 확률, boardability proxy, expected/P90 wait, freshness·coverage·confidence를 구현·검증한다. BusCrowdRisk 재구성, ETA·좌석 추론 작업 시 사용한다."
---

# Bus Intelligence Delivery

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


## 문제 분리

- observation normalization
- vehicle trip identity
- ETA arbitration/model
- target-stop seat risk
- route-type boardability policy
- multi-vehicle expected/P90 wait
- confidence/coverage

## 워크플로우

1. HIGH mapping과 user arrival time을 입력으로 받는다.
2. 그 시각 이후 도착 가능한 candidate vehicles만 선택한다.
3. ETA source를 official → position model → historical → unknown 순으로 결정한다.
4. Seat model로 target stop no-seat/low-seat probability를 계산한다.
5. 좌석형/일반형 정책으로 boardability proxy 의미를 제한한다.
6. 여러 차량의 순차 확률 질량으로 expected/P90 wait를 계산한다.
7. freshness·missing·mapping·model coverage로 confidence를 만든다.
8. model version, provenance, warning을 반환한다.
9. expected wait가 route time/ranking에 실제 반영되는지 replay로 검증한다.

## 금지

- proxy를 actual boarding probability로 표현
- 미래 관측 없음 label을 0으로 변환
- live와 historical을 같은 confidence로 표시
- 고정 threshold만으로 route decision
