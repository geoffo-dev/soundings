"""Authentication: who is calling. Server-side sessions (ADR 0005) and the principal
sources that turn a request into a :class:`~app.domain.principal.Principal`.

* :mod:`app.auth.tokens`: random tokens, their stored hashes, constant-time compare.
* :mod:`app.auth.cookies`: the ``soundings_session`` / ``soundings_csrf`` cookies.
* :mod:`app.auth.sources`: principal sources tried in order (session cookie now;
  Phase 5 adds API keys) and the CSRF check for cookie-authenticated requests.

Session storage lives in :mod:`app.services.sessions`; authorisation in
:mod:`app.authz`.
"""
