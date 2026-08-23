# UX and Information Architecture

## 화면

1. Search Home
2. Detailed Constraints
3. Searching Progress
4. Recommendation List
5. Map + Route Detail
6. Bus Intelligence Detail
7. History
8. Saved Places
9. Favorite Journeys
10. Preferences
11. Account·Consent·Data Rights
12. Support·Coverage

## Result Card Priority

1. 총 P50·P90와 도착시각
2. taxi expected·upper와 budget
3. baseline 대비 절감
4. mode summary
5. reliability·warning
6. recommendation reason

## Bus 정보 문구

- `좌석 부족 확률`과 `승차 가능성 대용값`을 구분한다.
- official·predicted·historical 표시
- freshness 표시
- `승차 보장`, `요금 확정` 금지

## PARTIAL

결과는 유지하고 누락 기능을 leg 또는 전체 banner에 표시한다. 사용자가 어떤 판단이 약해졌는지 알 수 있어야 한다.

## Map

- mode style token
- exact geometry 없는 leg는 요약/점선·warning
- selected card와 leg highlight 동기화
- upstream current/recommended stop 비교
- current location은 page/session state
