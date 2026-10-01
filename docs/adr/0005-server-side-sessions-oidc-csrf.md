# ADR 0005: Server-side sessions, OIDC code flow with PKCE, CSRF double-submit token

- Status: Accepted · Date: 2026-09-30 · Amended 2026-10-01 (Phase 2, below)

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

## Amendment: Phase 2 as built (2026-10-01)

What changed from the decision above when single sign-on shipped
([contract-phase2.md](../api/contract-phase2.md) sections 1 and 3):

- **No Authlib.** The OIDC client (`app/auth/oidc.py`) is httpx plus `joserfc`, which
  Authlib itself uses; Authlib's Starlette client wanted a signed session cookie for the
  flow state, which this design doesn't need. Discovery is cached for an hour (failures
  for 30 s); keys are refetched once for an unknown `kid`; only asymmetric algorithms
  are accepted; claims come from the validated ID token only (no userinfo call), checked
  for `iss`, `aud`/`azp`, `exp`/`iat` (60 s leeway), `nonce` and `sub`.
- **Login attempts table** (`oidc_login_attempts`): hashed `state`, nonce and PKCE
  verifier, 10 minutes, single use, at most 10,000 in progress, and `GET /auth/login`
  is throttled per client IP. The `soundings_oidc` cookie holds only `state`. No
  database transaction stays open while the IdP is called.
- **Cookie names:** whenever cookies are `Secure` (production, any https request) they
  are `__Host-soundings_session`, `__Host-soundings_csrf` and `__Host-soundings_oidc`,
  so a sibling subdomain can't plant one; plain names on http development. The SPA
  reads the `__Host-` CSRF cookie first. (Closes Phase 1 review item F10.)
- **Sign-out is split:** `POST /auth/logout` stays 204 for API clients;
  `POST /auth/logout/redirect` (a form post) ends the session and answers 303 to the
  IdP's end-session endpoint with `id_token_hint` (kept only up to 3,072 characters,
  otherwise `client_id`) and `post_logout_redirect_uri=<base URL>/login?signed_out=1`,
  or straight to that page when the IdP has no end-session endpoint. A cross-origin
  post ends nothing.
- **Sessions carry their sign-in method** (`sso`, `break_glass`, `dev_login`) and stop
  working once that method is unavailable (SSO unconfigured, break-glass switched off by
  SSO, dev login off). Break-glass sessions last at most 8 hours (1 hour idle).
- **Hosts:** each base URL signs in on itself; a sign-in started on another host is
  sent to the first base URL first.
