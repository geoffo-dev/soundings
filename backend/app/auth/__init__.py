"""Authentication: who is calling, and how they signed in (ADR 0005,
docs/api/contract-phase2.md section 3).

Sessions and cookies:

* :mod:`app.auth.tokens`: random tokens, their stored hashes, constant-time compare.
* :mod:`app.auth.cookies`: the session, CSRF and SSO-state cookies (``__Host-`` names
  when Secure).
* :mod:`app.auth.sources`: principal sources tried in order (the session cookie now;
  Phase 5 adds API keys) and the CSRF check for cookie-authenticated requests.
* :mod:`app.auth.sign_in`: the last step of every sign-in (session, audit, cookies).

Sign-in methods:

* :mod:`app.auth.oidc`: the OIDC relying party (discovery, JWKS, token request, ID
  token validation); the routes are in :mod:`app.api.v1.auth_sso`.
* :mod:`app.auth.login_matching`: which user an SSO sign-in is (or why not).
* :mod:`app.auth.group_mapping`: reading claims, the groups claim and what sync would
  do (shared with the admin "test mapping" box); :mod:`app.auth.group_sync` applies it.
* :mod:`app.auth.break_glass`: the local emergency admin.
* :mod:`app.auth.throttle`: per-client-IP throttles for the public sign-in endpoints.

Session storage lives in :mod:`app.services.sessions`; authorisation in
:mod:`app.authz`.
"""
