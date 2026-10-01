"""Email: the transactional outbox, the worker's sender, templates and the admin view
(ADR 0003 as amended; docs/api/contract-phase3.md sections 3.9-3.12).

* :mod:`.outbox`: write ``outbound_email`` rows and defer their jobs in the caller's
  transaction; backoff, maximum age and retryability.
* :mod:`.delivery`: one attempt (claim, re-check, render, send, record) and the sweep.
* :mod:`.smtp`: aiosmtplib with the configured security, and error classification.
* :mod:`.content` / :mod:`.render` / :mod:`.message`: what an email says (from the
  current data), its HTML and text (Jinja2), and the MIME message with safe headers.
* :mod:`.tasks`: the procrastinate jobs the worker runs.
* :mod:`.admin`: Admin settings -> Email.

Never log addresses, subjects, bodies, tokens, credentials or the server's replies.
"""
