# Web App Scope

- Workstream 1 owns this tree.
- React/TypeScript/PWA only.
- Call Service Public API only; never call Routing directly.
- Do not recompute routing duration, fare, ranking, ETA, or model probability.
- Use generated clients from `src/generated/`; no duplicate DTOs.
- Cover loading, COMPLETE, PARTIAL, NO_FEASIBLE_ROUTE, unsupported, stale, and error states.
- Preserve accessibility and exact-location log redaction.
