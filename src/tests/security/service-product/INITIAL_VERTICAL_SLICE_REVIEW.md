# Service Product Initial Vertical Slice Security Review

Review date: 2026-08-23 KST

Context: `1.0.1`; contract: `1.0.0`; aggregate SHA-256:
`c0390f148341e71d3bb9d0f7d13d3036656702c3cc477959c25a0d34a28a1b3a`.

## Verdict

`CONDITIONAL_GO` for an internal Foundation release using only Stub/Replay.
No Critical or High finding remains after bounded TTL/LRU abuse caches and the
browser CSRF handshake were added. Internet exposure or Real Routing remains
`NO_GO` until a shared multi-instance limiter/WAF is evidenced. Closed Beta/GA
also requires a production CSP.

## Threat-model delta

The implemented data flow is browser -> same-origin Public Service API ->
canonical Stub/Replay RoutingGateway. Exact origin/destination coordinates and
public display names enter Service. Only the locked private routing request is
forwarded; user identity, saved-place labels, Provider place IDs, and history
flags are excluded. The public search endpoint is an unauthenticated cost and
memory amplification surface.

## Findings

### SEC-SP-001 — Remediated High; residual Medium — abuse control is process-local

Affected flow: `journeys/views.py` rate limiting and idempotency handling.

The original unbounded dictionaries were replaced with finite TTL/LRU caches,
and eviction/expiry/rotating-client tests now cover the memory-exhaustion path.
The residual limiter remains process-local, so multiple workers or instances
multiply the effective per-IP allowance. `REMOTE_ADDR` also represents the
proxy unless the deployment defines a trusted client-IP boundary. No WAF/shared
limiter evidence is present.

Remediation before internet/Real Routing: use an atomic shared rate limiter
keyed by a trusted edge-derived client/guest identity; cap burst and sustained
cost; use a shared idempotency store when retries can reach different workers;
add multi-worker, WAF, and cost-budget tests.

Retest: demonstrate a single limit across workers and no duplicate Routing call
when concurrent retries reach different instances.

### SEC-SP-002 — Remediated Medium — CSRF handshake is implemented

Affected flow: `src/apps/web/src/shared/api/publicService.ts` ->
`POST /api/v1/route-searches`.

Django requires CSRF for the unsafe same-origin request and exposes a cookie
bootstrap on `GET /api/v1/health`. The React client now performs that bootstrap,
reads the CSRF cookie without persisting it, sends `X-CSRFToken`, and fails
closed if bootstrap or cookie retrieval fails. Frontend and Django tests cover
both rejection and success.

Remaining evidence for deployment: preserve same-origin hosting and execute the
flow through the deployed browser/edge configuration; do not exempt the
cost-bearing endpoint from CSRF.

### SEC-SP-003 — Medium — Content Security Policy evidence is absent

React renders Provider and place strings through escaped text nodes and the
review found no `dangerouslySetInnerHTML` or `.innerHTML` sink. However neither
the page nor Service configuration supplies a CSP, despite the workstream
security acceptance. Define and test a production CSP at the serving edge or
application, including the exact Kakao Maps origins only when that integration
is enabled.

### SEC-SP-004 — Low — caller-controlled opaque headers accept loggable content

Correlation IDs allow up to 1,024 arbitrary non-control characters and
idempotency keys allow arbitrary printable characters. Both cross the internal
boundary and may become log fields. Restrict them to short opaque ASCII tokens
or replace externally supplied correlation values; ensure log sinks redact
tokens and exact-location-like content.

## Positive evidence

- Django CSRF middleware rejects an unsafe POST without a matching token and
  accepts the bootstrap cookie plus matching header.
- Production settings require a configured secret and enable Secure cookies,
  HTTPS redirect, HSTS, nosniff, and frame denial.
- Public and Problem responses use `Cache-Control: no-store`.
- React sources contain no browser credential persistence, dangerous HTML sink,
  private Routing endpoint, or direct GBIS/Kakao Mobility orchestration.
- Service forwarding tests exclude identity, display metadata, and history
  flags from the Routing request.
- Lockfiles include artifact hashes; dependency audits reported zero known
  vulnerabilities at review time.
- Focused tests in this directory cover CSRF rejection/success, bounded runtime
  caches, oversized-body safe failure, browser boundary/sink scanning, secret
  assignment scanning, and production setting declarations.

## Commands and results

```text
uv run python manage.py test                                      PASS (17)
npm test -- --run                                                PASS (9)
npm run typecheck                                                PASS
npm run build                                                    PASS
SERVICE_ENVIRONMENT=production ... manage.py check --deploy      PASS
npm audit --omit=dev --audit-level=high                          PASS (0)
uvx pip-audit --path .venv/lib/python3.12/site-packages          PASS (0)
uv run python ../../tests/security/service-product/test_initial_vertical_slice_security.py
                                                                  PASS (8)
python3 src/scripts/validate_repository.py                       PASS
python3 src/scripts/verify_contract_lock.py                      PASS
```

## Release and rollback

Critical/High: none remaining. Internal Stub/Replay Foundation is conditional
on preserving the tested same-origin deployment and production settings.
Internet/Real Routing remains blocked on shared WAF/rate-limit/idempotency
evidence; Closed Beta/GA remains blocked on CSP plus the broader privacy and
data-rights gates. Rollback for this review is removal of this evidence
directory; it does not alter runtime code or canonical contracts.
