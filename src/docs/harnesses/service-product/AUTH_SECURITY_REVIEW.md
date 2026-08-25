# Email IAM Security Review

Date: 2026-08-23; history/favorite addendum 2026-08-25
Contract: Public 1.5.0

- Passwords are accepted only over CSRF-protected JSON mutations, bounded to 12–128 characters and stored with Django's adaptive one-way password hasher. Plaintext credentials are not logged, returned or audited.
- Login returns the same `INVALID_CREDENTIALS` response for an unknown email and an incorrect password and performs a dummy hash check for unknown users.
- Registration and login use bounded per-client rate limits. Production continues to require HTTPS, secure cookies, trusted hosts and Redis-backed coordination.
- Authentication rotates the Django session, uses HttpOnly/SameSite cookies and records a hashed authenticated-session identifier. Logout revokes the authenticated-session record and flushes the browser session.
- History, saved places, favorites, preferences and data-rights endpoints retain their USER owner checks. Guest route search remains available and guest data is not silently merged into an account.
- Current-session email is returned only to its authenticated owner and every auth/session response is `no-store`.

## History and favorite addendum

- A valid route search remains available to guests and users who decline `SEARCH_HISTORY`. Only an authenticated USER with a current accepted consent sends `saveToHistory=true`; the Web has no per-search history checkbox. Validation failures and unaccepted searches create no durable history, and idempotent retries create exactly one record.
- History `requestSummary` is display-only and omits coordinates, addresses and provider IDs. The client must not reconstruct a new route-search request from it. Display names may still reveal home or workplace information and therefore stay out of URLs, telemetry, persistent browser storage, notification previews and Service Worker caches.
- `POST /api/v1/me/favorite-journeys/from-places` requires the current USER, CSRF, current `PRECISE_LOCATION` consent, bounded input, rate limiting, `no-store`, owner-scoped idempotency and a single database transaction. Logs and idempotency keys must not contain labels or coordinates.
- Favorite quick search resolves only the same owner's active saved places and validated `FavoriteJourneySearchConditionsV1`. Legacy conditions, deleted places and other-owner resources fail closed without exposing whether another resource exists.
- `바로 길찾기` creates one fresh click-time `DEPART_AT` Public route-search. Page mount, reload, browser back/forward and duplicate taps must not trigger extra requests. `saveToHistory` is derived from current consent at execution time rather than stored in the favorite.
- Deleting a saved place invalidates linked favorites. UI confirmation explains the impact without exposing unrelated owner data; an invalid favorite cannot silently fall back to stale coordinates.
- The browser stores canonical `taxiBudget` in typed conditions and uses only the existing fare-cap display converter. It does not recalculate Routing cost, budget feasibility or ranking.

Known follow-ups: email verification, account recovery, credential-stuffing telemetry, guest-to-user merge, and individual history delete/retention controls require a later approved contract change and live delivery infrastructure.
