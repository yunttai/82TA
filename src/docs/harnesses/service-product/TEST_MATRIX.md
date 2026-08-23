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

## Contract-gap Gate

Public 1.2.0 resolves email registration/login, guest/session inspection and revoke, saved-place/favorite CRUD, preference ETag conflict, consent CRUD, and asynchronous export/deletion jobs. The following remain `BLOCKED` rather than being simulated with local API shapes: account recovery/email verification and guest merge, individual history delete/retention setting, consent-document distribution, typed favorite constraints/privacy preferences/feedback bus outcome/transit details, canonical baseline saved-time, public degraded/failure copy registries, and a server-owned freshness threshold.

## Security

- IDOR on search/history/favorite
- CSRF state changes
- XSS place/provider strings
- guest token guess/reuse
- login brute force/rate limit
- localStorage credential absence
