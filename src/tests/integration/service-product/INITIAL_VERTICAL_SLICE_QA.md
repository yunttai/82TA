# Service Product Initial Vertical Slice QA

Verdict: `CONDITIONAL PASS` for the canonical Stub/Replay slice.

Context: contract `1.0.0`, context `1.0.1`, aggregate SHA-256
`c0390f148341e71d3bb9d0f7d13d3036656702c3cc477959c25a0d34a28a1b3a`.

| Boundary | Verdict | Producer | Consumer | Evidence |
|---|---|---|---|---|
| Public request/response | PASS | `service-public.v1.yaml`, Django `journeys/views.py` and `projection.py` | generated `service-client-ts`, React hook/UI | canonical schema validation, TS typecheck, React tests, integration tests |
| Private fixture/projection | PASS | locked Routing request/response examples | Replay/Stub gateway and Service projection | exact replay request equality; private-only fields absent from Public response |
| Dynamic Public→Private translation | UNVERIFIED | Public request | future HTTP Routing gateway | Stub/Replay deliberately forwards the locked Private request; it does not translate dynamic values |
| Browser/Django CSRF | PASS | Django health/CSRF middleware | generated Public client wrapper | health bootstrap, same-origin credentials, `X-CSRFToken`, enforced-CSRF integration test |
| Route ownership | PASS | Django `/api/v1/*` | React app | no `/v1/routes/optimize`, Routing host, GBIS, Kakao Mobility, or model call in Web source |
| Status transitions | PASS for implemented mock states | Public response enum | React hook and result panel | IDLE/VALIDATING/SEARCHING plus COMPLETE/PARTIAL/error/expired unit branches |
| Canonical PARTIAL mock | PASS | locked empty-route Routing fixture | Django projection and React cards | `PARTIAL`, four null recommendations, warning and support retained |
| Service DB | NOT APPLICABLE | `service-db.dbml` | no ORM/migration in this Foundation slice | history/account persistence is intentionally not implemented |
| Real Routing | UNVERIFIED | private Routing API | generated Python client/HTTP gateway | generated fixture parsing exists; no live producer or HTTP gateway is wired |
| Cross-workstream context parity | UNVERIFIED | Service snapshot | Routing snapshot | Routing latest context snapshot is absent |

Known gaps:

- The canonical Routing response names recommendation IDs while `routes` is empty. The
  public-safe projection therefore returns four honest `null` recommendations; populated
  COMPLETE cards are not demonstrated.
- `ARRIVE_BY` is rejected as `UNSUPPORTED_TIME`; the current Private request has no
  canonical arrive-by translation.
- Stub/Replay is fixture-bound: dynamic browser inputs reach Django and receive the
  canonical response, but their coordinates, time, and preferences are not translated into
  a new Private request. Request-fidelity acceptance belongs to the real HTTP gateway slice.
- Public `support` is copied from the locked Public fixture. Live capability projection is
  not exercised by this slice.
- Public `403` CSRF and `502` bad-Routing-response behavior are implemented with canonical
  Problem Details codes but are not listed as responses on Public `POST /api/v1/route-searches`.
  This is a shared-contract documentation gap, not patched locally.
- P90/strict-budget semantic invariant rejection cannot be exercised with the empty-route
  canonical fixture and remains required before populated route integration.

Retest:

```bash
uv run --project src/services/service-api python -m unittest discover \
  -s src/tests/integration/service-product -p 'test_*.py' -v
npm --prefix src/apps/web run typecheck
npm --prefix src/apps/web test -- --reporter=dot
uv run --project src/services/service-api python src/services/service-api/manage.py test journeys.tests -v 2
python3 src/scripts/validate_repository.py
python3 src/scripts/verify_contract_lock.py
```
