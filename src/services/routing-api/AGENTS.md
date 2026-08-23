# Routing API Scope

- Workstream 2 owns this tree.
- Django Routing API exposes the private contract and delegates to pure routing/application packages.
- No account, email, favorites, saved-place labels, or Service DB access.
- Enforce service auth, request deadline, idempotency, partial semantics, provenance, and capability gates.
