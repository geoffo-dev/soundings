"""Phase 10's bid notifications (contract-phase10 section 11): "Asked to assess bids"
(``assessor_assigned``), "Bid assessment reminder" (``assessment_reminder``) and "Bid
assessments complete" (``assessments_complete``).

Bids are not in the feed (only ``bid_call_changed`` is, and it notifies nobody), so these
don't come from activity events: the bid services queue them (:func:`queue_assessors_added`
from ``set_bid_assessors``, :func:`queue_completion_check` after a submission, a rejection
and an assessor change), and a before-commit hook (:func:`fan_out`) writes them once, after
the request's last write, in its transaction, through the same
:class:`~app.notifications.fanout.NotificationWriter` (preferences, immediate emails, the
digest) and the same checks as every other type: not the actor, notifiable, ``idea.view``,
then the type's condition (:func:`app.notifications.access.applies` with the call's
:class:`~app.notifications.access.BidNotice`). The reminders are the hourly schedule's
(:func:`send_assessment_reminders`).

Payloads hold the call's id, a due date and counts: never bid score data, prices, bidder
names, document text or rejection reasons (role matrix section 3a rule 5).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.authz import eligible_assessor
from app.config import Settings
from app.db import before_commit, session_settings
from app.models.bid import Bid, BidAssessment, BidCall, BidSectionAssessor
from app.models.enums import (
    BidCallStatus,
    BidStatus,
    EvaluationStatus,
    IdeaStatus,
    NotificationType,
)
from app.models.idea import Idea
from app.models.project import Project
from app.notifications import access
from app.notifications.access import Recipient
from app.notifications.fanout import NotificationWriter

__all__ = [
    "fan_out",
    "queue_assessors_added",
    "queue_completion_check",
    "send_assessment_reminders",
]

_QUEUE: Final = "soundings.notify.bids"
_HOOK: Final = "bid_notifications"


@dataclass(frozen=True, slots=True)
class _Added:
    call_id: UUID
    actor_id: UUID | None
    user_ids: tuple[UUID, ...]
    request_id: UUID


@dataclass(frozen=True, slots=True)
class _Check:
    call_id: UUID
    actor_id: UUID | None


def queue_assessors_added(
    db: AsyncSession, call_id: UUID, actor_id: UUID | None, user_ids: Iterable[UUID]
) -> None:
    """ "Asked to assess bids" for the people one request added to sections of the call (one
    notification each, whatever the number of sections), when the unit of work commits."""
    wanted = tuple(dict.fromkeys(user_ids))
    if wanted:
        db.info.setdefault(_QUEUE, []).append(_Added(call_id, actor_id, wanted, uuid4()))
        before_commit(db, _HOOK, _hook)


def queue_completion_check(db: AsyncSession, call_id: UUID, actor_id: UUID | None) -> None:
    """Check, when the unit of work commits, whether nothing expected of the call is
    outstanding any more; if so, "Bid assessments complete" (once per call)."""
    db.info.setdefault(_QUEUE, []).append(_Check(call_id, actor_id))
    before_commit(db, _HOOK, _hook)


async def _hook(db: AsyncSession) -> None:
    await fan_out(db, settings=session_settings(db))


async def fan_out(
    db: AsyncSession, *, settings: Settings | None, now: datetime | None = None
) -> None:
    """Write what was queued in this unit of work (then forget it)."""
    items: list[_Added | _Check] = db.info.pop(_QUEUE, [])
    if not items:
        return
    await db.flush()
    writer = NotificationWriter(db, settings, now=now)
    checked: set[UUID] = set()
    for item in items:
        if isinstance(item, _Added):
            await _notify_added(writer, item)
        elif item.call_id not in checked:
            checked.add(item.call_id)
            await _check_complete(writer, item)


async def _call(db: AsyncSession, call_id: UUID) -> tuple[BidCall, Idea, Project] | None:
    row = (
        await db.execute(
            select(BidCall, Idea, Project)
            .join(Idea, Idea.id == BidCall.idea_id)
            .join(Project, Project.id == Idea.project_id)
            .where(BidCall.id == call_id)
            .execution_options(populate_existing=True)
        )
    ).first()
    return None if row is None else (row[0], row[1], row[2])


async def _applying(
    db: AsyncSession,
    type_: NotificationType,
    idea: Idea,
    project: Project,
    user_ids: Iterable[UUID],
    *,
    actor_id: UUID | None,
    payload: dict[str, Any],
    now: datetime,
) -> list[Recipient]:
    """Not the actor, notifiable, ``idea.view``, then the type's condition for each."""
    found = await access.recipients(
        db, idea, project, (user_id for user_id in user_ids if user_id != actor_id)
    )
    kept: list[Recipient] = []
    for recipient in found.values():
        notice = await access.bid_notice(db, type_, payload, recipient.id)
        if access.applies(type_, recipient, idea, payload=payload, now=now, bid=notice):
            kept.append(recipient)
    return kept


async def _notify_added(writer: NotificationWriter, item: _Added) -> None:
    db = writer.db
    found = await _call(db, item.call_id)
    if found is None:
        return
    call, idea, project = found
    due_at = call.assessment_due_at
    payload: dict[str, Any] = {
        "call_id": str(call.id),
        "due_at": due_at.isoformat() if due_at else None,
    }
    recipients = await _applying(
        db,
        NotificationType.ASSESSOR_ASSIGNED,
        idea,
        project,
        item.user_ids,
        actor_id=item.actor_id,
        payload=payload,
        now=writer.now,
    )
    await writer.notify(
        NotificationType.ASSESSOR_ASSIGNED,
        idea,
        recipients,
        actor_id=item.actor_id,
        dedupe_key=f"assessor_assigned:{call.id}:{item.request_id}",
        payload=payload,
    )


async def _check_complete(writer: NotificationWriter, item: _Check) -> None:
    """Contract section 8, "Progress": nothing expected is outstanding (and something was)
    while the call is being assessed: the idea's owner and the call's creator (lead default:
    not every admin) are told, once per call."""
    from app.bids.data import load_call_data

    db = writer.db
    found = await _call(db, item.call_id)
    if found is None:
        return
    call, idea, project = found
    if call.status is not BidCallStatus.ASSESSING:
        return
    data = await load_call_data(db, call)
    if not data.complete():
        return
    progress = data.call_progress()
    payload: dict[str, Any] = {
        "call_id": str(call.id),
        "bid_count": len(data.live_bids),
        "assessment_count": progress.submitted,
    }
    people = [user_id for user_id in (idea.owner_id, call.created_by_id) if user_id is not None]
    recipients = await _applying(
        db,
        NotificationType.ASSESSMENTS_COMPLETE,
        idea,
        project,
        people,
        actor_id=item.actor_id,
        payload=payload,
        now=writer.now,
    )
    await writer.notify(
        NotificationType.ASSESSMENTS_COMPLETE,
        idea,
        recipients,
        actor_id=item.actor_id,
        dedupe_key=f"assessments_complete:{call.id}",
        payload=payload,
    )


# --- Reminders (the hourly schedule) ---------------------------------------------------------
def _local(day: date, hour: int, settings: Settings) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=settings.tz)


async def send_assessment_reminders(db: AsyncSession, settings: Settings, now: datetime) -> int:
    """Phase 10 (contract section 11): the evaluation reminders' timing for calls being
    assessed: on local day ``d - n`` from the digest hour (``fire``), while ``now`` is before
    the assessment due date *d*, to each assessor who still owes an assessment (their
    sections x the bids that aren't rejected) and was assigned before that hour ("Asked to
    assess bids" gave the date); calls on closed or held ideas and in archived projects are
    skipped, and so are assignments that fail c28 now (review S10). One statement finds every
    (call, person) to remind; then per call the recipients' checks. One per call, person, due
    date and day (``dedupe_key``). Returns how many people were reminded."""
    if not settings.reminder_days:
        return 0
    today = now.astimezone(settings.tz).date()
    fire = _local(today, settings.digest_hour, settings)
    if fire > now:
        return 0
    offsets = {today + timedelta(days=n): n for n in settings.reminder_days}
    days = [
        (_local(day, 0, settings), _local(day + timedelta(days=1), 0, settings)) for day in offsets
    ]
    submitted = aliased(BidAssessment)
    due = BidCall.assessment_due_at
    on_a_day = [and_(due >= start, due < end) for start, end in days]
    rows = (
        await db.execute(
            select(BidSectionAssessor.call_id, BidSectionAssessor.user_id)
            .join(BidCall, BidCall.id == BidSectionAssessor.call_id)
            .join(Idea, Idea.id == BidCall.idea_id)
            .join(Project, Project.id == Idea.project_id)
            .join(Bid, and_(Bid.call_id == BidCall.id, Bid.status != BidStatus.REJECTED))
            .outerjoin(
                submitted,
                and_(
                    submitted.bid_id == Bid.id,
                    submitted.section_id == BidSectionAssessor.section_id,
                    submitted.assessor_id == BidSectionAssessor.user_id,
                    submitted.status == EvaluationStatus.SUBMITTED,
                ),
            )
            .where(
                BidCall.status == BidCallStatus.ASSESSING,
                due.is_not(None),
                due > now,
                or_(*on_a_day),
                Idea.status != IdeaStatus.CLOSED,
                Idea.held_for.is_(None),
                Project.archived_at.is_(None),
                BidSectionAssessor.assigned_at < fire,
                submitted.id.is_(None),
                eligible_assessor(BidSectionAssessor.user_id, Project.id),
            )
            .group_by(BidSectionAssessor.call_id, BidSectionAssessor.user_id)
            .having(func.count() > 0)
            .order_by(BidSectionAssessor.call_id, BidSectionAssessor.user_id)
        )
    ).all()
    people: dict[UUID, list[UUID]] = {}
    for call_id, user_id in rows:
        people.setdefault(call_id, []).append(user_id)
    writer = NotificationWriter(db, settings, now=now)
    reminded = 0
    for call_id, user_ids in people.items():
        found = await _call(db, call_id)
        if found is None:
            continue
        call, idea, project = found
        assert call.assessment_due_at is not None  # noqa: S101 - filtered above
        due_day = call.assessment_due_at.astimezone(settings.tz).date()
        days_before = offsets.get(due_day)
        if days_before is None:
            continue
        payload: dict[str, Any] = {
            "call_id": str(call.id),
            "due_at": call.assessment_due_at.isoformat(),
            "days_before": days_before,
        }
        recipients = await _applying(
            db,
            NotificationType.ASSESSMENT_REMINDER,
            idea,
            project,
            user_ids,
            actor_id=None,
            payload=payload,
            now=now,
        )
        reminded += len(
            await writer.notify(
                NotificationType.ASSESSMENT_REMINDER,
                idea,
                recipients,
                actor_id=None,
                dedupe_key=(f"assessment_reminder:{call.id}:{due_day.isoformat()}:{days_before}"),
                payload=payload,
            )
        )
    return reminded
