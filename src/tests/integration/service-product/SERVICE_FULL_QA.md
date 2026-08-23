# Service Product Full QA

Date: 2026-08-23 (Asia/Seoul)

Contract: `1.1.0`

Aggregate SHA-256:
`80ade2452c103c534ac88deb5b832d21c27d0bd8eee8d5c5f270bb5491ffdb1a`

## Verdict

The local canonical Stub/Replay Service Product slice is `PASS`. Its exercised
boundary is React Web/PWA -> Public Django Service API -> generated Private
client / Stub or Replay RoutingGateway. It does not move provider, Bus
Intelligence, model, candidate generation, or ranking logic into Service.

Internet staging is `NO-GO`: the repository evidence does not verify a real
Routing producer, Kakao Local/Maps, AWS apply, managed PostgreSQL/PostGIS,
physical iOS/Android devices, or live privacy/restore/rollback drills. The
local WebKit project also cannot launch on this host because its GTK/GStreamer
and media libraries are absent. These are release-evidence blockers, not
failures of the exercised local Stub/Replay slice.

## Coherence matrix

| Boundary | Verdict | Evidence |
|---|---|---|
| Public OpenAPI -> Django routes | PASS | Every Public path resolves; 106 Django tests pass |
| Public OpenAPI -> generated TypeScript -> React wrapper/pages | PASS | All operations and paths are present; typecheck, build, and React tests pass |
| Browser -> Service ownership | PASS | Browser source has no Private Routing, GBIS, Kakao Mobility, model, or raw-provider calls |
| Public request -> generated Private Python / Http, Stub, Replay | PASS locally | Schema-valid translation, locked fixture round-trip, gateway/error tests |
| Private response -> public-safe projection | PASS locally | Contract tests and Django projection tests; private provenance and identifiers are not leaked |
| Service DBML -> ORM -> migration | PASS locally | The canonical 13-table set is identical; WGS84 fields map to PostgreSQL `geography(Point,4326)` after the PostGIS extension; no migration drift |
| URL -> page/link | PASS | Static account/support/privacy paths and dynamic search/route/bus paths are covered |
| COMPLETE/PARTIAL/error/unknown/stale/low-confidence | PASS locally | React branches, registry parity, capability gates, HIGH-only mapping gate, Chromium E2E |
| Offline and retry | PASS locally | API/POST is never cached, offline submit is blocked, and an uncertain result retries the identical body and idempotency key only after user action |
| Redis coordination | PASS locally | Cross-worker single-flight, replay/conflict, lease abandon, hashed keys and fail-closed outage branches pass with the test backend; live multi-worker load is unverified |
| Generated clients | PASS with consolidation caveat | Sources are present, no longer ignored, pinned, and byte-reproducible; primary must verify they are included in the final commit/clean checkout |
| PWA install/update/offline | PASS locally | Manifest/iOS assets, shell-only cache, explicit update confirmation, offline E2E |
| Mobile accessibility | PASS on Chromium | 320 px reflow and axe serious/critical gate pass; map-picker semantics are covered |
| iOS/WebKit | UNVERIFIED | Playwright WebKit cannot launch because host runtime libraries are missing |
| Real external integrations | UNVERIFIED | No credentialed Kakao, live Routing, AWS staging, or device run was in scope |

## Executable evidence

| Command | Result |
|---|---|
| `manage.py test -v 1` | PASS, 106/106 |
| `manage.py test ../../tests/security/service-product -v 1` | PASS, 28/28 |
| `manage.py test ../../tests/integration/service-product -v 1` | PASS, 16/16 |
| `python -m unittest discover -s src/tests/contracts -p 'test_*.py' -v` | PASS, 14/14 |
| `python3 -m unittest discover -s src/tests/e2e -p 'test_*.py' -v` | PASS, 4/4 |
| `npm test` | PASS, 41/41 |
| `npm run typecheck` | PASS |
| `VITE_PRIVACY_DOCUMENT_VERSION=qa-policy-v1 npm run build` | PASS |
| `VITE_PRIVACY_DOCUMENT_VERSION=qa-policy-v1 npm run test:e2e -- --project=mobile-chromium` | PASS, 3/3 |
| production `manage.py check --deploy` with non-secret QA settings | PASS, no issues |
| `bash src/generated/verify-reproducibility.sh` | PASS |
| `python3 src/infra/scripts/validate_infra.py` | PASS, 8/8 and Compose config; this QA shell skipped Terraform because its CLI is absent |
| Infra-owner Terraform 1.9.8 `fmt -check`, staging `init`/`validate` | PASS |
| Infra-owner non-root image builds and Browser -> Django -> Stub Compose smoke | PASS; marker coordinate absent from logs |
| `validate_repository.py`, `verify_contract_lock.py`, `compare_context_snapshots.py` | PASS |

The WebKit command starts all three tests but none reaches application code; the
browser process refuses to launch due to missing host libraries. This is an
environment gap, not an application assertion failure.

## Contract and data-boundary impact

QA introduced no shared contract or database semantic change. The tests consume
the frozen Public/Private OpenAPI, code registry, Service DBML, generated clients,
and locked fixtures directly. Numeric zero remains distinct from unknown,
unsupported capability remains distinct from low risk, and Bus values are shown
only when the canonical mapping grade is `HIGH`.

The following product requests remain contract-gated and are not counted as
implemented: USER login/registration/recovery, guest-to-USER merge, an
authenticated short-lived/one-time export download operation, individual
history deletion/retention settings, consent-document distribution, typed
favorite/privacy/bus-outcome extensions, canonical saved-time, public degraded
copy registries, and a server-owned freshness threshold.

## Security and privacy

- Browser credentials stay same-origin and CSRF-protected; the browser never
  receives or calls the Private Routing service token.
- Public projection strips Service identity/display-only values before the
  Private request and does not expose private raw provider/model fields.
- Guest/history persistence is owner-scoped; history saving is explicit opt-in.
- Consent records accept only the server-owned current document version; the
  deployed web build must be pinned to the same published version.
- The service worker does not cache API requests or non-GET traffic.
- Production settings require HTTPS origins, secure cookies, PostgreSQL, an
  explicit RoutingGateway, and verified TLS for HTTP Routing mode.
- The staging topology requires CloudFront-to-ALB HTTPS, an ALB 443 listener
  with a matching certificate and Route53 alias, and limits ALB ingress to the
  CloudFront managed prefix list. Missing DNS/certificate inputs fail Terraform
  preconditions; health checks use private `/infra/healthz` without weakening
  public HTTPS redirects.

The bounded export/deletion worker, encrypted filesystem artifact store,
fail-closed physical purge, scheduled worker/purge infrastructure and DLQ are
implemented and pass local/static tests. Release still requires the governed
download contract plus live export, TTL purge, account deletion, backup,
analytics, DLQ/alarm and recovery drills.

The following risks remain non-blocking for the trusted local slice but must be
closed before broader release:

- `SEC-M-01`: the Private Routing response has no Service-side byte ceiling and
  canonical `Geometry.value` size/shape limit. Adding canonical limits requires
  a governed shared-contract change; QA did not invent a local contract.
- Redis-backed idempotency and rate coordination is implemented. Staging still
  needs real Redis/TLS, multi-worker retry/load, quota and outage evidence.

## Retest

```bash
cd src/services/service-api
.venv/bin/python manage.py test -v 1
.venv/bin/python manage.py test ../../tests/integration/service-product -v 1
.venv/bin/python manage.py test ../../tests/security/service-product -v 1

cd ../../apps/web
npm test
npm run typecheck
VITE_PRIVACY_DOCUMENT_VERSION=<published-version> npm run build
VITE_PRIVACY_DOCUMENT_VERSION=<published-version> npm run test:e2e -- --project=mobile-chromium
VITE_PRIVACY_DOCUMENT_VERSION=<published-version> npm run test:e2e -- --project=mobile-webkit

cd ../../..
src/services/service-api/.venv/bin/python -m unittest discover \
  -s src/tests/contracts -p 'test_*.py' -v
python3 -m unittest discover -s src/tests/e2e -p 'test_*.py' -v
bash src/generated/verify-reproducibility.sh
python3 src/infra/scripts/validate_infra.py
python3 src/scripts/validate_repository.py
python3 src/scripts/verify_contract_lock.py
python3 src/scripts/compare_context_snapshots.py
```

Rollback is limited to the Service QA tests and this report; no production code
or shared contract artifact is owned by this QA change.
