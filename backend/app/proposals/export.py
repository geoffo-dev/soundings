"""Proposal exports: gather the document, the per-user limit, the downloads
(docs/api/contract-phase4.md 3.4).

* **Who:** ``proposal.export`` (everyone who can view the idea); the aggregate line
  only with ``score.view_aggregate`` (never for a pending evaluator, role matrix 3).
* **Limit:** :data:`EXPORT_THROTTLE`, 10 exports a minute per user (Markdown and PDF
  together, in-process like the sign-in throttles) -> 429 ``too_many_attempts`` with
  ``Retry-After``. Refusals are logged with the user id only.
* **Branding** (PDF): the project's effective branding (override -> global ->
  default, :func:`app.services.branding.effective_branding`), its logo embedded from
  the database (:func:`app.services.branding.logo_image`).
* **Files:** ``<KEY>-proposal.md`` / ``.pdf``; the key is ASCII letters, digits and a
  hyphen (checked again here), so nothing can be injected through the filename.

Exports are reads: not audited (contract 3.14).
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.throttle import get_throttle
from app.authz import Rule, can, require
from app.config import Settings
from app.domain.labels import status_label
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.user import User
from app.proposals.document import (
    LOGO_TYPES,
    ExportBranding,
    ExportDocument,
    ExportSection,
    build_markdown,
)
from app.proposals.pdf import RETRY_AFTER, ExportBusy, RenderFailed, render_pdf
from app.proposals.service import TEMPLATE, require_proposal, section_rows
from app.services import branding
from app.services.ideas import LoadedIdea
from app.services.refs import idea_key

__all__ = [
    "EXPORT_THROTTLE",
    "export_document",
    "markdown_response",
    "pdf_response",
]

logger = logging.getLogger(__name__)

EXPORT_THROTTLE: Final = ("proposal_export", 10, 60.0)
"""Exports (Markdown and PDF together) per user per minute."""
_SAFE_KEY: Final = re.compile(r"[A-Za-z][A-Za-z0-9]{0,9}-[0-9]{1,9}")


def _check_limit(app: Any, principal: Principal) -> None:
    throttle = get_throttle(app, EXPORT_THROTTLE)
    key = str(principal.user_id)
    retry_after = throttle.retry_after(key)
    if retry_after is not None:
        logger.info("proposal export refused", extra={"reason": "rate_limited", "user_id": key})
        raise ProblemError(
            429,
            "too_many_attempts",
            detail="You've exported several times in a minute. Try again shortly.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )
    throttle.hit(key)


async def _branding(db: AsyncSession, project_id: UUID) -> ExportBranding:
    effective = await branding.effective_branding(db, project_id)
    image = await branding.logo_image(db, project_id)
    logo_type, logo = image if image is not None and image[0] in LOGO_TYPES else (None, None)
    return ExportBranding(
        app_name=effective.app_name,
        primary_color=effective.primary_color,
        accent_color=effective.accent_color,
        font=str(effective.font),
        logo_type=logo_type,
        logo=logo,
    )


async def export_document(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedIdea,
    settings: Settings,
    app: Any,
    *,
    now: datetime,
) -> ExportDocument:
    """The export's content as ``principal`` may see it; 404 without a proposal, 429
    beyond the limit (counted once the export is allowed)."""
    idea, project = loaded.idea, loaded.project
    proposal = await require_proposal(db, loaded)
    require(principal, Rule.PROPOSAL_EXPORT, loaded.resource)
    _check_limit(app, principal)
    rows = await section_rows(db, proposal.id)
    owner = (
        await db.scalar(select(User.display_name).where(User.id == idea.owner_id))
        if idea.owner_id
        else None
    )
    score_visible = can(principal, Rule.SCORE_VIEW_AGGREGATE, loaded.resource)
    return ExportDocument(
        title=idea.title,
        idea_key=idea_key(idea, project),
        project_name=project.name,
        status_label=status_label(project.status_labels, idea.status, idea.resolution),
        owner_name=owner,
        exported_at=now.astimezone(settings.tz),
        exported_by=principal.user.display_name,
        sections=tuple(
            ExportSection(row.key.value, TEMPLATE[row.key].title, row.body_md) for row in rows
        ),
        branding=await _branding(db, project.id),
        score=idea.aggregate_score if score_visible else None,
        score_count=idea.aggregate_count if score_visible else 0,
    )


def _filename(key: str, extension: str) -> str:
    stem = f"{key}-proposal" if _SAFE_KEY.fullmatch(key) else "proposal"
    return f"{stem}.{extension}"


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def markdown_response(document: ExportDocument) -> Response:
    # Parsing (heading demotion) is CPU work: off the event loop.
    text = await asyncio.to_thread(build_markdown, document)
    return _download(
        text.encode("utf-8"),
        "text/markdown; charset=utf-8",
        _filename(document.idea_key, "md"),
    )


async def pdf_response(state: Any, document: ExportDocument, idea_id: UUID) -> Response:
    try:
        pdf = await render_pdf(state, document)
    except ExportBusy as busy:
        logger.warning(
            "proposal export busy", extra={"reason": busy.reason, "idea_id": str(idea_id)}
        )
        raise ProblemError(
            503,
            "export_busy",
            detail="Exports are busy right now. Try again in a few seconds.",
            headers={"Retry-After": str(RETRY_AFTER)},
        ) from None
    except RenderFailed as failed:
        logger.error(
            "proposal export failed", extra={"error": str(failed), "idea_id": str(idea_id)}
        )
        raise ProblemError(
            500,
            "internal_error",
            detail="The PDF couldn't be made. Quote the request id when reporting it.",
        ) from None
    return _download(pdf, "application/pdf", _filename(document.idea_key, "pdf"))
