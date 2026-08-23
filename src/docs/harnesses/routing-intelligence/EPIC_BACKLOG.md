# Routing & Intelligence Epic Backlog

## RI-E01 Domain & Contract Foundation

- RI-001 canonical entities/value objects
- RI-002 request/response generated models
- RI-003 pure domain dependency rules
- RI-004 ranking/config versioning
- RI-005 error/warning/reason registry
- RI-006 deterministic clock/ID abstractions

## RI-E02 Provider Capability Spike

- RI-020 Kakao transit/walk live verification
- RI-021 driving fare/traffic
- RI-022 multi-destination/origin/future permissions
- RI-023 GBIS endpoints/schema
- RI-024 KMA forecast/ASOS
- RI-025 GITS access
- RI-026 production/storage/quota matrix

## RI-E03 Provider Core

- RI-030 adapter protocols
- RI-031 envelope/schema validation
- RI-032 timeout/retry/breaker
- RI-033 cache/single-flight
- RI-034 fixture/replay capture
- RI-035 capability registry

## RI-E04 Baseline Hybrid Routing

- RI-040 transit normalization
- RI-041 taxi-only/exact driving
- RI-042 access/egress hub search
- RI-043 pattern generation
- RI-044 time propagation
- RI-045 strict budget
- RI-046 Pareto and four rankings

## RI-E05 Routing Data Platform

- RI-050 PostgreSQL/PostGIS schema
- RI-051 legacy import
- RI-052 observation partition/index
- RI-053 collector/checkpoint/DLQ
- RI-054 quality gate
- RI-055 object dataset layout

## RI-E06 Entity Mapping

- RI-060 route/stop fingerprints
- RI-061 signal extraction
- RI-062 score/grade/version
- RI-063 gold set and review queue
- RI-064 mapping precision metrics
- RI-065 LOW no enrichment

## RI-E07 Bus Intelligence Seat

- RI-070 trip identity
- RI-071 target stop label with NULL
- RI-072 capacity registry
- RI-073 seat feature builder
- RI-074 LightGBM baseline/calibration
- RI-075 online runtime/coverage

## RI-E08 Bus Intelligence ETA

- RI-080 segment target/history
- RI-081 ETA feature builder
- RI-082 quantile/conformal interval
- RI-083 official ETA arbitration
- RI-084 batch inference
- RI-085 slice evaluation

## RI-E09 Expected Wait & Transfer

- RI-090 multi-vehicle boardability distribution
- RI-091 tail headway
- RI-092 expected/P90 wait
- RI-093 transfer margin P50/P90
- RI-094 general vs seat bus policy
- RI-095 ranking reversal tests

## RI-E10 Differentiation

- RI-100 upstream stop candidate
- RI-101 Taxi Bridge
- RI-102 arrival deadline/minimum budget
- RI-103 taxi dispatch wait model
- RI-104 efficient marginal gain

## RI-E11 Model Operations

- RI-110 registry/artifact hash
- RI-111 feature schema parity
- RI-112 shadow/canary/rollback
- RI-113 prediction audit/drift
- RI-114 model cards

## RI-E12 Performance, Security, GA

- RI-120 6.5s deadline/load shedding
- RI-121 provider cost/quota
- RI-122 service JWT/private ingress
- RI-123 artifact/SSRF/schema drift tests
- RI-124 replay/performance/resilience
- RI-125 dashboards/runbooks
- RI-126 GA field validation
