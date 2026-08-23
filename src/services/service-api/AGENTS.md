# Service API Scope

- Workstream 1 owns this tree.
- Django Service Backend owns identity, guest session, preferences, history, favorites, feedback, place proxy, and `RoutingGateway`.
- Do not call GBIS, Kakao Mobility, KMA, GITS, or model runtimes directly.
- Do not read Routing DB.
- Apply object-level authorization, idempotency, deadline, correlation, privacy, and public-safe projection.
