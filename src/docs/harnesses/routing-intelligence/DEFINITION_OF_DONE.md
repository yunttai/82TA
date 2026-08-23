# Routing & Intelligence Definition of Done

## Contract

- [ ] common lock passes
- [ ] private OpenAPI response validates
- [ ] code registry only
- [ ] backward compatibility reviewed

## Domain

- [ ] no Django/ORM/HTTP/provider raw dependency
- [ ] unit/property tests
- [ ] deterministic clock/replay
- [ ] strict budget and time invariants

## Provider

- [ ] adapter + normal/empty/error/timeout/429/drift fixtures
- [ ] timeout/retry/breaker/cache
- [ ] capability states and storage terms

## Data/Model

- [ ] source/observed/ingested/schema/quality
- [ ] no missing label negative
- [ ] leakage-safe split
- [ ] metrics/calibration/coverage
- [ ] artifact hash/schema/model card
- [ ] shadow/canary/rollback where applicable

## Operations

- [ ] metrics/log/trace without user identity/plate
- [ ] 6.5s deadline behavior
- [ ] PARTIAL fallback
- [ ] cost/quota impact
- [ ] runbook update

## QA

- [ ] mapping gold set
- [ ] replay route diff
- [ ] contract provider test
- [ ] security/performance/resilience
- [ ] Service consumer integration evidence
