"""Fixtures for the moderation and Public form settings tests (contract-phase4
sections 3.5 and 3.6). They reuse the public submission fixtures: SMTP configured, the
``team`` project ("customer-innovation") with its public form on and moderated
(``form``), ``make_public_idea`` for a public idea written straight to the database,
and ``visitor`` / ``send`` for the real form."""

from __future__ import annotations

from tests.ideas.conftest import api, team  # noqa: F401 - fixtures
from tests.notifications.conftest import clock, jobs, runtime, transport  # noqa: F401
from tests.public.conftest import (  # noqa: F401 - fixtures
    API,
    PUBLIC,
    Api,
    AsUser,
    Team,
    anon,
    assert_problem,
    form,
    make_public_idea,
    ok,
    only,
    send,
    settings_overrides,
    submitted,
    visitor,
)

__all__ = [
    "API",
    "PUBLIC",
    "Api",
    "AsUser",
    "Team",
    "assert_problem",
    "make_public_idea",
    "ok",
    "only",
    "send",
    "submitted",
]
