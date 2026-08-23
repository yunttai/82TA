# Provider Core

Framework-independent Provider integration boundary for Routing & Intelligence.
It contains immutable provider-neutral transport values, strict adapter envelopes,
capability gates, endpoint/input/schema validation, bounded resilience primitives,
and deterministic sanitized fixtures.

## Safety and truth state

- No live endpoint, credential, key probe, or production approval is included.
- Missing registry entries are `UNVERIFIED`, `UNAPPROVED`, fixture-only, and disabled.
- `DOCUMENTED`, `KEY_VERIFIED`, and `PRODUCTION_APPROVED` are independent.
- Every named operation also has an independent response-schema gate. It remains
  false, so even an accidental capability promotion cannot execute an unverified
  vendor response normalizer.
- Live execution additionally requires immutable exact-operation key, production,
  and response-schema evidence with IDs, SHA-256 bindings, versions, and unexpired
  validity windows. There is no environment-boolean promotion path.
- Provider dictionaries are parsed only inside adapters. The adapter output contains
  `CanonicalItinerary` values, never raw response fields.
- Unknown, empty, timeout, rate-limited, stale, and schema-drift outcomes remain
  distinct. Schema drift returns `BAD_RESPONSE` without fabricated values.
- URLs resolve through `FixedEndpointAllowlist`; request-selected URLs are rejected.

## Public modules

- `provider_core.canonical`: immutable transport objects and canonical units
- `provider_core.envelope`: status, freshness, quality, timestamps, safe fingerprint
- `provider_core.capabilities`: disabled-by-default capability registry
- `provider_core.protocols`: provider port protocols
- `provider_core.requests`: validated canonical provider inputs
- `provider_core.validation`: exact endpoint and strict object schema validation
- `provider_core.resilience`: deadline, bounded retry, circuit, semaphore, single-flight
- `provider_core.cache`: bounded fresh/stale TTL cache
- `provider_core.adapters.fixture`: sanitized fixture-only transit adapter
- `provider_core.http`: injected bounded HTTP port and secret-safe auth values
- `provider_core.transport`: concrete exact-allowlist HTTPS transport with system TLS,
  DNS/private-address rejection, deadline-derived connect/read bounds, no redirects,
  strict header/body framing, and an expiring external-egress attestation gate
- `provider_core.context`: immutable GBIS, weather, and traffic observations
- `provider_core.context_queries`: versioned KMA grid and bounded GITS corridor
  request identities; equivalent aware instants share deterministic fingerprints
- `provider_core.named`: disabled-by-default named Provider suite and closed fixtures
- `provider_core.runtime`: immutable capability/key/production/schema evidence gate
- `provider_core.telemetry`: secret-free call, retry, quota, cost, and byte counters

The named fixtures use a strict internal sanitized schema to test canonical
normalization. They are not copied vendor payloads and do not establish live schema
compatibility. Unpinned HTTPS operations have no executable URL.

## Production assembly boundary

`ProviderAdapterSuite(transport)` is the fixture/default fail-closed constructor. A
legacy shared `capabilities` or `credential` argument is accepted only as a quarantined
compatibility input and is never forwarded to an adapter. It cannot enable network
execution.

Live composition uses `ProviderAdapterSuite.from_config(ProviderAdapterSuiteConfig)`.
Every entry is a `ProviderOperationBinding` containing a
`ScopedProviderTransport` and `ScopedProviderCredential` whose provider and operation
must match exactly. Duplicate, unknown, missing, or cross-wired scopes fail closed.
The binding API exposes no endpoint, auth location, auth field name, prefix, or custom
header: those remain fixed by the reviewed `EndpointSpec` and exact allowlist.

Even a correctly scoped binding is insufficient. The same operation must independently
pass `DOCUMENTED`, `KEY_VERIFIED`, `PRODUCTION_APPROVED`, non-fixture, response-schema,
and unexpired runtime-evidence gates. The checked-in live response-schema gates remain
false, so this package makes no live Provider success or commercial-readiness claim.

`StrictHttpsTransport` accepts only the fixed endpoint strings supplied by the
composition root. Its resolver and pinned connection factory prevent a validated DNS
name from being re-resolved to a private address during connect. The default factory
uses `ssl.create_default_context()` and therefore the system CA store, hostname
verification, and required certificate validation. An external proxy/firewall cannot
be proven by Python code, so an injected, unexpired `NetworkEgressAttestation` is a
separate fail-closed deployment gate. This attestation is evidence metadata, not proof
that staging or production egress has been tested.

GBIS arrival and location values expose the same provider-scoped opaque
`vehicle_token` join key. A missing arrival token yields `vehicle_join_key=None` and
cannot be joined. `OpaqueVehicleTokenIssuer` HMAC-tokenizes an approved raw identifier;
raw IDs and plates do not enter canonical values or logs.

KMA/GITS context remains optional and fixture-only. `KmaWeatherQuery` derives the
documented DFS grid from WGS84 and rejects caller-supplied grid/coordinate mismatch.
`GitsTrafficCorridorQuery` bounds corridor points, span, padding, response count, and
optional opaque relevant-link IDs before adapter execution. Fixture helpers preserve
exact timezone-aware observation times—including observations later than the query
as-of—so downstream model context can exclude future evidence without converting it
to zero. These guards do not promote either Provider capability or supply a GITS URL.

## Test

From this directory:

```bash
python -m unittest discover -s tests -v
```
