# Service Product Handoff Contract

## Service가 Routing에 제공

- contractVersion, requestId
- origin/destination coordinate와 regionHint
- departureTime·arrivalDeadline
- taxi budget·strict
- max walk/transfer/taxi legs·allowed modes
- 익명 preference scalar
- requested recommendation types
- locale·timezone
- deadline·correlation·idempotency

## 제공하지 않음

- user ID·email·phone·social ID
- `집`, `학교`, `직장` label
- history·favorite 목록
- account token

## Routing에서 기대

- COMPLETE/PARTIAL/NO_FEASIBLE_ROUTE
- routes와 recommendation IDs
- P50/P90·fare range·legs
- Bus Intelligence·coverage·provenance
- provider/model/mapping/ranking versions
- reason·warning
- expiresAt

## Service의 변환

가능:

- internal debug field 제거
- label/localization
- searchId·ownership 추가
- public-safe support projection

금지:

- ranking 변경
- duration/fare/seat probability 재계산
- warning 삭제로 불확실성 은폐
- unsupported 기능을 사용 가능으로 표시

## 신규 요구 전달

Routing 응답에 새 정보가 필요하면 UI 코드에서 임의로 추정하지 않는다. Contract Change Request를 작성한다.
