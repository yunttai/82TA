# Security and Privacy

## 신뢰 경계

```text
Untrusted: browser input, public API traffic, external Provider response
Semi-trusted: authenticated Service request, cache, user feedback
Trusted internal: private Routing API, approved model registry, production DB
```

외부 Provider 응답도 schema·범위·시각 검증 전에는 신뢰하지 않는다.

## 주요 위협과 통제

| 위협 | 통제 |
|---|---|
| API key 유출 | server-side secret store, 최소 권한, rotation, browser 비노출 |
| Denial of Wallet | GCE edge/application rate limit, cache, candidate/provider call 상한, cost alarm |
| SSRF | Provider URL allowlist, 사용자 URL 금지, egress 제어 |
| 위치 이력 노출 | 최소 저장, encryption, redaction, 삭제 |
| 계정 탈취 | secure cookie, CSRF, login rate limit, audit |
| guest/session 탈취 | opaque high-entropy token, server-side hash, short TTL, rotation/revoke, localStorage 금지 |
| export URL 유출 | owner authorization, short-lived URL, no direct object reference, download audit |
| Routing API 위조 | private network, service JWT/workload identity |
| cache poisoning | canonical key, response validation, ACL |
| model artifact RCE | registry, native safe format, hash/signature, fixed path |
| dependency supply chain | lockfile, SBOM, SAST/SCA, image/IaC scan |
| mapping 오류 | precision-first threshold, LOW 미적용, review queue |
| Provider schema drift | validation, degraded state, alert, fixture 격리 |

## 위치 처리

- 검색 시 정확한 좌표는 계산 목적에만 사용한다.
- Routing에는 user identity를 보내지 않는다.
- 로그·trace에는 낮은 정밀도 region만 사용한다.
- saved place와 route history는 명시적 저장·삭제를 지원한다.
- history opt-in은 로그인과 `SEARCH_HISTORY` 동의를 요구하며 guest 결과는 짧은 결과 TTL만 유지한다.
- data export/deletion job의 상태 조회는 동일 owner에게만 허용하고, 삭제 완료는 backup/analytics retention까지 증빙한다.
- 다른 owner의 search·saved place·favorite·data-rights job ID는 resource 존재를 숨기기 위해 `404`로 응답한다. `403`은 동일 owner의 consent·scope 부족에만 사용한다.
- 분석 dataset에는 정확한 좌표와 `집/직장/학교` label을 복사하지 않는다.
- saved place 생성은 정확한 좌표를 새로 보존하므로 현재 `PRECISE_LOCATION` 동의를 요구한다. PATCH는 `place`를 포함한 좌표 변경에만 동의를 요구한다. label/`isSensitive` 변경과 DELETE에는 위치 동의를 요구하지 않아 동의 철회 뒤에도 사용자가 기존 데이터를 정리할 수 있게 한다. USER·owner·CSRF 통제는 모든 쓰기에서 유지한다.
- SavedPlace/FavoriteJourney의 POST·PATCH·DELETE는 동일한 owner-scoped `favorite-location-write` quota로 보호하고 초과를 `429 RATE_LIMITED`로 축약한다. 읽기 GET은 이 쓰기 quota에 포함하지 않는다.
- 임의 장소 즐겨찾기의 첫 생성은 현재 USER와 `PRECISE_LOCATION` 동의, CSRF, owner-scoped idempotency, rate limit을 요구한다. 두 장소·즐겨찾기·receipt 원장 중 일부만 남는 부분 성공을 금지한다. 동일 body의 성공 receipt replay는 USER·CSRF·owner를 검증하되 새 위치 write가 아니므로 현재 위치 동의와 write quota를 다시 소비하지 않는다.
- idempotency 원장은 raw key, request/response JSON, label, display name, 좌표를 저장하지 않는다. key와 canonical body는 서로 다른 domain의 versioned HMAC digest로만 저장하며, key rotation 시 모든 unexpired 24시간 row를 조회할 이전 key version을 유지한다. receipt는 세 resource ID와 생성·만료 시각만 포함한다.
- active receipt의 resource FK는 hard purge를 보호한다. soft delete 뒤 replay는 원래 ID receipt만 반환하고 자원을 복구하지 않는다. 계정 삭제는 ledger를 먼저 제거하며 export에는 사용자 장소·즐겨찾기만 포함하고 내부 digest/ledger를 제외한다.
- history `requestSummary`는 좌표와 Provider ID가 없어도 집·학교 같은 표시명이 포함될 수 있는 민감정보다. owner-only 응답과 `Cache-Control: no-store`를 적용하고 URL, Service Worker cache, local/browser storage, analytics, trace, notification preview에 넣지 않는다.
- legacy favorite JSON은 typed 조건으로 추정하지 않는다. 현재 active owner-bound saved place 두 곳과 엄격히 검증된 `searchConditions`가 모두 있을 때만 quick search를 허용한다.

## 내부 서비스 인증

- GCE private network 또는 host-internal Docker network
- Service workload만 Routing ingress 허용
- 짧은 수명의 signed JWT 또는 workload identity
- `iss`, `aud`, `exp`, `jti` 검증
- caller·correlation audit

## Secure SDLC

- branch protection과 mandatory review
- secret scanning
- SAST·dependency·container·IaC scan
- SBOM과 image provenance
- contract compatibility와 migration check
- production 관리자 MFA
- model activation·mapping override·data export audit

## 상용 출시 검토

- Kakao·Kakao Mobility 상용 사용·저장·표시 조건
- TMAP·ODsay 저장 제한
- GBIS·GITS·KMA 출처·이용조건
- 국내 개인정보·위치정보 관련 의무
- 택시비·ETA·승차 가능성 표현의 오인 가능성
