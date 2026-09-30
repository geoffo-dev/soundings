# ADR 0005: Server-side sessions, OIDC code flow with PKCE, CSRF double-submit token

- Status: Accepted · Date: 2026-09-30

## Context

SPEC section 7: OIDC sign-in (Keycloak first; Entra ID and Google documented),
server-side code flow with PKCE, an HttpOnly session cookie, CSRF protection, and "the
browser never sees IdP tokens". Redirect URIs derive from the host the user signed in
on, and several hosts may serve one instance. Authlib 1.8 was verified against
Keycloak 26 ([research R1](../research/backend-libraries.md#3-authlib-180-oidc-with-starlettefastapi-verified-against-keycloak-260)).

## Decision

- **Login:** Authlib's Starlette client, authorization code flow with PKCE (S256),
  `state` and `nonce`. The ID token is validated (signature via JWKS, `iss`, `aud`,
  `exp`, `nonce`). Login-flow state (nonce, code verifier) lives in a server-side cache
  table, so the short-lived `soundings_oidc` cookie (path `/api/v1/auth`, 10 minutes)
  holds only an expiry. It is not the app session.
- **Session:** after login we create a `session` row and set an opaque random id
  (256-bit) in an `HttpOnly; Secure; SameSite=Lax; Path=/` cookie. The row stores the
  user id, created/last-seen times, idle and absolute expiry, and the ID token only for
  RP-initiated logout. Access/refresh tokens are not kept. Logout deletes the row and
  redirects to the IdP end-session endpoint.
- **Session id rotates** at login; all of a user's sessions are revocable by admins.
- **CSRF:** double-submit token. The API sets a non-HttpOnly `soundings_csrf` cookie
  (random, bound to the session); the SPA echoes it in `X-CSRF-Token` on every unsafe
  method (`POST/PUT/PATCH/DELETE`). The server compares it in constant time. Requests
  authenticated by API key (`Authorization: Bearer`) are exempt: no cookie, no CSRF.
- **Hosts:** the redirect URI is built from the request `Host`, checked against the
  configured `base_urls` allow-list (400 otherwise); uvicorn trusts forwarded headers
  only from configured proxies.
- Phase 1 uses a **dev-only login stub** (`SOUNDINGS_DEV_LOGIN_ENABLED`, refused in
  production) that creates the same server-side session.

## Consequences

- No tokens in `localStorage`, no bearer tokens in the SPA; XSS cannot exfiltrate IdP
  tokens, and revocation is immediate (delete the row).
- Every public host needs its callback and post-logout URIs registered at the IdP.
- One extra DB read per request for the session (cached per request); fine at our scale.
