# Routing & Intelligence Handoff Contract

## 수신 보장

Service는 OpenAPI-valid request, opaque requestId, coordinate/time/budget/constraints, locale/timezone, deadline을 보낸다.

Routing은 사용자 identity나 UI label을 요구하지 않는다.

## 반환 보장

- route calculations are authoritative
- status·expiry
- four recommendation IDs
- candidate routes and legs
- P50/P90/fare range
- Bus Intelligence and provenance
- provider/model/mapping/ranking versions
- reason/warning
- computation summary

## Service에 요구하지 않는 것

- Provider orchestration
- mapping/model selection
- raw response storage
- routing fallback
- feature construction

## Contract 요청

UI가 새 필드를 요구하면 Routing internal debug field를 직접 노출하지 않는다. common schema로 설계하고 privacy·compatibility를 검토한다.
