# Service Product UX and Component Acceptance

## 1. 목적과 경계

이 문서는 React 모바일 웹앱/PWA가 Public Service API `1.3.0`을 오인 없이 표시하기 위한 정보 구조, 상태, 문구, 접근성 acceptance를 정의한다. 화면은 Routing이 반환한 시간·비용·순위·확률을 재계산하지 않는다. Provider 호출, Kakao↔GBIS 매핑, Bus ETA·Seat Risk 추론, 후보 생성, strict-budget 판정, Pareto/ranking은 이 작업흐름의 구현 대상이 아니다.

적용 원칙:

- Browser는 Public Service API만 호출한다. Private Routing API·GBIS·Kakao Mobility·모델 endpoint를 호출하지 않는다.
- canonical generated client type을 사용한다. 화면 전용 view model은 표시 순서·format만 소유한다.
- `null`, `UNKNOWN`, `UNSUPPORTED`, 숫자 `0`을 서로 다른 상태로 표시한다.
- P50은 대표 예상, P90은 지연 가능성을 고려한 보수적 예상이다. 어느 것도 도착 보장이 아니다.
- 택시 `expected`, `lower`, `upper`는 요금 범위이며 결제액이 아니다.
- `boardabilityProxy`는 실제 승차 확률이나 좌석 예약 보장이 아니다.
- 일반형 버스 혼잡을 자동으로 승차 실패 의미로 바꾸지 않는다.
- exact geometry가 없을 때 도로를 따르는 것처럼 보이는 직선을 그리지 않는다.
- 내부 provider 오류, model URI/version 상세, raw payload, 번호판, feature vector를 사용자 화면에 노출하지 않는다.

## 2. 모바일 정보 구조와 URL

### 2.1 1차 내비게이션

모바일 bottom navigation은 최대 네 항목으로 유지한다.

| 항목 | URL | 화면 | guest 동작 |
|---|---|---|---|
| 길찾기 | `/` | Search Home·결과 진입 | 사용 가능 |
| 기록 | `/history` | History | 로그인 안내 또는 guest-owned 단건만 표시 |
| 즐겨찾기 | `/favorites` | Favorite Journeys·Saved Places | 로그인 안내 |
| 내 정보 | `/me` | Preferences·Support·Privacy | 공개 support와 로컬 설정은 접근 가능 |

결과 및 보조 화면:

| URL | 화면 | 필수 식별자 |
|---|---|---|
| `/searches/:searchId` | Recommendation List | `searchId` ownership 확인 |
| `/searches/:searchId/routes/:routeId` | Map + Route Detail | 응답 안의 동일 `routeId` |
| `/searches/:searchId/routes/:routeId/bus/:legId` | Bus Intelligence Detail | 응답 안의 동일 `legId` |
| `/places` | Saved Places | session owner |
| `/preferences` | Preferences | session owner |
| `/privacy` | Consent·Data Rights | session owner 또는 공개 설명 |
| `/support` | Support·Coverage | 공개 |
| `/offline` | Offline shell | 공개 |

잘못된 `searchId`, `routeId`, `legId`를 인접 결과로 대체하지 않는다. 해당 resource가 없으면 안전한 not-found 화면과 결과 목록 복귀 action을 제공한다.

### 2.2 모바일 shell

- 상단에는 현재 화면 제목과 필요한 경우에만 뒤로가기를 둔다.
- 검색 결과에서 bottom navigation보다 `검색 수정`, `카드`, `지도`, `상세`의 작업 맥락을 우선한다.
- iOS standalone과 Android standalone 모두 `env(safe-area-inset-*)`를 반영한다.
- 주소창 변화에 견디도록 높이는 `100dvh`를 우선하고, 지원하지 않는 브라우저에 안전한 fallback을 둔다.
- 입력 글꼴은 iOS 자동 확대를 피하도록 최소 16 CSS px로 한다.
- 가로모드는 검색을 막지 않으며, 지도와 상세를 split view로 바꿀 수 있다. 세로모드로 강제하지 않는다.

## 3. PWA 설치·업데이트·오프라인

### 3.1 설치 가능 조건

다음을 모두 만족해야 `installable`로 판정한다.

- HTTPS 또는 localhost
- 유효한 manifest의 `name`, `short_name`, `id`, `start_url`, `scope`, `display: standalone`, theme/background color
- 192×192와 512×512 아이콘, 512×512 maskable 아이콘
- iOS용 `apple-touch-icon`
- 등록되고 활성화된 Service Worker
- manifest·아이콘·Service Worker 요청 성공

설치 UI:

- Android/지원 browser: `beforeinstallprompt`를 저장한 뒤 사용자 action으로만 설치 prompt를 연다.
- iOS Safari: 자동 prompt를 가장하지 않고 `공유 → 홈 화면에 추가` 안내를 단계별로 제공한다.
- 이미 standalone이거나 설치 완료 후에는 설치 CTA를 숨긴다.
- 설치 거절은 오류가 아니다. 동일 session에서 반복 prompt하지 않는다.

### 3.2 Service Worker cache 경계

precache 허용:

- versioned JS/CSS/font/icon
- offline shell
- 비민감 정적 copy

precache/runtime cache 금지:

- `/api/**` 응답
- 장소 suggestion과 reverse-geocode 응답
- 정확한 좌표, 검색 결과, history, saved place, favorite, account, feedback, consent, export
- session/CSRF/guest token 또는 인증 header가 포함된 request

오프라인에서 이전 민감 데이터를 cache로 재현하지 않는다. 검색·장소·지도·계정 작업은 네트워크 필요 상태로 전환하고 입력값 중 장소 표시명·좌표는 장기 저장 없이 현재 page memory에서만 유지한다.

### 3.3 업데이트 상태

| 상태 | 사용자 표시 | action |
|---|---|---|
| 최신 | 배너 없음 | 없음 |
| 새 worker 대기 | `새 버전이 준비됐어요` | `지금 업데이트`, `나중에` |
| update 적용 중 | 짧은 진행 상태 | 중복 action 금지 |
| update 실패 | `업데이트하지 못했어요. 현재 버전을 계속 사용할 수 있어요.` | `다시 시도` |
| controller 변경 | 현재 draft가 없을 때 reload | draft가 있으면 확인 후 reload |

검색 POST 진행 중에는 자동 reload하지 않는다. 새 worker 활성화는 완료 또는 취소 후로 미룬다.

### 3.4 offline/불안정 네트워크

- shell은 열리되 `오프라인입니다. 경로 검색과 장소 검색에는 연결이 필요해요.`를 지속적인 non-modal banner로 표시한다.
- 검색 제출은 disabled만 하지 말고 이유를 텍스트로 설명한다.
- 네트워크가 돌아오면 사용자가 입력을 검토한 뒤 직접 재검색한다. route search를 자동 POST하지 않는다.
- 이전 요청이 응답 여부 불명확 상태라면 같은 idempotency key로 `결과 확인/다시 시도`한다.
- slow network에서는 SEARCHING 상태와 취소 action을 유지하되, 취소가 Routing 계산 취소를 보장한다고 쓰지 않는다.

## 4. Search Home과 장소 선택

### 4.1 기본 흐름

1. 출발지 선택
2. 목적지 선택
3. 지금 출발 또는 지정 시각 선택
4. strict taxi budget 선택
5. 기본 제약 확인
6. 검색 제출

필드 순서는 screen reader DOM 순서와 시각 순서가 같아야 한다. 출발지·목적지 교환은 명시적 버튼으로 제공하며 두 PlaceRef를 원자적으로 바꾼다.

### 4.2 PlaceCombobox 상태

| 상태 | 표현 | action/acceptance |
|---|---|---|
| EMPTY | label과 예시 placeholder | query 입력 |
| TYPING | 입력 유지 | 2자 미만이면 API 호출 없음 |
| DEBOUNCING | 별도 spinner 없음 | 마지막 입력만 유효 |
| LOADING | combobox 안 loading status | 이전 stale suggestion을 선택 가능처럼 두지 않음 |
| RESULTS | 장소명 아래 도로명 주소(없으면 지번 주소)를 표시 | arrow/Enter/Escape와 touch 지원 |
| EMPTY_RESULTS | `검색 결과가 없어요` | 주소를 더 구체적으로 입력 |
| ERROR_RETRYABLE | 입력 유지, 일반 오류 | 다시 시도 |
| RATE_LIMITED | 기다릴 이유와 retry 가능 시점의 일반 안내 | 즉시 반복 호출 금지 |
| SELECTED | displayName을 표시하고 PlaceRef 전체 확정 | clear/change 가능 |

API 문자열은 text node로만 렌더링한다. HTML injection을 허용하지 않는다. 동일 displayName 결과는 Public PlaceRef의 `address`로 구분한다. 주소가 없으면 보조 행을 숨기며 `provider`, `providerPlaceId`, `regionCode`나 결측 placeholder를 사용자 label로 쓰지 않는다.

### 4.3 현재 위치

현재 위치는 사용자 action 후 한 번만 요청한다.

| 상태 | 문구 | fallback |
|---|---|---|
| PROMPT | `현재 위치를 출발지로 사용할까요?` | 장소 검색 |
| REQUESTING | `현재 위치를 확인하는 중` | 취소/장소 검색 |
| GRANTED | reverse-geocode displayName + `현재 위치` source | 위치 다시 확인 |
| DENIED | `위치 권한이 꺼져 있어요` | 브라우저 설정 안내·장소 검색 |
| UNAVAILABLE | `현재 위치를 확인할 수 없어요` | 장소 검색·지도 선택 |
| TIMEOUT | `위치 확인이 오래 걸리고 있어요` | 다시 시도·장소 검색 |
| INSECURE_CONTEXT | 현재 위치 CTA 비활성 + HTTPS 필요 설명 | 직접 장소 검색 |

좌표는 page/session memory에만 두고 analytics, URL, localStorage, Service Worker cache에 기록하지 않는다. V1은 백그라운드 위치 추적을 요청하지 않는다.

### 4.4 지도에서 선택

- 지도 중심 pin을 이동한 뒤 `이 위치 선택` action으로 reverse-geocode한다.
- dragging 중에는 reverse-geocode를 반복 호출하지 않고 이동 종료 후 debounce한다.
- reverse-geocode 실패 시 좌표 숫자를 기본 사용자 label로 노출하지 않고 `지도에서 선택한 위치`로 표시한다.
- 지도 SDK 실패, domain/key 오류, offline이면 text 장소 검색으로 복귀 가능해야 한다.
- Kakao browser key만 web bundle에 허용하고 REST/Mobility key는 금지한다.

## 5. 상세 제약

기본 검색에서 숨겨도 사용자가 제출 전 열어볼 수 있어야 한다.

| control | 표시 | validation |
|---|---|---|
| 출발 유형 | 지금 출발/지정 출발 시각 | Private 1.x는 `DEPART_AT`만 지원 |
| 도착 시각 기준 | `아직 지원하지 않아요`로 disabled | 전송되면 `ARRIVE_BY_UNSUPPORTED`; 출발시각으로 역산 금지 |
| 시각 | KST를 명시한 local picker | timezone-aware ISO 8601로 전송 |
| 택시 예산 | 0·5천·1만·2만·직접 입력 | 0~500,000 KRW, 정수 |
| strict | `이 금액을 넘는 택시 경로 제외` | V1 기본 true |
| 최대 도보 | 분 단위 UI | 0~7,200초 |
| 최대 환승 | 횟수 | 0~8 |
| 최대 택시 구간 | 횟수 | 0~3 |
| 허용 교통수단 | WALK/WAIT/TRANSFER/TAXI/BUS/SUBWAY/GTX/TRAIN | 선택값을 그대로 전달; 생략 시 canonical 전체 |
| 택시 bridge | capability true일 때만 활성 | false일 때 disabled 이유 제공 |
| 좌석 위험 회피 | busSeatRisk true일 때만 활성 | 위험 0으로 대체하지 않음 |
| 최적화 | 빠름/안정/효율/균형 | canonical enum 전송 |
| 계단 회피/휠체어 | accessibility | 지원 결과를 보장한다고 쓰지 않음 |

capability false인 control은 숨기기보다 사용자가 맥락상 기대할 수 있으면 disabled + 이유를 제공한다. capability unknown이면 기본 off이고 `지원 여부 확인 중`으로 표시한다.

폼 오류는 첫 오류로 focus를 이동하고 각 field의 `aria-describedby`에 연결한다. 전체 오류 summary와 field 오류를 함께 제공하며 입력값은 유지한다.

## 6. 검색 state chart

```text
IDLE
  -> VALIDATING
      -> IDLE                   local validation failed
      -> SEARCHING
          -> COMPLETE
          -> PARTIAL
          -> NO_FEASIBLE_ROUTE
          -> PROVIDER_UNAVAILABLE
          -> FAILED
COMPLETE | PARTIAL
  -> EXPIRED                    expiresAt reached or server says EXPIRED
  -> VALIDATING                 user changes and searches again
NO_FEASIBLE_ROUTE | PROVIDER_UNAVAILABLE | FAILED | EXPIRED
  -> VALIDATING                 explicit retry/search change
```

| 상태 | 핵심 copy | 결과 유지 | primary action |
|---|---|---:|---|
| IDLE | `출발지와 목적지를 입력해 주세요` | 해당 없음 | 검색 준비 |
| VALIDATING | `입력을 확인하고 있어요` | 해당 없음 | 오류 수정 |
| SEARCHING | `예산 안에서 경로를 찾고 있어요` | 이전 결과가 있으면 stale임을 표시 | 취소/입력 보기 |
| COMPLETE | `추천 경로를 찾았어요` | 예 | 카드 선택 |
| PARTIAL | `일부 실시간 정보 없이 찾은 결과예요` | 예 | 경고 확인·카드 선택 |
| NO_FEASIBLE_ROUTE | `조건에 맞는 경로를 찾지 못했어요` | 아니오 | 예산/도보/환승 조건 수정 |
| PROVIDER_UNAVAILABLE | `지금은 경로 정보를 불러올 수 없어요` | 아니오 | 다시 시도 |
| FAILED | `검색을 완료하지 못했어요` | 아니오 | support에 전달 가능한 오류 참조 제공 시 사용 |
| EXPIRED | `이 결과는 최신 정보가 아니에요` | 읽기 전용 | 같은 조건으로 다시 검색 |

`PARTIAL`은 failure 화면으로 바꾸지 않는다. 어떤 판단이 약해졌는지 전체 banner와 해당 card/leg에서 함께 표시한다. `EXPIRED` 결과에서 즐겨찾기 metadata는 가능하더라도 해당 route를 현재 추천처럼 선택·피드백하지 않는다.

SEARCHING progress는 가짜 percent를 표시하지 않는다. status announcement는 `role=status`, 오류는 `role=alert`를 사용하고 같은 문구를 반복 announce하지 않는다.

## 7. Recommendation List

### 7.1 카드 순서와 명칭

서버가 제공한 recommendation slot을 다음 순서로 표시한다.

1. `FASTEST` — 가장 빠른 예상
2. `STABLE` — 지연 가능성을 더 보수적으로 본 경로
3. `EFFICIENT` — 추가 비용 대비 효율적인 경로
4. `PUBLIC_TRANSIT_ONLY` — 택시 없는 비교 경로

slot이 `null`이면 다른 route로 채우지 않는다. `이 조건에서는 해당 추천을 만들지 못했어요`를 slot별로 표시한다. 동일 routeId가 여러 slot에 배정되면 카드 하나에 여러 badge를 합치되 서버의 배정을 보존한다.

### 7.2 카드 정보 우선순위

1. 추천 badge와 mode summary
2. 총 P50 (`보통 이 정도`)과 P90 (`늦어질 때 이 정도`)
3. P50/P90 도착시각이 있으면 도착 범위
4. 택시 expected와 upper (`최대 예상`), 입력한 strict budget
5. 전체 expected fare, 도보시간, 환승횟수, 택시 leg 수
6. reliability score와 confidence/origin
7. 상위 reason 두 개와 중요한 warning

`baseline`은 별도 비교 영역에 원래 수치를 나란히 표시한다. 현재 contract에 시간 절감 파생 필드가 없으므로 Frontend/Service가 `N분 절약`을 계산하지 않는다. Routing이 `WITHIN_STRICT_TAXI_BUDGET` reason을 반환하지 않았으면 upper와 budget을 비교해 `예산 이내` 판정을 새로 만들지 않고 숫자를 나란히 표시한다.

### 7.3 시간·비용 format

- duration은 반올림 규칙을 한 곳에서 일관되게 적용하되 원본 초를 변경하지 않는다.
- P50만 크게 쓰고 P90을 숨기지 않는다.
- P90이 P50보다 작으면 카드 렌더링을 중단하고 `결과를 확인할 수 없어요` + telemetry를 남긴다.
- `expected=0`은 `정보 없음`이 아니라 `0원`이다.
- MoneyRange origin `UNKNOWN`이면 수치가 있어도 `출처 확인 필요`를 함께 표시한다.
- `TAXI_FARE_MAY_VARY`가 있으면 `택시 요금은 교통·호출 상황에 따라 달라질 수 있어요`를 비용 바로 옆에 둔다.
- strict route의 upper가 요청 budget보다 큰 계약 위반은 숨김/수정하지 않고 해당 결과 전체를 invalid로 처리한다.

### 7.4 Pareto 비교

Pareto chart는 보조 view이며 카드 접근을 대체하지 않는다.

- x축 `택시비 상한(원)`, y축 `P50 예상시간(분)`을 text로도 제공한다.
- point는 `routeId`로 카드/지도와 연결한다.
- P90은 point detail/table에서 함께 제공한다.
- 축을 잘라 비용·시간 차이를 과장하지 않는다.
- screen reader용 동일 데이터 table을 제공한다.

## 8. Route Detail과 지도

### 8.1 timeline

leg는 `sequence` 오름차순으로 표시하고 누락/중복 sequence는 contract violation으로 처리한다.

| mode | 기본 label | 필수 표시 |
|---|---|---|
| WALK | 도보 | from/to, 시간, 거리 |
| WAIT | 대기 | 장소, 예상시간·출처 |
| TRANSFER | 환승 이동 | from/to, 시간, 거리 |
| TAXI | 택시 | from/to, 주행시간과 요금 범위; 배차 대기가 별도면 분리 |
| BUS | 버스 | Public transit 필드에 실제 제공된 노선 label, 정류장, 시간 |
| SUBWAY | 지하철 | 노선·역·방향이 실제 제공될 때 표시 |
| GTX | GTX | 노선·역·방향이 실제 제공될 때 표시 |
| TRAIN | 기차 | 노선·역·방향이 실제 제공될 때 표시 |

`transit`은 현재 canonical schema에서 자유 object이므로 특정 하위 필드를 UI가 필수라고 가정하지 않는다. label이 없으면 mode와 from/to만 표시하고 contract request로 관리한다.

### 8.2 카드↔지도 동기화

- 선택 card, route, leg는 동일 `routeId`·`legId`·`sequence`를 사용한다.
- 지도 feature click은 대응 timeline 항목으로 focus를 이동한다.
- timeline 선택은 해당 geometry를 highlight하되 map viewport 이동을 reduced-motion 설정에 맞춘다.
- 색만으로 mode/selection을 구분하지 않고 pattern, icon, text label을 병행한다.

### 8.3 geometry 상태

| encoding/state | 지도 | timeline |
|---|---|---|
| GEOJSON valid | mode style로 실제 geometry | 정상 |
| POLYLINE valid | decode 성공 후 실제 geometry | 정상 |
| NONE/null value | from/to marker만; 경로선 없음 | `상세 경로선 없음` |
| 일부 leg 누락 | 제공된 leg만 그리고 누락 구간은 연결하지 않음 | `GEOMETRY_PARTIAL` copy |
| decode/schema 실패 | 해당 geometry 폐기 | 일반 지도 오류 + telemetry |

지도 자체가 실패해도 timeline·카드·warning을 사용할 수 있어야 한다. 지도는 `aria-label`을 갖되 동등 정보는 DOM timeline으로 제공한다.

## 9. Bus Intelligence presentation

이 화면은 Routing/Bus 팀이 계산해 계약으로 전달한 값을 표시만 한다. Bus Intelligence가 `null`이면 0%나 안전으로 표시하지 않는다.

### 9.1 정보 순서

1. 적용 범위와 coverage
2. 사용자가 정류장에 도착하는 예상시각
3. expected wait와 P90 wait
4. 후보 차량별 ETA·출처·confidence
5. 관측 잔여 좌석과 좌석 부족/저좌석 위험
6. boardability proxy disclosure
7. freshness·fallback·warning

### 9.2 coverage matrix

| coverage | label | 허용 표현 | 금지 표현 |
|---|---|---|---|
| LIVE | `실시간 정보 사용` | 관측/수신 시각과 age | `현재 그대로 보장` |
| PARTIAL | `일부 차량 정보만 사용` | 누락 범위·warning | 전체 노선 대표처럼 표현 |
| HISTORICAL | `과거 운행 정보 기반` | `실시간 아님`을 인접 표시 | `현재 좌석` |
| UNSUPPORTED | `이 버스는 좌석 정보를 지원하지 않아요` | 일반 route 정보 유지 | 위험 0%, 안전 badge |
| UNKNOWN | `좌석 정보 지원 여부를 확인할 수 없어요` | 일반 route 정보 유지 | unsupported 또는 low-risk로 추정 |

`DATA_STALE`가 있거나 provenance age가 제품 freshness 기준을 초과했다고 서버가 warning한 경우 수치 옆에 `오래된 정보`를 표시한다. UI가 자체 freshness threshold를 만들어 warning을 생성하지 않는다.

### 9.3 confidence와 mapping

| grade | copy |
|---|---|
| HIGH | `신뢰도 높음` |
| MEDIUM | `참고할 수 있는 수준` |
| LOW | `신뢰도가 낮아 참고용` |
| UNKNOWN | `신뢰도 정보 없음` |

mapping grade LOW/UNKNOWN인데 `busIntelligence`가 적용된 응답은 canonical invariant 위반이다. 수치를 숨겨 안전으로 보이게 하지 말고 panel 전체를 `좌석 정보를 확인할 수 없어요`로 전환하고 telemetry를 남긴다.

### 9.4 후보 차량

- `vehicleRef`는 사용자에게 의미 있는 label임이 보장되지 않으므로 기본 표시하지 않는다.
- ETA의 P50/P90·origin·confidence를 함께 표시한다.
- `remainSeatObserved`가 null이면 `관측 좌석 정보 없음`, 0이면 `관측 잔여 좌석 0석`이다.
- no-seat/low-seat 확률은 model prediction으로 명시하고 소수점 정밀도를 과장하지 않는다.
- `boardabilityProxy`는 `승차 가능성 참고값`으로 표시하고 `실제 승차 결과를 보장하지 않아요`를 항상 인접 배치한다.
- 후보 차량이 비어 있어도 expected/P90 wait를 0으로 바꾸지 않는다. 일관되지 않은 응답은 invalid panel로 처리한다.

## 10. provenance·freshness·confidence 공통 표현

| DataOrigin | 사용자 label |
|---|---|
| OBSERVED | 관측 정보 |
| PROVIDER_ESTIMATE | 교통 제공사 예상 |
| MODEL_PREDICTED | 예측 모델 값 |
| HISTORICAL_PROXY | 과거 정보 기반 |
| USER_INPUT | 사용자가 입력한 값 |
| UNKNOWN | 출처 정보 없음 |

- freshness는 `방금`, `N분 전 수신`처럼 received/age를 표시하며 observedAt과 receivedAt을 혼동하지 않는다.
- fallbackLevel이 0보다 크면 `대체 정보 사용`을 표시하되 내부 provider 순서는 노출하지 않는다.
- modelVersion·mappingVersion은 기본 사용자 화면에 노출하지 않고 support/debug-safe evidence에만 사용한다.
- 출처와 confidence는 카드 summary에서는 간결하게, 상세에서는 필드별로 제공한다.

## 11. reason/warning copy catalog

catalog key는 canonical registry를 그대로 사용한다. 새 key를 여기서 만들지 않는다.

### 11.1 reason

| code | 사용자 copy |
|---|---|
| FASTER_THAN_PUBLIC_TRANSIT | `대중교통만 이용하는 경로보다 빠른 예상이에요` |
| BEST_MARGINAL_TIME_SAVING | `추가 택시비 대비 시간 절감이 큰 경로예요` |
| LOW_TRANSFER_RISK | `환승 여유를 보수적으로 잡은 경로예요` |
| UPSTREAM_STOP_HIGHER_BOARDABILITY | `상류 정류장 이용으로 대기·좌석 조건이 나아지는 경로예요` |
| HIGH_BUS_SEAT_RISK_AVOIDED | `좌석 부족 위험이 높은 버스 구간을 피했어요` |
| TAXI_BRIDGE_CONNECTS_FAST_LINES | `짧은 택시 이동으로 빠른 대중교통 구간을 연결해요` |
| WITHIN_STRICT_TAXI_BUDGET | `택시비 상한이 설정한 예산 안이에요` |
| NO_MEANINGFUL_GAIN_FROM_MORE_BUDGET | `예산을 더 써도 예상 절감이 크지 않아요` |
| LOWER_WALKING_TIME | `도보 시간이 더 짧은 경로예요` |
| LOWER_P90_ARRIVAL_TIME | `늦어질 때의 도착 예상이 더 안정적이에요` |

### 11.2 warning

| code | 사용자 copy | 인접 action |
|---|---|---|
| BUS_DATA_UNAVAILABLE | `버스 실시간 정보를 확인하지 못했어요` | 일반 경로 정보로 계속 |
| BUS_MAPPING_LOW_CONFIDENCE | `버스 노선·정류장 연결 신뢰도가 낮아 좌석 정보를 적용하지 않았어요` | 대중교통 상세 확인 |
| ETA_MODEL_FALLBACK | `공식 도착정보 대신 예측값을 사용했어요` | 출처 확인 |
| HISTORICAL_PROXY_USED | `실시간 정보 대신 과거 운행 정보를 사용했어요` | 출처 확인 |
| TAXI_FARE_MAY_VARY | `택시 요금은 교통·호출 상황에 따라 달라질 수 있어요` | 비용 범위 확인 |
| TAXI_DISPATCH_WAIT_ESTIMATED | `택시 배차 대기는 예측값이에요` | 시간 범위 확인 |
| TRANSFER_MARGIN_LOW | `환승 여유가 짧아요` | 안정 경로 비교 |
| GEOMETRY_PARTIAL | `일부 구간의 상세 경로선을 표시할 수 없어요` | timeline 사용 |
| PROVIDER_PARTIAL_FAILURE | `일부 교통 정보를 불러오지 못했지만 가능한 결과를 표시해요` | 누락 정보 확인 |
| DATA_STALE | `일부 정보가 최신 상태가 아니에요` | 다시 검색 |
| BUDGET_NEAR_LIMIT | `택시비 상한이 설정한 예산에 가까워요` | 비용 범위 확인 |
| BOARDABILITY_IS_PROXY | `승차 가능성은 실제 승차 결과가 아닌 참고값이에요` | 설명 확인 |
| FEATURE_OUT_OF_DISTRIBUTION | `평소와 다른 조건이라 예측 신뢰도가 낮을 수 있어요` | 다른 경로 비교 |
| FUTURE_TRANSIT_ESTIMATED | `미래 대중교통은 과거 운행 정보 기반 예상이에요` | 현재 출발과 구분 |

unknown reason은 추천 근거 영역에서 `추가 추천 근거가 있어요`로 안전하게 축약하고 telemetry를 남긴다. unknown warning은 숨기지 않고 `일부 정보를 확인할 수 없어요`로 표시하며 원문 code를 일반 사용자에게 노출하지 않는다.

## 12. Problem Details와 복구

| code/status | 사용자 copy | action |
|---|---|---|
| INVALID_COORDINATE | `선택한 위치를 확인해 주세요` | 장소 다시 선택 |
| UNSUPPORTED_TIME | `선택한 시각은 지원하지 않아요` | 시각 수정 |
| ARRIVE_BY_UNSUPPORTED | `도착 시각 기준 검색은 아직 지원하지 않아요` | 출발 시각으로 검색 |
| CONSTRAINT_OUT_OF_RANGE | `이동 조건의 허용 범위를 확인해 주세요` | 오류 field focus |
| AUTH_REQUIRED/401 | `로그인이 필요한 기능이에요` | 로그인 또는 길찾기로 복귀 |
| SESSION_EXPIRED/401 | `세션이 만료됐어요` | guest session 다시 시작 또는 로그인 |
| FORBIDDEN/403 | `이 항목에 접근할 수 없어요` | 자신의 목록으로 복귀 |
| CONSENT_REQUIRED/403 | `이 기능을 사용하려면 동의가 필요해요` | 해당 동의 설명 확인 |
| SEARCH_NOT_FOUND/404 | `검색 결과를 찾을 수 없어요` | 새 검색 |
| DATA_RIGHTS_JOB_NOT_FOUND/404 | `요청 내역을 찾을 수 없어요` | 개인정보 화면으로 복귀 |
| IDEMPOTENCY_CONFLICT/409 | `같은 요청의 내용이 달라 다시 확인이 필요해요` | 새 요청으로 재검색 |
| CONTRACT_VERSION_CONFLICT/409 | `앱 업데이트가 필요해요` | reload/update |
| PREFERENCE_VERSION_CONFLICT/409 | `다른 곳에서 설정이 변경됐어요` | 최신 설정을 불러와 변경 재확인 |
| DATA_RIGHTS_JOB_CONFLICT/409 | `이미 같은 요청을 처리하고 있어요` | 기존 job 상태 확인 |
| UNSUPPORTED_REGION/422 | `현재 지원 지역 밖이에요` | support 지역 확인 |
| RATE_LIMITED/429 | `요청이 많아 잠시 후 다시 시도해 주세요` | 지연 후 재시도 |
| PROVIDER_BAD_RESPONSE/502 | `교통 정보를 처리하지 못했어요` | 다시 시도 |
| TRANSIT_PROVIDER_UNAVAILABLE/503 | `대중교통 정보를 불러올 수 없어요` | 다시 시도 |
| MODEL_NOT_READY/503 | `일부 예측 기능을 사용할 수 없어요` | partial 가능 시 결과 유지 |
| ROUTING_DEADLINE_EXCEEDED/504 | `검색 시간이 길어져 완료하지 못했어요` | 같은 idempotency context로 확인/재시도 |

`detail`, `safeContext`, correlation ID는 raw debug panel에 출력하지 않는다. 고객지원 참조가 필요하면 서버가 public-safe reference를 제공할 때만 복사 action을 둔다.

## 13. 계정·기록·즐겨찾기·선호

### 13.1 guest-first

- 첫 검색에 로그인 modal을 강제하지 않는다.
- 첫 ownership-bound 검색 전에 `POST /api/v1/guest-sessions`로 짧은 수명의 opaque credential을 한 번 발급한다.
- guest token은 응답에서 한 번만 받아 memory에 보관하고 `X-Guest-Token`으로만 전송한다. URL/localStorage/화면/telemetry/Service Worker cache에 노출하지 않는다.
- `GET /api/v1/session`의 `subjectType`, `authenticated`, `expiresAt`으로 GUEST/USER와 만료를 표시한다. token에서 identity를 해석하지 않는다.
- `DELETE /api/v1/session` 성공 시 memory의 guest credential과 사용자 화면 state를 즉시 지운다. 서버 revoke 성공 전 `로그아웃됨`으로 표시하지 않는다.
- guest 만료 후에는 이전 token을 재사용하지 않고 새 guest session을 만든 뒤 새 검색을 시작한다. 만료된 결과의 ownership을 자동 이전하지 않는다.
- 로그인 생성 방식은 계약 공백이므로 로그인 기능이 unavailable이어도 guest 검색·결과 흐름은 유지한다.
- 로그인 후 guest 결과 병합은 현재 계약에 정의되지 않았으므로 자동 병합을 약속하지 않는다.

### 13.2 History

| 상태 | 표현/action |
|---|---|
| logged out | 로그인 시 기록을 관리할 수 있다는 안내; 자동 저장 동의 금지 |
| opt-out | `검색 기록 저장 안 함`을 명확히 표시 |
| loading | skeleton + status |
| empty | `저장된 검색 기록이 없어요` |
| loaded | 출발/도착 displayName, 검색 시각, 상태, `history.saved`, `retainedUntil`; exact 좌표 숨김 |
| expired item | `다시 검색 필요`; 과거 route를 현재 결과처럼 열지 않음 |
| delete pending | 대상과 범위를 확인; undo 가능 여부를 서버 의미대로 표시 |
| error | 목록 유지 가능한 경우 유지 + 재시도 |

`saveToHistory`는 명시적 opt-in이며 USER session과 현재 `SEARCH_HISTORY` 동의가 모두 있어야 한다. GUEST 검색은 `history.saved=false`, `ownerKind=GUEST`로 짧은 조회 TTL만 표시한다. 민감 장소 label을 analytics event에 넣지 않는다.

### 13.3 Saved Places

- label, displayName, `민감한 장소` 여부를 표시한다.
- 화면/notification preview에서 민감 label을 기본 숨길 수 있는 privacy 설정을 제공한다.
- create는 목록에 server `201` response가 도착한 뒤 반영하고, edit는 item `PATCH`의 server response로 교체한다.
- delete는 대상 label을 확인한 뒤 item `DELETE` 204에서 목록에서 제거한다. 다른 owner는 404로 resource 존재를 숨기고, 동일 owner의 scope/consent 부족 403은 일반 접근 불가로 처리한다.
- 삭제 확인은 연결된 favorite 영향이 계약으로 제공될 때만 구체적으로 말한다.
- 저장 장소 label과 providerPlaceId는 Routing request에 전달하지 않는다.

### 13.4 Favorite Journeys

- nickname, 저장된 출발/도착, default constraints 요약을 표시한다.
- favorite 선택은 Search Home을 prefill하며 자동 POST하지 않는다.
- create/update/delete는 collection POST와 item PATCH/DELETE 응답을 기준으로 완료 처리한다. 다른 owner의 item 404에서 resource 존재를 추정하지 않는다.
- 저장된 조건이 현재 capability와 맞지 않으면 disabled 이유를 표시하고 사용자가 수정하게 한다.
- favorite은 경로 결과 snapshot이 아니라 검색 조건임을 명확히 한다.

### 13.5 Preferences

- 기본 taxi budget, 최대 도보·환승·taxi legs, optimization, accessibility, privacy를 section별 저장한다.
- GET의 ETag를 보관하고 first-party PUT마다 `If-Match`로 전달한다. response ETag와 read-only `version`, `updatedAt`을 최신 상태로 교체한다.
- optimistic UI를 사용해도 server 확인 전 저장 완료로 announce하지 않는다.
- `PREFERENCE_VERSION_CONFLICT`이면 서버 최신값을 다시 가져와 사용자의 변경과 나란히 보여주고 재확인한다. 자동 last-write-wins를 사용하지 않는다.
- accessibility preference는 실제 경로 접근성 보장이 아니며 provider coverage 경고를 함께 표시한다.

## 14. Feedback

- 결과가 만료되지 않았고 응답 안에 존재하는 `selectedRouteId`만 제출한다.
- rating/comment는 선택 사항이며 실제 duration·taxi cost·도착 여부·bus outcome은 별도 동의를 받아 선택적으로 입력한다.
- `busOutcome` 입력은 사용자가 실제 경험한 사실과 예측을 구분하는 질문으로 구성한다.
- 정확한 위치를 comment에 쓰지 않도록 안내하고 comment를 HTML로 렌더링하지 않는다.
- 제출 성공 후 값을 예측 학습에 즉시 반영한다고 약속하지 않는다.

## 15. Support·Coverage

Support 화면은 PublicCapabilities만 사용한다.

- origin/destination region support를 각각 표시한다.
- feature true/false/unknown을 지원/미지원/확인 불가로 구분한다.
- `degraded`는 registry에 정의된 public-safe copy가 있을 때 표시하고 unknown은 일반 문구로 fallback한다.
- provider 이름·quota·key verification 같은 private capability를 노출하지 않는다.
- `realtimeRerouting=false`는 `이동 중 자동 재탐색은 아직 지원하지 않아요`로 표시한다.
- `busSeatRisk=false`는 버스 경로 자체 미지원으로 확대 해석하지 않는다.

## 16. Consent·Privacy·Data Rights

### 16.1 privacy center

`GET /api/v1/me/consents`의 최신 상태를 다음 canonical type별로 분리한다.

| consentType | 사용자 label | 거절 시 영향 |
|---|---|---|
| SEARCH_HISTORY | 검색 기록 저장 | `saveToHistory=true` 사용 불가; guest/짧은 TTL 검색은 유지 |
| PRECISE_LOCATION | 정확한 위치 저장 | saved place 등 지속 저장 제한; 일회성 현재 위치 검색은 별도 설명 |
| PRODUCT_ANALYTICS | 제품 개선 분석 | 분석 event 비활성; route search 유지 |
| ROUTING_FEEDBACK | 이동 결과 feedback 활용 | feedback 수집 비활성; route search 유지 |

- 현재 화면의 법적 문서 version을 `PUT /api/v1/me/consents/{consentType}`의 `documentVersion`으로 보내고, server가 반환한 `ConsentRecord` 이후에만 저장 완료로 표시한다.
- 동의 취소도 `accepted=false` record로 남기며 과거 data 삭제까지 완료됐다고 표현하지 않는다.
- 필수 서비스 동의와 선택 동의를 한 switch로 묶지 않는다. 선택 동의 거절로 guest route search를 막지 않는다.
- 일회성 현재 위치, saved place의 정확한 위치 저장, 보존기간·삭제 범위, export와 계정 삭제를 별도 설명한다.

### 16.2 삭제

- 삭제 대상(계정과 관련 위치·장소·검색·동의·feedback)을 구체적으로 확인한다.
- 새 client는 `POST /api/v1/me/data-deletions`를 사용한다. deprecated `DELETE /api/v1/me/data`를 새 UI에서 호출하지 않는다.
- 202 `PENDING`은 `삭제 요청을 접수했어요`, `RUNNING`은 `삭제하는 중`, `COMPLETE`는 `삭제를 완료했어요`, `FAILED`는 `삭제를 완료하지 못했어요`로 표시한다.
- `GET /api/v1/me/data-deletions/{jobId}`를 backoff polling하며 page 복귀 후에도 owner session으로 상태를 다시 확인한다.
- `DATA_RIGHTS_JOB_CONFLICT`이면 새 요청을 반복하지 않고 기존 job으로 이동한다.
- `failureCode`는 registry가 없으므로 raw code를 노출하지 않고 일반 실패 copy와 support action만 제공한다.
- `COMPLETE`는 server가 backup/analytics retention evidence까지 확인한 상태로 취급한다. Frontend가 완료 시점을 추정하지 않는다.
- 계약에 없는 취소·복구·즉시 완료를 약속하지 않는다.

### 16.3 export

export는 exact location이 포함될 수 있는 민감 파일로 취급한다.

- `POST /api/v1/me/data-exports`의 202 job을 만든 뒤 `GET /api/v1/me/data-exports/{jobId}`를 backoff polling한다.
- PENDING/RUNNING/COMPLETE/FAILED copy는 deletion과 동일한 상태 의미를 사용하되 action은 다운로드 준비 흐름으로 구분한다.
- `COMPLETE`이고 `downloadUrl`과 미래 `downloadExpiresAt`이 모두 있을 때만 다운로드 CTA를 활성화한다.
- URL을 DOM text, analytics, clipboard 기본 action, history query, persistent cache에 저장하지 않는다.
- 만료 후에는 기존 URL을 재사용하지 않고 새 export를 요청한다.
- 다른 owner의 job은 404와 동일한 not-found copy로 처리하여 존재 여부를 노출하지 않는다.

## 17. 공통 component acceptance

| component | 입력/계약 | 필수 상태 | 접근성·테스트 acceptance |
|---|---|---|---|
| AppShell | router, network, install state | online/offline/update/standalone | skip link, landmark, safe area, 320px width |
| InstallPrompt | browser install capability | eligible/iOS guide/installed/dismissed | focus 이동 없음, 반복 prompt 없음 |
| UpdateBanner | SW lifecycle | waiting/applying/failed | status announce, draft 보호 |
| SessionStatus | GuestSessionCredential/SessionContext | creating/guest/user/expired/revoking/error | credential non-display, memory-only, revoke confirmation |
| PlaceCombobox | `PlaceRef[]` | empty/loading/results/empty/error/selected | ARIA combobox/listbox, keyboard·touch, XSS test |
| CurrentLocationButton | Geolocation API | prompt/requesting/granted/denied/error | permission reason, no background watch/storage |
| MapPicker | map adapter, reverse geocode | loading/ready/dragging/resolving/fallback | text alternative, confirm action, no coordinate log |
| RouteSearchForm | Public request | idle/invalid/submitting/offline | labels, error summary, timezone/unit tests |
| SearchStatus | SearchStatus/Problem | all canonical states | live-region dedupe, retry semantics |
| RecommendationCard | `RouteCandidate` | complete/null/invalid/warning | P50/P90 and expected/upper spoken labels |
| ParetoComparison | `paretoFrontier` | populated/empty | equivalent table, routeId selection sync |
| RouteTimeline | `legs` | populated/partial/invalid | semantic ordered list, mode text + icon |
| RouteMap | geometry | ready/partial/none/error | timeline equivalent, reduced motion |
| BusPanel | `BusLegIntelligence|null` | all coverage/confidence/stale states | proxy disclosure always adjacent, null≠0 tests |
| WarningList | registry codes | known/unknown | severity not color-only, generic fallback |
| HistoryList | Public responses | auth/loading/empty/data/error | no exact coordinate exposure, expired action |
| SavedPlaceList | SavedPlace | auth/loading/empty/data/error | sensitive label privacy, ownership errors |
| FavoriteList | FavoriteJourney | auth/loading/empty/data/error | prefill only, no auto-search |
| PreferencesForm | UserPreferences | loading/dirty/saving/saved/conflict/error | section status, server confirmation |
| FeedbackForm | RouteFeedbackInput | pristine/invalid/submitting/success/error | optional fields identified, no HTML rendering |
| CapabilityPanel | PublicCapabilities | supported/degraded/unknown/error | false≠unknown, private details absent |
| ConsentForm | ConsentRecord | loading/accepted/declined/saving/error | type별 설명, document version, server confirmation |
| DataRightsJob | DataRightsJob | PENDING/RUNNING/COMPLETE/FAILED/not-found | owner-safe polling, URL expiry, destructive confirmation |
| PrivacyCenter | consent/delete/export | available/pending/error | 선택 동의 분리, 202/job semantics, 민감 URL 비저장 |

## 18. iOS·Android 접근성 acceptance

기준은 WCAG 2.2 AA를 목표로 한다.

- 모든 action은 keyboard로 접근 가능하고 focus indicator가 보인다.
- touch target은 최소 44×44 CSS px, 주요 모바일 action은 가능하면 48×48을 사용한다.
- text contrast 4.5:1, 큰 text·비문자 UI 3:1 이상.
- 200% text 확대와 320 CSS px width에서 양방향 scroll 없이 핵심 검색·결과 action을 사용한다.
- color, 위치, animation만으로 상태를 전달하지 않는다.
- `prefers-reduced-motion`에서 지도 pan, skeleton shimmer, page transition을 제거/축소한다.
- screen reader label에는 단위와 의미를 포함한다. 예: `대표 예상 52분, 늦어질 때 71분`.
- modal/drawer는 focus trap, Escape/닫기, focus return을 제공한다. iOS swipe dismissal에도 상태가 유실되지 않는다.
- Android system back은 drawer→detail→list→search 순서로 history를 따른다. 앱 종료를 막는 가짜 confirm을 반복하지 않는다.
- hardware/software keyboard가 열린 상태에서 primary action과 오류가 가려지지 않는다.
- hover-only tooltip을 사용하지 않는다. warning 설명은 tap/focus로도 연다.
- `datetime-local`의 iOS/Android 차이를 검증하고 화면에는 `한국 시간`을 명시한다.
- forced colors/high contrast에서도 selected route와 error가 구분된다.
- 접근성 설정(계단 회피·휠체어)은 단순 시각 icon 외 text label과 지원 경고를 갖는다.

## 19. 모바일 검증 matrix

| 환경 | 필수 시나리오 |
|---|---|
| Playwright Chromium mobile | guest search, place keyboard/touch, all statuses, offline, SW update, accessibility |
| Playwright WebKit mobile | form/date-time, focus/keyboard, history navigation, map fallback, reduced motion |
| iPhone Safari 실기기/Simulator | safe area, viewport/keyboard, Home Screen 추가, standalone launch/update, VoiceOver smoke |
| Android Chrome 실기기/Emulator | install prompt, standalone/back, offline/update, TalkBack smoke |
| 320px small viewport | search, cards, warning, destructive confirm without clipping |
| landscape | search submit, result/card/map-detail access |
| slow/offline network | no duplicate POST, idempotent retry, sensitive API cache 없음 |

fixture coverage:

- COMPLETE with four recommendations and baseline
- PARTIAL without Bus data
- PARTIAL with ETA fallback
- LIVE/PARTIAL/HISTORICAL/UNSUPPORTED/UNKNOWN Bus coverage
- HIGH/MEDIUM/LOW/UNKNOWN confidence
- observed seat `0`, observed seat `null`, probability `0`, probability unavailable
- stale data, unknown warning/reason
- no feasible strict budget, provider unavailable, failed, expired
- full/partial/none/invalid geometry
- duplicate recommendation routeId, null recommendation slot
- offline before submit, lost connection after submit, update waiting during search
- guest credential create/expire/revoke, USER/GUEST session inspection
- `history.saved` true/false, USER/GUEST owner, retainedUntil null/value
- saved place and favorite create/update/delete, owner-hidden 404
- preference ETag update and `PREFERENCE_VERSION_CONFLICT`
- each consent type accepted/declined and stale document version failure
- export/deletion PENDING/RUNNING/COMPLETE/FAILED, conflict, owner-hidden not-found, expired download URL

## 20. Public 1.3.0 지원 범위와 남은 계약 gap

### 20.1 contract-backed 구현 범위

다음은 Public 1.3.0 generated client를 통해 구현한다.

- guest credential create, GUEST/USER session inspection, current session revoke
- `history.saved`, owner kind, retained-until 표시와 로그인+SEARCH_HISTORY opt-in
- preference ETag/`If-Match` optimistic concurrency
- saved place와 favorite journey list/create/update/delete
- consent type별 list/record
- asynchronous export/deletion create/status와 짧은 수명 download
- owner를 숨기는 not-found, consent 부족 403, preference/data-rights conflict 복구
- allowedModes와 avoidHighBusSeatRisk pass-through, explicit ARRIVE_BY unsupported

### 20.2 여전히 차단된 gap

다음 UX는 shared semantics/API가 없어 local endpoint나 DTO를 임의로 만들 수 없다. `$shared-contract-governance` change request 승인 전 해당 CTA를 unavailable 상태로 두거나 계약에 있는 범위만 표시한다.

| gap | 필요한 계약 결정 | 현재 안전한 UX |
|---|---|---|
| 계정 복구·이메일 확인 | recovery token, email delivery, verification state, 재인증 | 이메일 가입·로그인은 제공하고 복구 CTA는 제공하지 않음 |
| guest→USER 병합 | 검색·feedback ownership 이전과 conflict policy | 자동 병합을 약속하지 않음 |
| 개별 history 삭제·보존기간 설정 | delete endpoint, retention preference | save opt-in과 list/get/metadata만 사용 |
| 동의 문서 배포 | 현재 document URL/version, required/optional policy, version 갱신 UX | 배포가 고정한 법적 문서 version만 전송; 임의 version 생성 금지 |
| favorite default constraints | `defaultConstraints`의 typed public schema | opaque object 내부를 추정·부분 수정하지 않음 |
| privacy preference | `UserPreferences.privacy`의 typed public schema | typed consent API만 사용; 임의 toggle 저장 금지 |
| feedback bus outcome | `busOutcome`의 typed public schema와 동의/validation | rating·comment 등 typed 필드만 사용; object 추정 금지 |
| transit display fields | `RouteLeg.transit`의 안정된 public shape | mode/from/to 외 필드 추정 금지 |
| baseline time-saving | 서버가 계산한 canonical saved-time field/reason | 원본 수치를 나란히 표시; UI 계산 금지 |
| support degraded copy | public-safe degraded code registry | unknown generic copy, raw code 숨김 |
| data freshness threshold | server warning policy | `DATA_STALE`가 있을 때만 stale badge 생성 |
| data-rights failure copy | public-safe `failureCode` registry | generic failure와 support action; raw code 숨김 |

## 21. 완료 판정

Service UX 구현 완료는 다음을 모두 만족할 때만 주장한다.

- generated Public client→hook→component field 접근이 계약과 일치한다.
- COMPLETE/PARTIAL/error/EXPIRED와 모든 null/unknown/unsupported 상태가 fixture로 검증된다.
- P50/P90·요금 범위·Bus proxy·freshness를 과장하는 copy가 없다.
- 카드·timeline·지도는 동일 routeId/legId/sequence를 사용한다.
- PWA install/update/offline이 iOS·Android에서 검증되고 민감 API 데이터가 cache되지 않는다.
- guest route search가 계정 기능 없이도 끝까지 동작한다.
- 이메일 가입·로그인·session revoke, guest session, history consent, CRUD, preference conflict, consent, export/deletion job의 Public 1.3.0 상태가 end-to-end로 검증된다.
- exact coordinate·token·민감 label이 URL, persistent browser storage, telemetry, Service Worker cache에 없다.
- WCAG 2.2 AA 기본 자동 검사와 VoiceOver/TalkBack smoke가 통과한다.
- contract gap 기능은 구현 완료로 세지 않고 `BLOCKED` 또는 `UNVERIFIED`로 보고한다.
