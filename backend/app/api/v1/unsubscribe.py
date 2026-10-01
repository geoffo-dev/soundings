"""Unsubscribe links in emails: no sign-in needed (rule ``self.unsubscribe``, c14).

Every notification email links to the SPA page ``/unsubscribe?token=...`` and carries
``List-Unsubscribe: <{base}/api/v1/unsubscribe?token=...>`` with
``List-Unsubscribe-Post: List-Unsubscribe=One-Click`` (RFC 8058), so mail clients can
unsubscribe with one POST. A GET never changes anything (link scanners prefetch); a
browser that opens the header's URL (``Accept: text/html``, mail clients without
one-click support) is redirected (303) to the SPA page. Business rules:
docs/api/contract-phase3.md section 3.5.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.api.v1.responses import problems, redirect
from app.config import Settings
from app.db import SessionDep
from app.notifications import unsubscribe
from app.schemas.notifications import UnsubscribeInfo

router = APIRouter(prefix="/unsubscribe", tags=["notifications"])

UnsubscribeToken = Annotated[
    str,
    Query(
        min_length=16,
        max_length=512,
        pattern=r"^[A-Za-z0-9_.-]+$",
        description="The signed token from the email's link.",
    ),
]


@router.get(
    "",
    operation_id="get_unsubscribe",
    response_model=UnsubscribeInfo,
    summary="What an unsubscribe link turns off",
    description=(
        "Public (self.unsubscribe, c14): the page's data. Changes nothing. 404 for an "
        "invalid token or a user who is no longer active. A browser navigation (Accept "
        "lists text/html) is answered with 303 to the SPA page /unsubscribe?token=..., "
        "without checking the token."
    ),
    responses={
        **problems(404),
        **redirect(303, "Opened in a browser (Accept lists text/html): to /unsubscribe?token=..."),
    },
)
async def get_unsubscribe(
    request: Request, session: SessionDep, token: UnsubscribeToken
) -> UnsubscribeInfo | Response:
    settings: Settings = request.app.state.settings
    if _wants_html(request):
        # A mail client without one-click support opened List-Unsubscribe's URL: show
        # the page (which checks the token through this route's JSON).
        page = f"{settings.public_base_url.rstrip('/')}/unsubscribe?{urlencode({'token': token})}"
        return RedirectResponse(page, status_code=303)
    return await unsubscribe.unsubscribe_info(session, settings, token)


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return any(part.split(";", 1)[0].strip().lower() == "text/html" for part in accept.split(","))


@router.post(
    "",
    operation_id="confirm_unsubscribe",
    summary="Unsubscribe",
    description=(
        "Public (self.unsubscribe, c14), idempotent: turns off email for the link's "
        "scope, or for every type with all=true. Also the RFC 8058 one-click target: "
        "the mail client's form body (List-Unsubscribe=One-Click) is accepted and "
        "ignored; no CSRF token or session is needed (the token is the authority). 404 "
        "for an invalid token or a user who is no longer active."
    ),
    responses=problems(404),
)
async def confirm_unsubscribe(
    request: Request,
    session: SessionDep,
    token: UnsubscribeToken,
    all_types: Annotated[
        bool, Query(alias="all", description="Turn off every email notification type.")
    ] = False,
) -> UnsubscribeInfo:
    settings: Settings = request.app.state.settings
    return await unsubscribe.confirm(session, settings, token, all_types=all_types)
