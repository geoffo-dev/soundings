"""REST API v1, mounted at ``/api/v1``.

To add a feature area:

1. Create ``app/api/v1/<area>.py``::

       router = APIRouter(prefix="/<area>", tags=["<area>"])

       @router.get("/{item_id}", operation_id="get_item", responses=problems(404))
       async def get_item(
           item_id: UUID, principal: PrincipalDep, session: SessionDep
       ) -> Item: ...

2. Register it below with ``api_router.include_router(<area>.router)``.

Conventions: signed-in routes take ``PrincipalDep`` (``app/api/v1/principal.py``),
never the bare user; schemas from ``app/schemas`` (lead-owned contract); errors via
``app.errors`` (problem+json); growing lists return ``Page[T]`` subclasses with
cursor pagination (``app.pagination``); every route has an explicit, stable
snake_case ``operation_id`` equal to the function name (the TypeScript client and
MSW mocks depend on it). The contracts are summarised in docs/api/contract-phase1.md
to contract-phase5.md (the MCP server at ``/mcp`` is not part of this router).
"""

from fastapi import APIRouter

from app.api.v1 import (
    activity,
    admin_api_keys,
    admin_audit,
    admin_email,
    admin_groups,
    admin_sso,
    admin_users,
    api_keys,
    auth,
    auth_sso,
    branding,
    evaluations,
    groups,
    ideas,
    notifications,
    project_groups,
    projects,
    proposal_suggestions,
    proposals,
    public,
    search,
    submissions,
    unsubscribe,
    users,
    work,
)

api_router = APIRouter(prefix="/api/v1")

# --- Feature routers (keep alphabetical) ---------------------------------------------
api_router.include_router(activity.router)
api_router.include_router(admin_api_keys.router)
api_router.include_router(admin_audit.router)
api_router.include_router(admin_email.router)
api_router.include_router(admin_groups.router)
api_router.include_router(admin_sso.router)
api_router.include_router(admin_users.router)
api_router.include_router(api_keys.router)
api_router.include_router(auth.router)
api_router.include_router(auth_sso.router)
api_router.include_router(branding.router)
api_router.include_router(evaluations.router)
api_router.include_router(groups.router)
api_router.include_router(ideas.router)
api_router.include_router(notifications.router)
api_router.include_router(project_groups.router)
api_router.include_router(projects.router)
api_router.include_router(proposal_suggestions.router)
api_router.include_router(proposals.router)
api_router.include_router(public.router)
api_router.include_router(search.router)
api_router.include_router(submissions.router)
api_router.include_router(unsubscribe.router)
api_router.include_router(users.router)
api_router.include_router(work.router)
