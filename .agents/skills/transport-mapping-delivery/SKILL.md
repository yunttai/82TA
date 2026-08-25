---
name: transport-mapping-delivery
description: "Kakao·TMAP·ODsay의 transit route/stop 표시를 GBIS와 canonical route·stop·direction·sequence로 식별하고 score·grade·version·validity·gold set·review queue를 구현한다. 노선·정류장 매핑 작업 시 사용한다."
---

# Transport Mapping Delivery

## 작업 범위 확인

1. 적용되는 `AGENTS.md`, 현재 구현, 직접 영향받는 테스트를 읽는다.
2. 공유 API·데이터 의미를 소비하거나 바꿀 때만 manifest, lock, 관련 canonical 계약과 실제 producer·consumer를 읽는다.
3. 작업 전후 가장 작은 관련 검증을 실행한다. 전체 repository/lock 검증은 공유 경계·통합·릴리스 또는 drift 조사에 사용한다.
4. 기존의 무관한 실패는 baseline으로 분리해 보고하고, 현재 작업을 무효화할 때만 중단한다.

제품 산출물은 `src/`에 두고 CI/CD는 `.github/`에 둘 수 있다. `_workspace/`는 선택적·gitignored 메모이며 최신 상태의 근거가 아니다. 공통 PRD·OpenAPI·ERD·enum 복사본은 만들지 않는다.


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
