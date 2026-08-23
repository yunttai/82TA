# Provider Integration Specification

## Adapter Protocols

- TransitRouteProvider.search
- WalkRouteProvider.route
- DrivingRouteProvider.route/manyDestinations/manyOrigins/future
- BusRealtimeProvider.arrivals/locations/routes/stations
- WeatherContextProvider
- TrafficContextProvider

## Envelope

provider, operation, fingerprint, fetchedAt, observedAt, status, schemaVersion, freshness, normalizedCount, qualityFlags, optional payloadRef.

## Rules

- fixed URL allowlist
- credential outside code
- input validation
- response size/time limit
- XML external entity disabled
- minimum schema validation
- exact observed timestamp
- retry only within deadline
- per-provider concurrency semaphore
- circuit breaker·negative cache·single-flight

## Kakao Transit↔GBIS

Signals:

- normalized route name/type
- boarding/alighting name and coordinate
- route stop sequence and direction
- origin/destination
- route geometry
- live vehicle existence

HIGH >= proposed 0.92; MEDIUM 0.80~0.92; LOW<0.80. Threshold must be calibrated with gold set.

## Capability

DOCUMENTED, KEY_VERIFIED, PRODUCTION_APPROVED are independent fields. Multi-destination unavailable must trigger bounded single fallback, not product outage.

## Schema Drift

Missing required path, type/enum change, timestamp reversal, coordinate error, result count shift:

1. operation degraded
2. sanitized sample quarantine
3. alert
4. no fabricated zeros
5. fallback/PARTIAL
