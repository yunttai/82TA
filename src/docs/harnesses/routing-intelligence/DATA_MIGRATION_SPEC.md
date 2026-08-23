# Legacy BusCrowdRisk Data Migration Specification

## Source

`yunttai/BusCrowdRisk-KOR`의 SQLite snapshot·feature·label·metric을 새 Routing DB와 versioned datasets로 이동한다.

## Pre-Migration Audit

- source commit/local diff
- DB SHA-256 backup
- table row counts/date range
- route/direction/time coverage
- duplicate/missing/out-of-range
- current diagnostics/artifact metadata

## Mapping

- arrival_snapshot -> bus_arrival_observation
- location_snapshot -> bus_location_observation
- target_route/route_station -> canonical transport/provider entity
- external context -> versioned context tables
- feature/label -> object dataset with schema/target version
- metrics -> model registry

## Critical Correction

- missing future observation label becomes NULL
- trip identity reconstructed
- hardcoded routes become support registry
- plate tokenized
- observed max capacity is evidence, not truth
- live vs historical proxy separated

## Reconciliation

- legacy row count
- date min/max
- route/vehicle aggregate
- seat distribution
- target positive/unknown coverage
- sample row lineage

## Exit

- idempotent import
- checkpoint collector continues without duplicates
- feature/label dataset reproducible
- legacy model card records limitations
