# Service Product Team Blueprint

## Full Vertical Slice

1. lead: requirements/tasks/dependencies
2. UX: state and information contract
3. backend/data: Public API, Gateway, persistence
4. frontend: generated client, views, map
5. security: auth/privacy/abuse
6. QA: every boundary incrementally

## Mandatory message routes

- UX -> Frontend: state names, labels, edge cases
- Backend -> Frontend: fixture and operation availability
- Data -> Backend: ownership, transaction, delete rules
- Frontend + Backend -> QA: producer/consumer file pair
- Any agent -> contract-steward: shared meaning change
