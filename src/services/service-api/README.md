# Django Service Backend

사용자 인증, 장소 검색 proxy, 사용자 입력 검증, Routing Gateway, 검색 기록, 즐겨찾기, 설정, 개인정보 권리를 구현한다. 교통 Provider와 모델을 직접 호출하지 않는다.

## Public Service API 1.5.0

```bash
uv sync
uv run python manage.py test
uv run python manage.py runserver
```

The backend implements the Public 1.5.0 endpoint set for guest/session lifecycle,
place suggestion/reverse geocoding, route search/history/detail/feedback,
preferences, saved places, favorite journeys, consents, data export/deletion
jobs, capabilities, and health. Requests and Routing responses are validated
against the locked OpenAPI sources under `src/contracts/`.

Development defaults to the canonical `stub` gateway so valid dynamic
`DEPART_AT` UI requests can exercise the full browser-to-Service flow. Use
`SERVICE_ROUTING_GATEWAY=replay` for exact deterministic replay; a request that
does not match the locked public fixture then returns an honest `503`.
`SERVICE_ROUTING_GATEWAY=http` uses the generated Private Python client and
requires `SERVICE_ROUTING_API_BASE_URL`, an exact host allowlist, and a shared
`SERVICE_ROUTING_JWT_SECRET`. Production also requires explicit
`SERVICE_ROUTING_JWT_ISSUER` and `SERVICE_ROUTING_JWT_AUDIENCE` values matching
the Routing deployment. Each request receives a short-lived HS256 JWT.
It forwards only canonical coordinates/constraints plus correlation,
idempotency, and deadline headers; user identity, guest credentials, place
labels, and provider place IDs never cross the Routing boundary.
The public correlation ID is forwarded exactly only after strict syntax and
length validation so one safe identifier traces the public and private hops.

In production, `SERVICE_ROUTING_API_BASE_URL` must be an HTTPS origin without
userinfo, path, query, or fragment. Its normalized hostname must exactly match
one of the comma-separated `SERVICE_ROUTING_API_ALLOWED_HOSTS`; redirects are
never followed. TLS verification cannot be disabled in production. Malformed,
schema-invalid, or undocumented Routing responses map to a safe 502 for route
searches and an `UNKNOWN` degraded capability response. Routing responses are
requested with identity encoding and rejected if encoded or larger than
`SERVICE_ROUTING_MAX_RESPONSE_BYTES` (default 2 MiB) before generated model/JSON
parsing.

Kakao Local is enabled only when `KAKAO_REST_API_KEY` is present, and the key
is mandatory in production. Without a key in development, suggestion returns
an empty canonical list and reverse geocoding returns a coordinate-only safe
placeholder so local/mobile development remains usable.
The fixed Kakao base URL is not user-configurable, redirects are disabled, and
responses are schema-normalized before returning to the browser.
Kakao responses use the same identity-encoding rule and a separate
`SERVICE_KAKAO_LOCAL_MAX_RESPONSE_BYTES` bound (default 512 KiB).

Public 1.5.0 provides CSRF-protected email registration and login backed by
Django adaptive password hashing and an HttpOnly/SameSite session cookie.
Authentication attempts are rate limited and login failure does not reveal
whether an email exists. A route POST without a credential gets an ephemeral browser guest session;
explicit `POST /api/v1/guest-sessions` additionally returns a one-time opaque
guest token whose hash alone is stored. `saveToHistory=true` remains restricted
to an authenticated user with current `SEARCH_HISTORY` consent.

Consent purposes use one server-owned current registration-document bundle.
Development defaults the bundle to `local-development`; production must set
`SERVICE_CONSENT_DOCUMENT_VERSION`. Purpose-specific version variables are
rejected because the Public registration request and Web build intentionally send
one `documentVersion` for all five purposes. Submitted stale or unknown versions
are rejected without recording them, and an older accepted record no longer
authorizes history or feedback after a configured document rotation. The Web
build's `VITE_PRIVACY_DOCUMENT_VERSION` must exactly match the Service bundle
version.

Data export and deletion requests are consumed by the bounded command:

```bash
uv run python manage.py process_data_rights_jobs --limit 100
uv run python manage.py purge_service_data
```

Run both from a single scheduled worker (or with database-backed worker
concurrency; PostgreSQL uses `skip_locked`). Export payloads are written only
through an internal artifact abstraction. Production must explicitly set
`SERVICE_DATA_RIGHTS_ARTIFACT_BACKEND`. `disabled` fails export jobs closed;
`encrypted-filesystem` additionally requires an absolute private mounted
`SERVICE_DATA_RIGHTS_ARTIFACT_DIRECTORY` and a Fernet
`SERVICE_DATA_RIGHTS_ARTIFACT_ENCRYPTION_KEY`. Files are atomically replaced,
encrypted before write, and restricted to directory mode `0700` and file mode
`0600`. Keep the key available for at least the export TTL and configure
`SERVICE_DATA_RIGHTS_EXPORT_TTL_SECONDS` (default 900 seconds).

The purge lifecycle deletes the physical artifact before clearing its database
reference. A failed physical deletion retains the reference and writes a safe
audit event for retry. Account hard deletion likewise fails closed until all of
that account's export artifacts are physically removed. Deletion jobs remain
`RUNNING` through the canonical 30-day grace period; completion atomically
removes the owner-bound job with the account and leaves a de-identified
`DATA_DELETION_COMPLETED` audit event.

Public 1.5.0 currently has no authenticated artifact-download operation, so
`downloadUrl` intentionally remains `null`. Infrastructure wires the encrypted
filesystem backend to private EFS and schedules both lifecycle commands, but a
short-lived owner-bound delivery contract plus live worker, backup/analytics
deletion, and recovery drills remain staging release gates. The filesystem
backend is suitable only when the mounted volume itself is private and durable.

Production startup requires `SERVICE_ENVIRONMENT=production` and a non-empty
`SERVICE_SECRET_KEY`, and requires `SERVICE_ROUTING_GATEWAY` to be selected
explicitly. It also requires a PostgreSQL `DATABASE_URL`; SQLite remains only
the default for development and tests. The runtime installs `psycopg` from the
locked Service dependency set. The initial PostgreSQL migration enables PostGIS
before creating `geography(Point,4326)` columns, and the field adapter decodes
EWKT/EWKB into the canonical `{lon, lat}` object. A live managed-PostgreSQL
migration plus saved-place/search coordinate round-trip remains a staging gate,
including confirmation that the migration role may install the PostGIS
extension (or that operations pre-provisions it).

Guest-session issuance, place suggest/reverse, favorite creation, and route search have
client-address rate limits. Configure them with
`SERVICE_GUEST_SESSION_RATE_LIMIT_PER_MINUTE`,
`SERVICE_PLACE_RATE_LIMIT_PER_MINUTE`,
`SERVICE_FAVORITE_WRITE_RATE_LIMIT_PER_MINUTE`, and
`SERVICE_RATE_LIMIT_PER_MINUTE`.
Forwarding headers are ignored by default. Behind the ALB, set
`SERVICE_TRUST_PROXY_HEADERS=true` and provide comma-separated exact IPs or
CIDRs in `SERVICE_TRUSTED_PROXY_IPS`. Only a request whose immediate peer is in
those networks may supply forwarding headers; the resolver removes trusted
hops from the right of the append-only `X-Forwarded-For` chain. The ALB must be
configured to append/sanitize XFF, its security group must restrict direct
ingress, and WAF remains the authoritative distributed abuse control. For the
CloudFront → ALB topology, include both the ALB subnet CIDRs and AWS-managed
CloudFront origin-facing CIDRs. The resolver then skips the trusted ALB and
CloudFront hops and selects the viewer address; a forged browser-supplied
leftmost XFF value cannot replace that nearer untrusted hop. Do not add general
public address ranges to this allowlist.

Set `SERVICE_CSRF_TRUSTED_ORIGINS` to comma-separated, exact HTTPS origins for
the CloudFront and custom web domains. Userinfo, paths, queries, fragments,
wildcards, and non-HTTPS values are rejected; this list is distinct from
`SERVICE_ALLOWED_HOSTS`.

Production requires `SERVICE_REDIS_URL` using `rediss://`. Redis provides atomic
per-minute counters and route-search single-flight idempotency leases across
Django workers; an outage fails new rate-limited requests closed with a safe
`429`. The atomic favorite-from-places endpoint instead stores a 24-hour,
owner-scoped immutable receipt in Service PostgreSQL. That receipt stores only
HMAC digests, resource IDs, key version, and timestamps; it never stores the raw
idempotency key, request body, labels, coordinates, or a response snapshot.
Completed favorite replays therefore do not depend on Redis and run before
current consent and write-quota checks. Redis keys and the durable receipt
digests hash client and owner material with secret-keyed, domain-separated HMAC
derived from `SERVICE_REDIS_KEY_DERIVATION_SECRET` when configured, or from the
application secret. `rediss://` connections always require a valid
certificate and matching hostname; URL query overrides are rejected in
production. Development without Redis uses process-local
monotonic TTL/LRU caches. Configure coordination with `SERVICE_REDIS_KEY_PREFIX`,
`SERVICE_REDIS_SOCKET_TIMEOUT_SECONDS`, and `SERVICE_IDEMPOTENCY_LEASE_SECONDS`;
the lease must exceed the Routing deadline and be shorter than the completed
response TTL. Cache and expiry bounds use
`SERVICE_IDEMPOTENCY_CACHE_MAX_ENTRIES`, `SERVICE_IDEMPOTENCY_CACHE_TTL_SECONDS`,
`SERVICE_RATE_LIMIT_CACHE_MAX_ENTRIES`, and
`SERVICE_RATE_LIMIT_CACHE_TTL_SECONDS`. The WAF remains the outer distributed
abuse layer and production application rate limits must remain positive.

`SERVICE_FAVORITE_IDEMPOTENCY_RETENTION_SECONDS` is contract-locked to `86400`
and `SERVICE_FAVORITE_IDEMPOTENCY_DIGEST_KEY_VERSION` is currently locked to
`1`. The active HMAC derivation secret must remain stable for at least the full
24-hour receipt lifetime. Safe online rotation requires a reader key ring that
can derive every unexpired version; until that reader exists, drain the 24-hour
window before rotating the derivation secret. Startup rejects a version change
so a deployment cannot silently bypass an unexpired receipt.
