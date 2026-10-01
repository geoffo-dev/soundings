"""Fixtures for the branding tests (contract-phase4 sections 3.10-3.11).

``team`` (tests/ideas/conftest.py) is "Customer Innovation" (``customer-innovation``)
with a project admin (``team.admin``), members, a viewer, an outsider and a platform
admin (``team.platform``). ``api(user)`` signs a user in.

* ``upload(api, data, kind=..., slug=None)``: post raw image bytes to the global (or a
  project's) upload route and return the response.
"""

from __future__ import annotations

import httpx

from tests.ideas.conftest import (  # noqa: F401 - fixtures
    API,
    Api,
    AsUser,
    Team,
    api,
    assert_problem,
    ok,
    team,
)
from tests.notifications.conftest import (  # noqa: F401 - fixtures
    clock,
    jobs,
    runtime,
    transport,
)

__all__ = ["API", "Api", "AsUser", "Team", "assert_problem", "ok", "upload"]


async def upload(
    client: Api,
    data: bytes,
    *,
    kind: str = "logo",
    slug: str | None = None,
    content_type: str = "image/png",
) -> httpx.Response:
    path = "/admin/branding/assets" if slug is None else f"/projects/{slug}/branding/assets"
    return await client.http.post(
        f"{API}{path}",
        params={"kind": kind},
        content=data,
        headers={"Content-Type": content_type},
    )
