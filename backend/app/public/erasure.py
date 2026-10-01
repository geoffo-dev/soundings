"""Erasing a public submitter's details (UK GDPR; contract-phase4 section 3.9).

One function for the three ways it happens: an admin (``erase_submitter``,
``public.erase_submitter``), the submitter from their tracking page
(``erase_tracked_submission``, no actor, ``reason: "submitter"``) and the retention
cleanup (no actor, ``reason: "retention"``). It clears the name, address,
confirmation, opt-in, both tracking-token columns and the copy of what was sent, sets
``erased_at``, deletes **all** the idea's submitter emails (queued and sent: no address
lingers in the outbox) and audits ``submission.erase`` with ids only. The idea, its
content and history stay; the tracking link stops working at once.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule
from app.domain.principal import Principal
from app.models.enums import EmailType
from app.models.idea import Idea
from app.models.notification import OutboundEmail
from app.models.public import PublicSubmission
from app.services import audit

__all__ = ["ERASE_ACTION", "erase"]

ERASE_ACTION: Final = "submission.erase"

ErasedBy = Principal | Literal["submitter", "retention"]


async def erase(
    db: AsyncSession,
    submission: PublicSubmission,
    idea: Idea,
    *,
    by: ErasedBy,
    now: datetime,
) -> bool:
    """Erase ``submission``'s details (the caller holds the idea's lock). ``False``
    when they were already erased (nothing changes, nothing is audited)."""
    if submission.erased_at is not None:
        return False
    submission.name = None
    submission.email = None
    submission.email_verified_at = None
    submission.wants_updates = False
    submission.tracking_token_hash = None
    submission.tracking_token_sealed = None
    submission.submitted_title = None
    submission.submitted_summary = None
    submission.erased_at = now
    submission.erased_by_id = by.user_id if isinstance(by, Principal) else None
    await db.flush()
    await db.execute(
        delete(OutboundEmail)
        .where(
            OutboundEmail.idea_id == idea.id,
            OutboundEmail.type.in_(
                [EmailType.SUBMISSION_RECEIVED, EmailType.SUBMISSION_STATUS_CHANGED]
            ),
        )
        .execution_options(synchronize_session=False)
    )
    details: dict[str, str] = (
        {"rule": Rule.PUBLIC_ERASE_SUBMITTER.value} if isinstance(by, Principal) else {"reason": by}
    )
    await audit.record(
        db,
        ERASE_ACTION,
        actor=by if isinstance(by, Principal) else None,
        target_type="idea",
        target_id=idea.id,
        project_id=idea.project_id,
        details=details,
    )
    return True
