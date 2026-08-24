# Place suggestion address incremental QA

Status: PASS for the Service place-address slice.

## Boundary evidence

- Producer: `src/services/service-api/places/adapter.py` maps Kakao
  `road_address_name`, falling back to `address_name`, into optional
  `PlaceRef.address`.
- Contract/client: Public OpenAPI 1.4 declares optional nullable
  `PlaceRef.address`; the generated TypeScript schema contains the same field.
- Consumer: `src/apps/web/src/features/place-search/PlaceField.tsx` renders the
  address beneath the place name, hides the row when absent, and does not expose
  provider identifiers or region-code placeholders.
- Privacy: no new storage, log, analytics, URL or Routing-boundary field was added.

## Verification

- Django full suite: 139 passed.
- Vitest full suite: 47 passed.
- Frontend production build/typecheck: passed.
- Contract suite: 18 passed.
- Generated-client reproducibility: passed.
- Cross-workstream metadata/version coherence: passed.

The full canonical route-chain suite retains one unrelated fixture mismatch in the
Kakao Mobility producer chain (`observedAt`/provider output); it does not touch the
Service place response, generated TypeScript client, or place UI.
