"""Personal API keys (SPEC section 8; contract-phase5 sections 3.1-3.3, role matrix
section 5).

* :mod:`app.api_keys.tokens`: the key format, generation, hashing, constant-time compare.
* :mod:`app.api_keys.state`: a key's listed state and why authentication refuses it.
* :mod:`app.api_keys.verify`: checking a presented key (one indexed lookup) and the
  throttled ``last_used_at`` update in its own transaction.
* :mod:`app.api_keys.service`: create, list and revoke (yours and, for platform admins,
  everyone's), and revoking a deactivated user's keys.

The principal source that reads ``Authorization: Bearer`` is
:class:`app.auth.sources.ApiKeySource`; the bearer header, refusals and throttles
shared with the ``/mcp`` guard (:mod:`app.mcp.guard`) are in :mod:`app.auth.key_auth`.
Nothing is imported here, so :mod:`app.auth.sources` can use
:mod:`app.api_keys.verify` without a cycle.
"""
