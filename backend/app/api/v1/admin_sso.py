"""Admin settings -> Single sign-on, read-only (rule ``platform.configure_sso``).

SSO is configured through Helm values / ``SOUNDINGS_OIDC_*``; there is no editing
screen. Business rules: docs/api/contract-phase2.md section 3.10.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.schemas.sso import SsoConfig

router = APIRouter(prefix="/admin/sso", tags=["admin"])


@router.get(
    "",
    operation_id="get_sso_config",
    summary="Effective SSO configuration",
    description=(
        "Platform admins (platform.configure_sso). The settings in effect with secrets "
        "masked, the redirect URIs to register at the IdP for each base URL, whether "
        "the provider's discovery document can be used, and the break-glass status."
    ),
    responses=problems(401, 403),
)
async def get_sso_config(principal: PrincipalDep) -> SsoConfig:
    raise NotImplementedProblem
