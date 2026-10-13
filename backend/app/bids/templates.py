"""Bid evaluation templates (contract-phase10 section 4): the project's default (one JSON
document in ``bid_templates``) and each call's own relational copy.

* :func:`get_project_template` / :func:`replace_project_template`: Project settings ->
  Bids (``project.view`` / ``project.edit_bid_template``, session only, allowed in an
  archived project, last write wins, audited ``project.bid_template_replace``). Titles and
  must-have texts are unique by Postgres ``lower()`` too (``require_unique_lower``), since a
  call's copy has unique ``lower(...)`` indexes.
* :func:`insert_default_template`: ``create_project`` writes the built-in default
  (``DEFAULT_BID_TEMPLATE``; migration 0016 wrote it for existing projects).
* :func:`copy_into_call`: a new call copies the project's template into rows with ids.
* :func:`replace_call_template`: a call's copy, complete (items keep their ids, new ones
  get one, items left out go), until the first person's assessment is submitted (409
  ``bid_call_template_locked``); any change deletes the call's AI assessments and cancels
  its active assess runs (their questions changed).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule
from app.bids import runs
from app.bids.data import CallData
from app.bids.problems import unprocessable
from app.domain.principal import Principal
from app.models.base import utcnow
from app.models.bid import (
    BidAiAssessment,
    BidCall,
    BidCallMustHave,
    BidCallQuestion,
    BidCallSection,
    BidDocument,
    BidMustHaveResult,
)
from app.models.bid import BidTemplate as TemplateRow
from app.models.enums import BidQuestionType, MustHaveKind, MustHaveResult
from app.models.project import Project
from app.models.user import User
from app.schemas.bids import (
    DEFAULT_BID_TEMPLATE,
    BidCallTemplateIn,
    BidTemplate,
    BidTemplateIn,
    BidTemplateMustHave,
    BidTemplateQuestion,
    BidTemplateSection,
)
from app.schemas.bids import (
    BidCallMustHave as BidCallMustHaveOut,
)
from app.schemas.bids import (
    BidCallQuestion as BidCallQuestionOut,
)
from app.schemas.users import UserRef
from app.services import audit
from app.services.sql import require_unique_lower

__all__ = [
    "copy_into_call",
    "get_project_template",
    "insert_default_template",
    "must_have_out",
    "question_out",
    "replace_call_template",
    "replace_project_template",
]


# --- The project's default --------------------------------------------------------------------
def insert_default_template(project_id: UUID) -> TemplateRow:
    """The built-in default for a new project (``create_project``)."""
    return TemplateRow(project_id=project_id, template=DEFAULT_BID_TEMPLATE.model_dump(mode="json"))


def _parse(template: dict[str, Any] | None) -> BidTemplateIn:
    """A stored template (validated when written); a missing or unreadable one reads as the
    built-in default (a project made by an older release during a rollback)."""
    if template is None:
        return DEFAULT_BID_TEMPLATE
    try:
        return BidTemplateIn.model_validate(template)
    except ValidationError:
        return DEFAULT_BID_TEMPLATE


async def project_template(db: AsyncSession, project_id: UUID) -> BidTemplateIn:
    row = await db.get(TemplateRow, project_id)
    return _parse(row.template if row is not None else None)


async def get_project_template(
    db: AsyncSession, project: Project, *, can_edit: bool
) -> BidTemplate:
    row = await db.get(TemplateRow, project.id, populate_existing=True)
    template = _parse(row.template if row is not None else None)
    updated_by = None
    if row is not None and row.updated_by_id is not None:
        user = await db.get(User, row.updated_by_id)
        updated_by = UserRef.model_validate(user) if user is not None else None
    return BidTemplate(
        scale=list(template.scale),
        sections=[
            BidTemplateSection(
                title=section.title,
                guidance=section.guidance,
                weight=section.weight,
                questions=[
                    BidTemplateQuestion(
                        text=question.text,
                        guidance=question.guidance,
                        type=question.type,
                        weight=question.weight or 0,
                    )
                    for question in section.questions
                ],
            )
            for section in template.sections
        ],
        must_haves=[
            BidTemplateMustHave(text=m.text, kind=m.kind, pricing=m.pricing)
            for m in template.must_haves
        ],
        updated_at=row.updated_at if row is not None else None,
        updated_by=updated_by,
        can_edit=can_edit,
    )


async def _unique_lower(
    db: AsyncSession, section_titles: Sequence[str], must_have_texts: Sequence[str]
) -> None:
    """422 when two titles (or must-have texts) collide under Postgres ``lower()``, which
    the call copy's unique indexes use (Python's ``casefold`` in the schema differs)."""
    await require_unique_lower(
        db, section_titles, field="sections", message="section titles must be unique"
    )
    await require_unique_lower(
        db, must_have_texts, field="must_haves", message="must-haves must be unique"
    )


async def replace_project_template(
    db: AsyncSession, principal: Principal, project: Project, body: BidTemplateIn
) -> None:
    """``project.edit_bid_template`` (checked by the caller, who holds the project row
    ``FOR UPDATE``): the complete template; existing calls keep their own copy."""
    await _unique_lower(db, [s.title for s in body.sections], [m.text for m in body.must_haves])
    row = await db.get(TemplateRow, project.id)
    value = body.model_dump(mode="json")
    if row is None:
        db.add(TemplateRow(project_id=project.id, template=value, updated_by_id=principal.user_id))
    else:
        row.template = value
        row.updated_by_id = principal.user_id
        row.updated_at = utcnow()
    await audit.record(
        db,
        "project.bid_template_replace",
        actor=principal,
        target_type="project",
        target_id=project.id,
        project_id=project.id,
        details={
            "rule": Rule.PROJECT_EDIT_BID_TEMPLATE,
            "sections": len(body.sections),
            "questions": sum(len(s.questions) for s in body.sections),
            "must_haves": len(body.must_haves),
        },
    )
    await db.flush()


# --- A call's copy ------------------------------------------------------------------------------
async def copy_into_call(db: AsyncSession, call: BidCall, template: BidTemplateIn) -> None:
    """The call's own rows from ``template`` (its scale is on the call). Sections are
    written before their questions (no ORM relationships order the inserts)."""
    call.scale = list(template.scale)
    sections = [
        BidCallSection(
            id=uuid4(),
            call_id=call.id,
            position=position,
            title=section.title,
            guidance=section.guidance,
            weight=section.weight,
        )
        for position, section in enumerate(template.sections)
    ]
    db.add_all(sections)
    db.add_all(
        BidCallMustHave(
            id=uuid4(),
            call_id=call.id,
            position=position,
            text=must_have.text,
            kind=must_have.kind,
            pricing=must_have.pricing,
        )
        for position, must_have in enumerate(template.must_haves)
    )
    await db.flush()
    db.add_all(
        BidCallQuestion(
            id=uuid4(),
            call_id=call.id,
            section_id=row.id,
            position=index,
            text=question.text,
            guidance=question.guidance,
            type=question.type,
            weight=question.weight or 0,
        )
        for row, section in zip(sections, template.sections, strict=True)
        for index, question in enumerate(section.questions)
    )
    await db.flush()


def question_out(question: BidCallQuestion) -> BidCallQuestionOut:
    return BidCallQuestionOut(
        id=question.id,
        section_id=question.section_id,
        position=question.position,
        text=question.text,
        guidance=question.guidance,
        type=question.type,
        weight=question.weight,
    )


def must_have_out(must_have: BidCallMustHave) -> BidCallMustHaveOut:
    return BidCallMustHaveOut(
        id=must_have.id,
        position=must_have.position,
        text=must_have.text,
        kind=must_have.kind,
        pricing=must_have.pricing,
    )


def _canonical(data: CallData) -> tuple[Any, ...]:
    """The copy as comparable values (to tell a real change from a re-save)."""
    return (
        tuple(data.call.scale),
        tuple(
            (
                s.id,
                s.title,
                s.guidance,
                s.weight,
                tuple(
                    (q.id, q.text, q.guidance, q.type, q.weight)
                    for q in data.questions.get(s.id, [])
                ),
            )
            for s in data.sections
        ),
        tuple((m.id, m.text, m.kind, m.pricing) for m in data.must_haves),
    )


def _requested(body: BidCallTemplateIn) -> tuple[Any, ...]:
    """The request in :func:`_canonical`'s shape (new items get placeholders)."""
    return (
        tuple(body.scale),
        tuple(
            (
                s.id if s.id is not None else f"new-section-{i}",
                s.title,
                s.guidance,
                s.weight,
                tuple(
                    (
                        q.id if q.id is not None else f"new-question-{i}-{j}",
                        q.text,
                        q.guidance,
                        q.type,
                        q.weight or 0,
                    )
                    for j, q in enumerate(s.questions)
                ),
            )
            for i, s in enumerate(body.sections)
        ),
        tuple(
            (m.id if m.id is not None else f"new-must-have-{i}", m.text, m.kind, m.pricing)
            for i, m in enumerate(body.must_haves)
        ),
    )


def _check_ids(data: CallData, body: BidCallTemplateIn) -> None:
    """422 ``unknown_template_item``: an id that isn't one of this call's items (of that
    kind). Ids used twice are refused by the schema."""
    sections = {s.id for s in data.sections}
    questions = {q.id for items in data.questions.values() for q in items}
    must_haves = {m.id for m in data.must_haves}
    for i, section in enumerate(body.sections):
        if section.id is not None and section.id not in sections:
            raise unprocessable("unknown_template_item", loc=["body", "sections", i, "id"])
        for j, question in enumerate(section.questions):
            if question.id is not None and question.id not in questions:
                raise unprocessable(
                    "unknown_template_item", loc=["body", "sections", i, "questions", j, "id"]
                )
    for i, must_have in enumerate(body.must_haves):
        if must_have.id is not None and must_have.id not in must_haves:
            raise unprocessable("unknown_template_item", loc=["body", "must_haves", i, "id"])


async def validate_call_template(db: AsyncSession, data: CallData, body: BidCallTemplateIn) -> bool:
    """The 422s of a call template replacement (ids, ``lower()`` uniqueness); whether it
    changes anything at all."""
    _check_ids(data, body)
    await _unique_lower(db, [s.title for s in body.sections], [m.text for m in body.must_haves])
    return _canonical(data) != _requested(body)


async def replace_call_template(
    db: AsyncSession,
    principal: Principal,
    project_id: UUID,
    data: CallData,
    body: BidCallTemplateIn,
) -> None:
    """Make the call's copy exactly ``body`` (validated by :func:`validate_call_template`;
    the caller holds the call ``FOR UPDATE`` and has checked the lock). Items left out are
    deleted (sections with their assignments and drafts; must-haves with their results,
    their documents unlinked first); new must-haves get a result for every bid; changed
    must-haves' results follow their kind; every bid's status is recomputed; the call's AI
    assessments go and its active assess runs are cancelled."""
    call = data.call
    keep_sections = {s.id for s in body.sections if s.id is not None}
    keep_questions = {q.id for s in body.sections for q in s.questions if q.id is not None}
    keep_must_haves = {m.id for m in body.must_haves if m.id is not None}
    old_must_haves = {m.id: m for m in data.must_haves}

    # Gone first (so their titles, texts and the price question free their unique slots).
    gone_musts = [m for m in data.must_haves if m.id not in keep_must_haves]
    if gone_musts:
        ids = [m.id for m in gone_musts]
        await db.execute(
            update(BidDocument)
            .where(BidDocument.call_id == call.id, BidDocument.must_have_id.in_(ids))
            .values(must_have_id=None)
            .execution_options(synchronize_session=False)
        )
        await db.execute(delete(BidCallMustHave).where(BidCallMustHave.id.in_(ids)))
    gone_questions = [
        q.id for items in data.questions.values() for q in items if q.id not in keep_questions
    ]
    if gone_questions:
        await db.execute(delete(BidCallQuestion).where(BidCallQuestion.id.in_(gone_questions)))
    gone_sections = [s.id for s in data.sections if s.id not in keep_sections]
    # Every section (gone ones are deleted last: a kept question may move out of one) and
    # kept must-have steps out of the unique lower(...) slots while they move, and the
    # price question becomes a score question until it is written again.
    if data.sections:
        await db.execute(
            update(BidCallSection)
            .where(BidCallSection.call_id == call.id)
            .values(title=func.cast(BidCallSection.id, BidCallSection.title.type))
            .execution_options(synchronize_session=False)
        )
    if keep_must_haves:
        await db.execute(
            update(BidCallMustHave)
            .where(BidCallMustHave.id.in_(keep_must_haves))
            .values(text=func.cast(BidCallMustHave.id, BidCallMustHave.text.type))
            .execution_options(synchronize_session=False)
        )
    if keep_questions:
        await db.execute(
            update(BidCallQuestion)
            .where(
                BidCallQuestion.id.in_(keep_questions),
                BidCallQuestion.type == BidQuestionType.PRICE,
            )
            .values(type=BidQuestionType.SCORE)
            .execution_options(synchronize_session=False)
        )
    await db.flush()

    call.scale = list(body.scale)
    for position, section in enumerate(body.sections):
        section_id = section.id or uuid4()
        values = {
            "position": position,
            "title": section.title,
            "guidance": section.guidance,
            "weight": section.weight,
        }
        if section.id is None:
            db.add(BidCallSection(id=section_id, call_id=call.id, **values))
            await db.flush()
        else:
            await db.execute(
                update(BidCallSection)
                .where(BidCallSection.id == section_id)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        for index, question in enumerate(section.questions):
            values = {
                "section_id": section_id,
                "position": index,
                "text": question.text,
                "guidance": question.guidance,
                "type": question.type,
                "weight": question.weight or 0,
            }
            if question.id is None:
                db.add(BidCallQuestion(id=uuid4(), call_id=call.id, **values))
            else:
                await db.execute(
                    update(BidCallQuestion)
                    .where(BidCallQuestion.id == question.id)
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )
    await db.flush()
    if gone_sections:
        await db.execute(delete(BidCallSection).where(BidCallSection.id.in_(gone_sections)))

    bid_ids = [bid.id for bid in data.bids]
    for position, must_have in enumerate(body.must_haves):
        values = {
            "position": position,
            "text": must_have.text,
            "kind": must_have.kind,
            "pricing": must_have.pricing,
        }
        if must_have.id is None:
            row = BidCallMustHave(id=uuid4(), call_id=call.id, **values)
            db.add(row)
            await db.flush()
            for bid_id in bid_ids:
                db.add(
                    BidMustHaveResult(
                        bid_id=bid_id,
                        must_have_id=row.id,
                        call_id=call.id,
                        result=_initial(must_have.kind),
                    )
                )
            continue
        old = old_must_haves[must_have.id]
        await db.execute(
            update(BidCallMustHave)
            .where(BidCallMustHave.id == must_have.id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if old.kind is not must_have.kind:
            await _kind_changed(db, call, must_have.id, must_have.kind)
        elif must_have.pricing and not old.pricing:
            # Its files are pricing documents now (only bid.view_price; the AI never).
            await db.execute(
                update(BidDocument)
                .where(BidDocument.call_id == call.id, BidDocument.must_have_id == must_have.id)
                .values(pricing=True)
                .execution_options(synchronize_session=False)
            )
    await db.flush()

    from app.bids.service import refresh_statuses

    await refresh_statuses(db, call)
    if bid_ids:
        await db.execute(delete(BidAiAssessment).where(BidAiAssessment.bid_id.in_(bid_ids)))
    cancelled = await runs.cancel_assess_runs(db, principal, call)
    await audit.record(
        db,
        "bid_call.template_replace",
        actor=principal,
        target_type="idea",
        target_id=call.idea_id,
        project_id=project_id,
        details={
            "rule": Rule.BID_MANAGE,
            "call_id": call.id,
            "sections": len(body.sections),
            "questions": sum(len(s.questions) for s in body.sections),
            "must_haves": len(body.must_haves),
            "removed": len(gone_sections) + len(gone_questions) + len(gone_musts),
            "cancelled_runs": cancelled,
        },
    )
    await db.flush()


def _initial(kind: MustHaveKind) -> MustHaveResult:
    """A bid's result for a new must-have: nobody decided yet."""
    return MustHaveResult.MISSING if kind is MustHaveKind.DOCUMENT else MustHaveResult.UNCHECKED


async def _kind_changed(
    db: AsyncSession, call: BidCall, must_have_id: UUID, kind: MustHaveKind
) -> None:
    """A kept must-have changed kind: decisions start over (a confirmation has no files:
    its documents are unlinked)."""
    if kind is MustHaveKind.CONFIRMATION:
        await db.execute(
            update(BidDocument)
            .where(BidDocument.call_id == call.id, BidDocument.must_have_id == must_have_id)
            .values(must_have_id=None)
            .execution_options(synchronize_session=False)
        )
    await db.execute(
        update(BidMustHaveResult)
        .where(BidMustHaveResult.must_have_id == must_have_id)
        .values(result=_initial(kind), decided_by_id=None, decided_at=None, note="")
        .execution_options(synchronize_session=False)
    )
