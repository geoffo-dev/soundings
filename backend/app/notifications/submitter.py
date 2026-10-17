"""Phase 11: "The submitter replied" (``submitter_replied``; contract-phase11 section 6).

The conversation with a public submitter is not in the feed, so this doesn't come from an
activity event: the reply service queues it (:func:`queue_reply`) and a before-commit hook
(:func:`fan_out`) writes it once, after the request's last write, in its transaction,
through the usual :class:`~app.notifications.fanout.NotificationWriter` (preferences,
immediate emails, the digest), like Phase 10's bid notifications.

Recipients: the idea's owner and everyone who has sent a team message in that conversation
(deduplicated), each passing ``idea.view`` and holding ``public.message_submitter`` now
(:func:`app.notifications.access.applies`, again when shown and sent). Never while the idea
is held for moderation (held ideas are in nobody's inbox). The payload names the reply only
(``message_id``): never its text, the submitter's name or address (untrusted public input,
a phishing channel into staff inboxes otherwise). At most one immediate email per recipient
and idea an hour (:data:`app.schemas.notifications.SUBMITTER_REPLIED_EMAIL_INTERVAL`, the
writer's coalescing): later replies in that hour reach the inbox only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import before_commit, session_settings
from app.models.enums import MessageDirection, NotificationType
from app.models.idea import Idea
from app.models.project import Project
from app.models.public import PublicSubmission, SubmissionMessage
from app.notifications import access
from app.notifications.fanout import NotificationWriter

__all__ = ["fan_out", "queue_reply", "recipient_ids"]

_QUEUE: Final = "soundings.notify.submitter"
_HOOK: Final = "submitter_notifications"
_TYPE: Final = NotificationType.SUBMITTER_REPLIED


def queue_reply(db: AsyncSession, message_id: UUID) -> None:
    """ "The submitter replied" for this reply, when the unit of work commits."""
    db.info.setdefault(_QUEUE, []).append(message_id)
    before_commit(db, _HOOK, _hook)


async def _hook(db: AsyncSession) -> None:
    await fan_out(db, settings=session_settings(db))


async def recipient_ids(db: AsyncSession, idea: Idea, submission_id: UUID) -> list[UUID]:
    """The idea's owner, then everyone who has written to the submitter (in the order they
    first wrote), deduplicated. The checks come after (:func:`access.recipients`,
    :func:`access.applies`)."""
    writers = await db.scalars(
        select(SubmissionMessage.author_id)
        .where(
            SubmissionMessage.submission_id == submission_id,
            SubmissionMessage.direction == MessageDirection.TEAM,
            SubmissionMessage.author_id.is_not(None),
        )
        .group_by(SubmissionMessage.author_id)
        .order_by(func.min(SubmissionMessage.created_at), SubmissionMessage.author_id)
    )
    people = [*([idea.owner_id] if idea.owner_id else []), *(w for w in writers if w)]
    return list(dict.fromkeys(people))


async def fan_out(
    db: AsyncSession, *, settings: Settings | None, now: datetime | None = None
) -> None:
    """Write what was queued in this unit of work (then forget it)."""
    queued: list[UUID] = db.info.pop(_QUEUE, [])
    if not queued:
        return
    await db.flush()
    writer = NotificationWriter(db, settings, now=now)
    for message_id in dict.fromkeys(queued):
        await _notify(writer, message_id)


async def _notify(writer: NotificationWriter, message_id: UUID) -> None:
    db = writer.db
    row = (
        await db.execute(
            select(SubmissionMessage, PublicSubmission, Idea, Project)
            .join(PublicSubmission, PublicSubmission.id == SubmissionMessage.submission_id)
            .join(Idea, Idea.id == PublicSubmission.idea_id)
            .join(Project, Project.id == Idea.project_id)
            .where(SubmissionMessage.id == message_id)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        return
    message, submission, idea, project = row
    if message.direction is not MessageDirection.SUBMITTER or idea.held_for is not None:
        return
    payload: dict[str, Any] = {"message_id": str(message.id)}
    found = await access.recipients(db, idea, project, await recipient_ids(db, idea, submission.id))
    kept = [
        recipient
        for recipient in found.values()
        if access.applies(_TYPE, recipient, idea, payload=payload, now=writer.now, reply=True)
    ]
    await writer.notify(
        _TYPE,
        idea,
        kept,
        actor_id=None,
        dedupe_key=f"submitter_replied:{message.id}",
        payload=payload,
    )
