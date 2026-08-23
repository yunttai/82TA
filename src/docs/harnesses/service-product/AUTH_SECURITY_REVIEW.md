# Email IAM Security Review

Date: 2026-08-23
Contract: Public 1.2.0

- Passwords are accepted only over CSRF-protected JSON mutations, bounded to 12–128 characters and stored with Django's adaptive one-way password hasher. Plaintext credentials are not logged, returned or audited.
- Login returns the same `INVALID_CREDENTIALS` response for an unknown email and an incorrect password and performs a dummy hash check for unknown users.
- Registration and login use bounded per-client rate limits. Production continues to require HTTPS, secure cookies, trusted hosts and Redis-backed coordination.
- Authentication rotates the Django session, uses HttpOnly/SameSite cookies and records a hashed authenticated-session identifier. Logout revokes the authenticated-session record and flushes the browser session.
- History, saved places, favorites, preferences and data-rights endpoints retain their USER owner checks. Guest route search remains available and guest data is not silently merged into an account.
- Current-session email is returned only to its authenticated owner and every auth/session response is `no-store`.

Known follow-ups: email verification, account recovery, credential-stuffing telemetry and guest-to-user merge require a later approved contract change and live delivery infrastructure.
