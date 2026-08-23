# Service Product Epic Backlog

공통 요구 ID는 `src/docs/shared/PRD.md`를 참조한다. 각 Epic은 contract·test·security 작업을 함께 포함한다.

## SP-E01 Foundation

**목표:** React App, Django Service, generated client, local integration 기반.

- SP-001 source layout와 package manager 결정
- SP-002 React+TS strict app shell·PWA manifest
- SP-003 Django settings/env/local test skeleton
- SP-004 Service DB migration baseline
- SP-005 OpenAPI TS/Python client generation
- SP-006 StubRoutingGateway와 fixture
- SP-007 correlation·Problem Details middleware
- SP-008 unit·contract CI

**Acceptance:** Browser→Service→Stub Routing의 route search가 fixture를 렌더링한다.

## SP-E02 Place Search

- SP-020 Kakao Local adapter
- SP-021 address/keyword/reverse/region normalization
- SP-022 debounce·cache·rate limit
- SP-023 current location permission
- SP-024 duplicate place distinction
- SP-025 saved/recent/provider result UX
- SP-026 XSS·input length·coordinate tests

**Dependency:** Kakao Local key·domain policy.

## SP-E03 Route Search Command

- SP-030 public request validation
- SP-031 guest token·user ownership
- SP-032 idempotency store
- SP-033 RoutingGateway deadline/auth
- SP-034 public error mapping
- SP-035 search state persistence
- SP-036 expiry/cache policy
- SP-037 request contract test

## SP-E04 Result Projection

- SP-040 internal→public projection
- SP-041 remove raw/plate/model URI
- SP-042 recommendation label mapping
- SP-043 reason/warning localization
- SP-044 capability/support projection
- SP-045 projection snapshot version
- SP-046 unknown enum fallback

## SP-E05 Route Results UI

- SP-050 recommendation cards
- SP-051 baseline/Pareto budget comparison
- SP-052 route leg timeline
- SP-053 map polyline and mode styles
- SP-054 Bus Intelligence panel
- SP-055 provenance/freshness/confidence
- SP-056 COMPLETE/PARTIAL/no route/provider down/expired
- SP-057 responsive/accessibility

## SP-E06 Identity & Preferences

- SP-060 guest first flow
- SP-061 email/social login
- SP-062 secure session·CSRF
- SP-063 preference CRUD/version conflict
- SP-064 saved place CRUD
- SP-065 favorite journey CRUD
- SP-066 consent records
- SP-067 auth security tests

## SP-E07 History & Feedback

- SP-070 history list/detail
- SP-071 save opt-in and retention
- SP-072 route feedback
- SP-073 anonymized feedback event projection
- SP-074 deletion/export
- SP-075 backup/analytics deletion policy

## SP-E08 Support & Operations

- SP-080 public capability page
- SP-081 Provider degraded banner
- SP-082 frontend error telemetry
- SP-083 Service metrics/dashboard
- SP-084 rate-limit/cost abuse detection
- SP-085 admin access boundary

## SP-E09 Security & Privacy Hardening

- SP-090 threat model
- SP-091 CSP/CORS/cookie/CSRF
- SP-092 secret scan and key exposure tests
- SP-093 PII logging redaction
- SP-094 ownership/IDOR tests
- SP-095 privacy policy implementation hooks
- SP-096 penetration findings

## SP-E10 Integration & GA

- SP-100 real Routing client swap
- SP-101 consumer contract test
- SP-102 cross-boundary QA
- SP-103 staging E2E representative routes
- SP-104 load/accessibility/browser matrix
- SP-105 deploy/rollback
- SP-106 user data deletion drill
- SP-107 GA checklist
