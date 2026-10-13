"""My work's "Bids to assess" and its counts (contract-phase10 section 11).

The assessments a person **owes**: a section they assess (c28 now: an active person who
views the idea in their own right; never a guest researcher or an agent) x a bid that
isn't rejected, without their submitted assessment of it, in a call being assessed, on an
idea that isn't closed (and isn't held), in a project that isn't archived, inside an API
key's projects. Progress only: never scores, prices or bidders.

* :func:`bids_to_assess`: the first 50 calls (overdue first, then soonest due, no due date
  last, then by call) **and** both counts, in one statement (window aggregates over the
  groups the sort reads anyway).
* :func:`bid_assessment_counts`: the two counts alone, one aggregate statement (the
  sidebar's badge).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from sqlalchemy import ColumnElement, and_, false, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from app.authz import eligible_assessor
from app.domain.principal import Principal
from app.models.base import utcnow
from app.models.bid import Bid, BidAssessment, BidCall, BidCallSection, BidSectionAssessor
from app.models.enums import BidCallStatus, BidStatus, EvaluationStatus, IdeaStatus
from app.models.idea import Idea
from app.models.project import Project
from app.schemas.bid_refs import BidCallRef, BidProgress, BidSectionRef
from app.schemas.work import BIDS_TO_ASSESS_MAX, WorkBidAssessment
from app.services.refs import idea_ref

__all__ = ["bid_assessment_counts", "bids_to_assess"]

_IDEA_COLUMNS: Final = load_only(
    Idea.id,
    Idea.project_id,
    Idea.number,
    Idea.title,
    Idea.status,
    Idea.resolution,
    raiseload=True,
)
_PROJECT_COLUMNS: Final = load_only(
    Project.id, Project.slug, Project.key, Project.name, Project.status_labels, raiseload=True
)


def _where(principal: Principal) -> list[ColumnElement[bool]]:
    """The person's live assignments in calls being assessed (module docstring)."""
    if principal.user.is_service_account or not principal.has_scope("read"):
        return [false()]  # agents never assess (c28); a key needs read
    in_key = Project.id.in_(principal.project_ids) if principal.project_ids is not None else true()
    return [
        BidSectionAssessor.user_id == principal.user_id,
        BidCall.status == BidCallStatus.ASSESSING,
        Idea.status != IdeaStatus.CLOSED,
        Idea.held_for.is_(None),
        Project.archived_at.is_(None),
        in_key,
        eligible_assessor(BidSectionAssessor.user_id, Project.id),
    ]


def _joins(statement: Any, submitted: Any) -> Any:
    """Assignments x the call's bids that aren't rejected, with the person's submitted
    assessment of each (``submitted``, an alias of ``bid_assessments``; or none)."""
    return (
        statement.select_from(BidSectionAssessor)
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
    )


async def bid_assessment_counts(db: AsyncSession, principal: Principal) -> tuple[int, int]:
    """(bid assessments owed, of which overdue): one aggregate."""
    now = utcnow()
    submitted = aliased(BidAssessment)
    owed = submitted.id.is_(None)
    statement = _joins(
        select(
            func.count().filter(owed),
            func.count().filter(and_(owed, BidCall.assessment_due_at < now)),
        ),
        submitted,
    ).where(*_where(principal))
    due, overdue = (await db.execute(statement)).one()
    return int(due), int(overdue)


async def bids_to_assess(
    db: AsyncSession, principal: Principal
) -> tuple[list[WorkBidAssessment], tuple[int, int]]:
    """The first 50 calls where the person owes assessments, and (owed, overdue) over all."""
    now = utcnow()
    submitted = aliased(BidAssessment)
    owed = submitted.id.is_(None)
    owed_here = func.count().filter(owed)
    overdue_here = func.count().filter(and_(owed, BidCall.assessment_due_at < now))
    sections = func.jsonb_agg(
        func.distinct(
            func.jsonb_build_object(
                "id", BidCallSection.id, "title", BidCallSection.title, "p", BidCallSection.position
            ).cast(JSONB)
        )
    )
    statement = (
        _joins(
            select(
                BidCall,
                Idea,
                Project,
                func.count().label("total"),
                func.count(submitted.id).label("done"),
                sections.label("sections"),
                func.sum(owed_here).over().label("owed_total"),
                func.sum(overdue_here).over().label("overdue_total"),
            ),
            submitted,
        )
        .join(BidCallSection, BidCallSection.id == BidSectionAssessor.section_id)
        .where(*_where(principal))
        .group_by(BidCall.id, Idea.id, Project.id)
        .having(owed_here > 0)
        .options(_IDEA_COLUMNS, _PROJECT_COLUMNS)
        .order_by(BidCall.assessment_due_at.asc().nulls_last(), BidCall.id)
        .limit(BIDS_TO_ASSESS_MAX)
    )
    rows = (await db.execute(statement)).all()
    counts = (int(rows[0].owed_total), int(rows[0].overdue_total)) if rows else (0, 0)
    items = []
    for row in rows:
        call: BidCall = row[0]
        due_at: datetime | None = call.assessment_due_at
        mine = sorted(row.sections or [], key=lambda item: (item["p"], item["id"]))
        items.append(
            WorkBidAssessment(
                idea=idea_ref(row[1], row[2]),
                call=BidCallRef(id=call.id, title=call.title, status=call.status),
                sections=[BidSectionRef(id=s["id"], title=s["title"]) for s in mine],
                due_at=due_at,
                overdue=due_at is not None and due_at < now,
                progress=BidProgress(submitted=int(row.done), total=int(row.total)),
            )
        )
    return items, counts
