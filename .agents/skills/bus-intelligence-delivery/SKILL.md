---
name: bus-intelligence-delivery
description: "사용자 승차 정류장 도착시각 이후 후보 차량의 공식·자체 ETA, 목표 정류장 좌석 부족·저좌석 확률, boardability proxy, expected/P90 wait, freshness·coverage·confidence를 구현·검증한다. BusCrowdRisk 재구성, ETA·좌석 추론 작업 시 사용한다."
---

# Bus Intelligence Delivery

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


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
