"""AI assistance through kagent (SPEC section 9; contract-phase6; ADR 0014).

* :mod:`app.ai.a2a`: the A2A client. Every request goes to the URL **built** from
  ``SOUNDINGS_KAGENT_URL`` and the agent's namespace and name (never a URL from a card
  or a request); no redirects, no proxies from the environment, capped bodies.
* :mod:`app.ai.agents`: Admin settings -> AI agents (the registry, the service account,
  its memberships and its one key), c10 for an agent and a kind.
* :mod:`app.ai.runs`: runs on an idea (request, list, cancel), the include-AI toggle and
  the run's permission flags. :mod:`app.ai.transitions`: the compare-and-set status
  changes, the progress events and what a run that ends without its evaluation undoes.
* :mod:`app.ai.runner`: the ``run_ai`` job's body (the A2A conversation, the deadline,
  cooperative cancel, worker shutdown); :mod:`app.ai.tasks`: the procrastinate tasks
  (``run_ai`` on the ``ai`` queue, the per-minute ``sweep_ai_runs``).
* :mod:`app.ai.scope`: c22, the run scope of an agent's key on ``/mcp``;
  :mod:`app.ai.results`: attaching an agent's evaluation, note or suggestion to its run;
  :mod:`app.ai.notes`: research notes.
* :mod:`app.ai.sse`: live progress (one poller per run per API process).
"""
