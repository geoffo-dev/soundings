"""Public submission (SPEC section 10, contract-phase4 sections 3.5-3.9).

* :mod:`.forms`: the public form's availability (c8) and what it asks for.
* :mod:`.submit`: ``POST /public/projects/{slug}/submissions``, the checks in order
  (per-IP limit, email required, ALTCHA, per-project limit, honeypot) and the idea it
  creates (held for email confirmation or moderation as the project says).
* :mod:`.tracking`: the private tracking link (``public.track``, c9), status emails on
  or off, the confirmation email again, the submitter erasing their own details, and
  confirming the address.
* :mod:`.erasure`: erasing a submitter's details (admin, submitter, retention).
* :mod:`.emails`: the two submitter emails (Phase 3 outbox): queueing, the status
  fan-out hook and their content at send time.
* :mod:`.branding`: a project's effective branding for its public pages.
* :mod:`.retention`: the hourly cleanup's public-submission rules.

Anti-abuse (ALTCHA, throttles, JSON-only writes, the honeypot) and the submitter's
tokens live in :mod:`app.auth` (``altcha``, ``public_form``, ``submission_tokens``);
held-idea visibility (c12, c19, :func:`app.authz.listed_ideas`) in :mod:`app.authz`.
Nothing here logs or audits names, addresses, tokens, ALTCHA payloads or idea text.
"""
