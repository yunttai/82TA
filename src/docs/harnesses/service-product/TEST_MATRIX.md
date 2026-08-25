# Service Product Test Matrix

| 영역 | Producer | Consumer | 필수 검증 |
|---|---|---|---|
| Public route response | Service serializer | TS client/query | shape·wrapper·null·enum |
| Routing response | Routing OpenAPI | Python generated client | field·unit·unknown enum |
| UI route | router config | links/navigation | 존재·dynamic param |
| Search state | backend state | UI branch | reachable·dead state |
| Capability | support API | form control | unsupported hidden/disabled |
| Reason/warning | registry | label renderer | 1:1·generic fallback |
| Service DB | DBML/migration | ORM/query | null·index·retention |
| Privacy | request/log | log sink | exact coordinate·token 없음 |
| History | accepted route search | history list/card | current consent auto-save exactly once; coordinate-free summary; no replay |
| Favorite create | atomic from-places API | favorite form/list | two places+favorite all-or-nothing; consent/idempotency/owner |
| Favorite quick search | typed favorite+saved places | route-search POST/result navigation | click-time request exactly once; mount/back/reload do not submit |

## Fixture Matrix

- complete with all recommendations
- partial without bus data
- partial with ETA fallback
- no feasible strict budget
- transit provider unavailable
- expired result
- unknown warning enum
- geometry partial
- upstream stop
- Taxi Bridge

## Browser Matrix

- current Chromium·Edge
- current Safari mobile equivalent 검토
- Android PWA install flow
- reduced motion·keyboard navigation·screen width

## Mobile PWA Matrix

| Boundary | Scenario | Required evidence |
|---|---|---|
| Manifest | 192/512/maskable/apple-touch icons, id/scope/start URL, standalone | Chromium Application audit and iOS Home Screen icon |
| Install | Android prompt, iOS manual Home Screen guide, already-installed suppression | Playwright where supported + device smoke |
| Update | waiting worker, accept/defer/failure, search in progress | no automatic reload or draft/result loss |
| Offline | initial shell, before submit, connection lost after POST | `/api/**` not cached; no automatic POST on reconnect |
| Privacy cache | places, route result, history, saved places, account | Cache Storage/IndexedDB/localStorage inspection shows no sensitive payload/token |
| iOS layout | safe area, dynamic viewport, software keyboard, standalone | iPhone Simulator/real Safari screenshots and interaction log |
| Android layout | system back, keyboard, standalone, landscape | Android Emulator/real Chrome interaction log |

## Component and State Matrix

| Component | Required states |
|---|---|
| Place combobox | empty, typing, loading, results, no result, retryable error, rate-limited, selected |
| Current location | prompt, requesting, granted, denied, unavailable, timeout, insecure context |
| Map picker | loading, ready, dragging, resolving, SDK failure, offline fallback |
| Search | IDLE, VALIDATING, SEARCHING, COMPLETE, PARTIAL, NO_FEASIBLE_ROUTE, PROVIDER_UNAVAILABLE, FAILED, EXPIRED |
| Recommendation slot | populated, null, duplicate routeId across slots, contract-invalid route |
| Geometry | full GEOJSON, full POLYLINE, NONE, partial, decode/schema error |
| Bus panel | LIVE, PARTIAL, HISTORICAL, UNSUPPORTED, UNKNOWN; HIGH/MEDIUM/LOW/UNKNOWN confidence |
| Bus value | observed seat 0 vs null; probability 0 vs unavailable; stale vs fresh; proxy disclosure |
| Guest/session | create, GUEST/USER inspect, expire, revoke, rate-limit; token memory-only/non-display |
| Account collection | logged out, loading, empty, populated, owner-hidden not-found, retryable error |
| Preference | GET ETag, PUT If-Match, saved response ETag, version conflict/reload/reconfirm |
| Consent | each canonical type accepted/declined, document version, consent-required recovery |
| Data rights | export/delete PENDING, RUNNING, COMPLETE, FAILED, conflict, not-found, expired download URL |
| History | logged out, consent off, loading, empty, summary present/null, expired, retryable error |
| Favorite | empty, create consent-required/submitting/conflict/success, typed ready, legacy invalid, deleted place, quick-search loading/error |

## Accessibility Matrix

| Check | Acceptance |
|---|---|
| Keyboard | all actions reachable; visible focus; combobox arrows/Enter/Escape; modal focus return |
| Screen reader | landmarks/headings; P50/P90 and expected/upper spoken meanings; deduplicated status/alert |
| Touch | minimum 44×44 CSS px target; no hover-only information |
| Reflow | 320 CSS px and 200% text without loss of primary action or two-dimensional page scroll |
| Contrast | WCAG 2.2 AA; selection/error/mode not color-only; forced-colors usable |
| Motion | reduced-motion removes nonessential pan, shimmer, and transitions |
| Device assistive tech | VoiceOver smoke on iOS; TalkBack smoke on Android |
| Favorite actions | `바로 길찾기`와 추가/삭제가 44×44 이상; submit 중 해당 카드만 disabled; status 중복 announce 없음 |
| iPhone keyboard | favorite 장소 combobox·조건 form의 오류/primary action이 software keyboard와 safe area에 가려지지 않음 |

## Contract-gap Gate

Public 1.5.0 resolves email registration/login with nickname and consent capture, guest/session inspection and revoke, consent-driven automatic history plus display-only request summary, saved-place/favorite CRUD, typed favorite conditions, atomic favorite creation from arbitrary places, preference ETag conflict, consent CRUD, and asynchronous export/deletion jobs. The following remain `BLOCKED` rather than being simulated with local API shapes: account recovery/email verification and guest merge, individual history delete/retention setting, consent-document distribution, typed privacy preferences/feedback bus outcome/transit details, canonical baseline saved-time, public degraded/failure copy registries, and a server-owned freshness threshold.

## Security

- IDOR on search/history/favorite
- CSRF state changes
- USER/current consent enforcement for history and exact-location favorite creation
- atomic rollback and owner-scoped idempotency conflict for favorite from-places
- deleted/other-owner saved-place quick search fail closed
- XSS place/provider strings
- guest token guess/reuse
- login brute force/rate limit
- localStorage credential absence
