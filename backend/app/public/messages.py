"""Phase 11: the conversation between the team and a public submitter (contract-phase11
sections 2-5, ADR 0019).

* **The team** (``public.message_submitter``: the idea's owner with member or admin,
  project and platform admins, in a session; never an AI agent or the break-glass account,
  c31) reads the conversation in the submission panel (:func:`list_messages`, newest first)
  and writes to the submitter (:func:`send`). Order of checks: 404 (the idea, then no
  public submission) -> 403 (the rule, c31) -> 409 ``project_archived``,
  ``submitter_erased``, ``public_submission_off``, ``conversation_full`` -> 429 (20 team
  messages to the submission in 24 hours, then 30 of the sender's an hour). Each message
  appears on the tracking page and is also emailed (``submission_message``) when the
  address is confirmed and email is set up; it is audited (``submission.message``, never
  the text). The idea's ``last_activity_at`` never moves: a conversation others can't see
  must not show in "recently updated".
* **The submitter** replies on their tracking page (:func:`add_reply`, behind the token):
  only after the team has written and at most 10 times after each team message (409
  ``awaiting_team``), 100 messages in all, 10 replies in 24 hours (429). Each reply queues
  "The submitter replied" for the team (:mod:`app.notifications.submitter`); replies are not
  audited (no actor: the row is the record).

Messages are plain text (``MessageBody``); a submitter's is untrusted public input. Nothing
here logs or audits a message's text, the submitter's name or address, or a token.

Writes lock project (``FOR KEY SHARE``) -> idea -> submission (``FOR UPDATE``), so the
per-submission limits and the conversation cap are exact; the per-person hourly count is
read in the same transaction but not serialised across submissions.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import String, func, select, tuple_
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.public_form import refuse
from app.authz import Resource, Rule, can, require
from app.config import Settings
from app.domain.principal import Principal
from app.errors import ProblemError
from app.models.enums import MessageDirection
from app.models.idea import Idea
from app.models.project import Project
from app.models.public import PublicSubmission, SubmissionMessage
from app.notifications import submitter as submitter_notifications
from app.notifications.inbox import decode_time_cursor
from app.pagination import PageParams, encode_cursor
from app.public.emails import queue_message_email
from app.public.submissions import load_submission
from app.schemas.public import (
    CONVERSATION_MAX_MESSAGES,
    MESSAGE_DAY,
    MESSAGE_HOUR,
    SUBMITTER_MESSAGES_PER_SUBMISSION_PER_DAY,
    SUBMITTER_MESSAGES_SINCE_TEAM_MESSAGE,
    TEAM_MESSAGES_PER_PERSON_PER_HOUR,
    TEAM_MESSAGES_PER_SUBMISSION_PER_DAY,
    MessageDelivery,
    ReplyBlocked,
    SendBlocked,
    SubmissionMessagePage,
    SubmissionMessagesSummary,
    TrackedMessage,
)
from app.schemas.public import SubmissionMessage as MessageOut
from app.services import audit
from app.services.ideas import LoadedIdea
from app.services.summaries import user_refs

__all__ = [
    "MESSAGE_ACTION",
    "Conversation",
    "add_reply",
    "conversation_from",
    "conversation_of",
    "conversations",
    "delivery",
    "list_messages",
    "may_message",
    "reply_blocked",
    "send",
    "send_blocked",
    "summary",
    "summary_for",
    "thread",
    "tracked_messages",
]

logger = logging.getLogger(__name__)

MESSAGE_ACTION: Final = "submission.message"

_ARCHIVED: Final = "This project is archived, so its conversations are read-only."
_ERASED: Final = "Their details were erased: there's no one to write to."
_PUBLIC_OFF: Final = (
    "Public submission is turned off for this Soundings, so they can't open their tracking "
    "page to read a message."
)
_FULL: Final = "This conversation has reached 100 messages."
_TEAM_DAILY: Final = "You've sent 20 messages to this person today. You can write again tomorrow."
_PERSON_HOURLY: Final = (
    "You've sent a lot of messages in the last hour. Try again in a few minutes."
)
_AWAITING_TEAM: Final = "You can reply once the team writes to you."
_REPLY_DAILY: Final = "You've replied 10 times today. You can reply again tomorrow."
_REPLY_REFUSED: Final = "public reply refused"


# --- What the panel shows --------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Conversation:
    """One conversation in figures (:func:`conversations`): its size, its latest message,
    and the team's messages in the last 24 hours (the per-submission limit)."""

    count: int = 0
    last_at: datetime | None = None
    last_direction: MessageDirection | None = None
    team_today: int = 0
    team_today_oldest: datetime | None = None


EMPTY: Final = Conversation()


def _figures(now: datetime) -> tuple[Any, ...]:
    """The aggregate columns of :class:`Conversation`, over ``submission_messages``."""
    message = SubmissionMessage
    team_today = (message.direction == MessageDirection.TEAM) & (
        message.created_at > now - MESSAGE_DAY
    )
    last_direction = func.array_agg(
        aggregate_order_by(message.direction, message.created_at.desc(), message.id.desc()),
        type_=ARRAY(String()),
    )[1]
    return (
        func.count().label("count"),
        func.max(message.created_at).label("last_at"),
        last_direction.label("last_direction"),
        func.count().filter(team_today).label("team_today"),
        func.min(message.created_at).filter(team_today).label("team_today_oldest"),
    )


def _conversation(
    count: Any, last_at: Any, direction: Any, today: Any, oldest: Any
) -> Conversation:
    return Conversation(
        count=int(count or 0),
        last_at=last_at,
        last_direction=MessageDirection(direction) if direction else None,
        team_today=int(today or 0),
        team_today_oldest=oldest,
    )


def conversation_of(submission_id: Any, *, now: datetime) -> Any:
    """A ``LATERAL`` subquery of one submission's :class:`Conversation` figures (always one
    row: an aggregate without ``GROUP BY``), to join into a page's own statement (the
    moderation queue: no statement of its own; ``ix_submission_messages_submission_id_
    created_at``). Read it back with :func:`conversation_from`."""
    return (
        select(*_figures(now))
        .where(SubmissionMessage.submission_id == submission_id)
        .lateral("conversation")
    )


def conversation_from(subquery: Any, row: Any) -> Conversation:
    """The :class:`Conversation` of a row that selected :func:`conversation_of`'s columns."""
    found = row._mapping
    columns = subquery.c
    return _conversation(
        found[columns.count],
        found[columns.last_at],
        found[columns.last_direction],
        found[columns.team_today],
        found[columns.team_today_oldest],
    )


async def conversations(
    db: AsyncSession, submission_ids: Iterable[UUID], *, now: datetime
) -> dict[UUID, Conversation]:
    """:class:`Conversation` per submission, in **one grouped statement** however many;
    submissions without a message are absent."""
    wanted = list(dict.fromkeys(submission_ids))
    if not wanted:
        return {}
    rows = await db.execute(
        select(SubmissionMessage.submission_id, *_figures(now))
        .where(SubmissionMessage.submission_id.in_(wanted))
        .group_by(SubmissionMessage.submission_id)
    )
    return {row[0]: _conversation(*row[1:]) for row in rows}


def may_message(principal: Principal, resource: Resource) -> bool:
    """``public.message_submitter`` (c31 included): who sees anything of the conversation."""
    return can(principal, Rule.PUBLIC_MESSAGE_SUBMITTER, resource)


def delivery(settings: Settings | None, submission: PublicSubmission) -> MessageDelivery:
    """Where a team message sent now reaches the submitter: also by email when the
    address is confirmed and email is set up (whatever ``wants_updates`` says)."""
    if (
        settings is not None
        and settings.smtp_configured
        and submission.erased_at is None
        and submission.email is not None
        and submission.email_verified_at is not None
    ):
        return MessageDelivery.EMAIL
    return MessageDelivery.TRACKING_PAGE


def send_blocked(
    settings: Settings | None,
    project: Project,
    submission: PublicSubmission,
    conversation: Conversation,
) -> SendBlocked | None:
    """Why the team can't send now, in the order checked (``SendBlocked``)."""
    if project.archived_at is not None:
        return SendBlocked.PROJECT_ARCHIVED
    if submission.erased_at is not None:
        return SendBlocked.SUBMITTER_ERASED
    if settings is not None and not settings.public_submission_enabled:
        return SendBlocked.PUBLIC_SUBMISSION_OFF
    if conversation.count >= CONVERSATION_MAX_MESSAGES:
        return SendBlocked.CONVERSATION_FULL
    if conversation.team_today >= TEAM_MESSAGES_PER_SUBMISSION_PER_DAY:
        return SendBlocked.DAILY_LIMIT
    return None


def summary(
    settings: Settings | None,
    project: Project,
    submission: PublicSubmission,
    conversation: Conversation,
) -> SubmissionMessagesSummary:
    return SubmissionMessagesSummary(
        count=conversation.count,
        last_message_at=conversation.last_at,
        last_direction=conversation.last_direction,
        delivery=delivery(settings, submission),
        blocked=send_blocked(settings, project, submission, conversation),
    )


async def summary_for(
    db: AsyncSession,
    settings: Settings | None,
    principal: Principal,
    loaded: LoadedIdea,
    submission: PublicSubmission,
    *,
    now: datetime,
) -> SubmissionMessagesSummary | None:
    """The panel's summary for a holder of the rule (one statement); ``None`` for everyone
    else, without touching the database."""
    if not may_message(principal, loaded.resource):
        return None
    found = await conversations(db, [submission.id], now=now)
    return summary(settings, loaded.project, submission, found.get(submission.id, EMPTY))


# --- The team's side ---------------------------------------------------------------------------
def _out(message: SubmissionMessage, authors: dict[UUID, object]) -> MessageOut:
    return MessageOut.model_validate(
        {
            "id": message.id,
            "direction": message.direction,
            "body": message.body,
            "created_at": message.created_at,
            "author": authors.get(message.author_id) if message.author_id else None,
            "emailed": message.emailed,
        }
    )


async def list_messages(
    db: AsyncSession, principal: Principal, loaded: LoadedIdea, page: PageParams
) -> SubmissionMessagePage:
    """``list_submission_messages``: newest first, ``(created_at, id)`` descending."""
    submission = await load_submission(db, loaded)
    require(principal, Rule.PUBLIC_MESSAGE_SUBMITTER, loaded.resource)
    statement = select(SubmissionMessage).where(SubmissionMessage.submission_id == submission.id)
    if page.cursor:
        statement = statement.where(
            tuple_(SubmissionMessage.created_at, SubmissionMessage.id)
            < decode_time_cursor(page.cursor)
        )
    rows = list(
        await db.scalars(
            statement.order_by(
                SubmissionMessage.created_at.desc(), SubmissionMessage.id.desc()
            ).limit(page.limit + 1)
        )
    )
    items = rows[: page.limit]
    next_cursor = None
    if len(rows) > page.limit and items:
        next_cursor = encode_cursor({"t": items[-1].created_at, "id": items[-1].id})
    authors: dict[UUID, object] = dict(await user_refs(db, (m.author_id for m in items)))
    return SubmissionMessagePage(items=[_out(m, authors) for m in items], next_cursor=next_cursor)


async def _person_hourly(
    db: AsyncSession, author_id: UUID, *, now: datetime
) -> tuple[int, datetime | None]:
    """The sender's team messages in the last hour, all submissions, and the oldest
    (``ix_submission_messages_author_id_created_at``)."""
    row = (
        await db.execute(
            select(func.count(), func.min(SubmissionMessage.created_at)).where(
                SubmissionMessage.author_id == author_id,
                SubmissionMessage.created_at > now - MESSAGE_HOUR,
            )
        )
    ).one()
    return int(row[0] or 0), row[1]


def _refuse_send(blocked: SendBlocked, conversation: Conversation, now: datetime) -> ProblemError:
    match blocked:
        case SendBlocked.PROJECT_ARCHIVED:
            return ProblemError(409, "project_archived", detail=_ARCHIVED)
        case SendBlocked.SUBMITTER_ERASED:
            return ProblemError(409, "submitter_erased", detail=_ERASED)
        case SendBlocked.PUBLIC_SUBMISSION_OFF:
            return ProblemError(409, "public_submission_off", detail=_PUBLIC_OFF)
        case SendBlocked.CONVERSATION_FULL:
            return ProblemError(409, "conversation_full", detail=_FULL)
        case SendBlocked.DAILY_LIMIT:
            oldest = conversation.team_today_oldest or now
            return refuse((oldest + MESSAGE_DAY - now).total_seconds(), _TEAM_DAILY)


async def send(
    db: AsyncSession,
    settings: Settings | None,
    principal: Principal,
    loaded: LoadedIdea,
    body: str,
    *,
    now: datetime,
) -> MessageOut:
    """``send_submission_message``: the caller loaded the idea ``for_update`` (project key
    share, then the idea); the submission is locked here. ``settings`` ``None`` (the demo
    seed): no email, the instance switch taken as on."""
    submission = await load_submission(db, loaded, for_update=True)
    require(principal, Rule.PUBLIC_MESSAGE_SUBMITTER, loaded.resource)
    conversation = (await conversations(db, [submission.id], now=now)).get(submission.id, EMPTY)
    blocked = send_blocked(settings, loaded.project, submission, conversation)
    if blocked is not None:
        raise _refuse_send(blocked, conversation, now)
    sent, oldest = await _person_hourly(db, principal.user_id, now=now)
    if sent >= TEAM_MESSAGES_PER_PERSON_PER_HOUR:
        raise refuse(((oldest or now) + MESSAGE_HOUR - now).total_seconds(), _PERSON_HOURLY)
    emailed = delivery(settings, submission) is MessageDelivery.EMAIL
    message = SubmissionMessage(
        id=uuid4(),
        submission_id=submission.id,
        direction=MessageDirection.TEAM,
        author_id=principal.user_id,
        body=body,
        emailed=emailed,
        created_at=now,
    )
    db.add(message)
    await db.flush()
    if emailed:
        assert settings is not None  # noqa: S101 - delivery needs settings
        await queue_message_email(db, settings, submission, message.id, now=now)
    await audit.record(
        db,
        MESSAGE_ACTION,
        actor=principal,
        target_type="idea",
        target_id=loaded.idea.id,
        project_id=loaded.idea.project_id,
        details={
            "rule": Rule.PUBLIC_MESSAGE_SUBMITTER.value,
            "message_id": str(message.id),
            "emailed": emailed,
        },
    )
    authors: dict[UUID, object] = dict(await user_refs(db, [principal.user_id]))
    return _out(message, authors)


# --- The submitter's side (the tracking page) --------------------------------------------------
async def thread(db: AsyncSession, submission_id: UUID) -> list[SubmissionMessage]:
    """The whole conversation, oldest first (at most 100 messages)."""
    return list(
        await db.scalars(
            select(SubmissionMessage)
            .where(SubmissionMessage.submission_id == submission_id)
            .order_by(SubmissionMessage.created_at, SubmissionMessage.id)
            .execution_options(populate_existing=True)
        )
    )


def _replies_since_team(rows: Sequence[SubmissionMessage]) -> int | None:
    """Replies after the team's latest message; ``None`` while the team hasn't written."""
    for since, message in enumerate(reversed(rows)):
        if message.direction is MessageDirection.TEAM:
            return since
    return None


def _replies_today(rows: Sequence[SubmissionMessage], now: datetime) -> list[SubmissionMessage]:
    return [
        message
        for message in rows
        if message.direction is MessageDirection.SUBMITTER
        and message.created_at > now - MESSAGE_DAY
    ]


def reply_blocked(
    project: Project, rows: Sequence[SubmissionMessage], now: datetime
) -> ReplyBlocked | None:
    """Why the submitter can't reply now, in the order checked (``ReplyBlocked``)."""
    if project.archived_at is not None:
        return ReplyBlocked.PROJECT_ARCHIVED
    since = _replies_since_team(rows)
    if since is None or since >= SUBMITTER_MESSAGES_SINCE_TEAM_MESSAGE:
        return ReplyBlocked.AWAITING_TEAM
    if len(rows) >= CONVERSATION_MAX_MESSAGES:
        return ReplyBlocked.CONVERSATION_FULL
    if len(_replies_today(rows, now)) >= SUBMITTER_MESSAGES_PER_SUBMISSION_PER_DAY:
        return ReplyBlocked.DAILY_LIMIT
    return None


def tracked_messages(rows: Sequence[SubmissionMessage]) -> list[TrackedMessage]:
    """The conversation as the submitter sees it: no author (public pages show no people)."""
    return [
        TrackedMessage(
            id=message.id,
            direction=message.direction,
            body=message.body,
            created_at=message.created_at,
        )
        for message in rows
    ]


async def add_reply(
    db: AsyncSession,
    found: tuple[PublicSubmission, Idea, Project],
    body: str,
    *,
    now: datetime,
) -> SubmissionMessage:
    """The submitter's reply (the caller found the submission by its token with the lock,
    and applied the per-address throttle): 409 ``project_archived``, ``awaiting_team``,
    ``conversation_full``, then 429 for 10 replies in 24 hours; then the reply and its
    notifications ("The submitter replied", written before commit)."""
    submission, idea, project = found
    rows = await thread(db, submission.id)
    blocked = reply_blocked(project, rows, now)
    if blocked is not None:
        logger.info(_REPLY_REFUSED, extra={"reason": blocked.value, "idea_id": str(idea.id)})
    match blocked:
        case ReplyBlocked.PROJECT_ARCHIVED:
            raise ProblemError(409, "project_archived", detail=_ARCHIVED)
        case ReplyBlocked.AWAITING_TEAM:
            raise ProblemError(409, "awaiting_team", detail=_AWAITING_TEAM)
        case ReplyBlocked.CONVERSATION_FULL:
            raise ProblemError(409, "conversation_full", detail=_FULL)
        case ReplyBlocked.DAILY_LIMIT:
            oldest = _replies_today(rows, now)[0].created_at
            raise refuse((oldest + MESSAGE_DAY - now).total_seconds(), _REPLY_DAILY)
        case None:
            pass
    message = SubmissionMessage(
        id=uuid4(),
        submission_id=submission.id,
        direction=MessageDirection.SUBMITTER,
        author_id=None,
        body=body,
        emailed=False,
        created_at=now,
    )
    db.add(message)
    await db.flush()
    submitter_notifications.queue_reply(db, message.id)
    return message
