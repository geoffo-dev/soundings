"""The bid evaluation report (contract-phase10 section 13, L11): Markdown and PDF for call
managers only (``bid.view_scores``; the route checks it), through the proposal exports'
machinery (:mod:`app.proposals.export`: the shared limit, the project's branding, the
Markdown writer and the PDF child with its 5,000-box bound).

What it holds: the call (status, deadline, assessment due date, progress); the ranking
with each bid's section scores, price, price score, total and whether an AI assessment is
counted (:func:`app.bids.views.comparison`, so it is scored the same way before and after
the award, and a manager who owes an assessment gets no ranks and "Hidden until you submit"
for that bid's scores: role matrix 3a rule 1); each bid's must-have **counts** (met, not
met, missing, unchecked) and the items missing or not met by name (not the whole grid:
review S15); the rejected bids with their reasons; the assessors per section with their
progress; the award with its reason.

Text people or bidders wrote (the call's title, bidders, section and must-have titles,
reasons, names) is escaped (:func:`app.proposals.document.markdown_text`): it shows as
text, never as markup, a link or a table column, in the Markdown and in the PDF (whose
sections are this Markdown, rendered by the proposal renderer: raw HTML dropped).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bids.access import LoadedCall
from app.bids.data import CallData, load_call_data
from app.bids.views import comparison
from app.config import Settings
from app.domain.labels import status_label
from app.domain.principal import Principal
from app.models.bid import Bid
from app.models.enums import BidCallStatus, BidStatus, MustHaveResult
from app.models.user import User
from app.proposals.document import ExportDocument, ExportSection, markdown_text
from app.proposals.export import branding_for, check_limit
from app.schemas.bids import BidComparison, BidComparisonRow
from app.services.refs import idea_key
from app.services.sql import any_of

__all__ = ["HIDDEN", "REPORT_EYEBROW", "REPORT_KIND", "report_document"]

REPORT_EYEBROW: Final = "Bid evaluation report"
REPORT_KIND: Final = "bid-evaluation"
"""``<KEY>-bid-evaluation.md`` / ``.pdf``."""
HIDDEN: Final = "Hidden until you submit"
NONE: Final = "\u2013"
"""An empty cell: an en dash."""
_CALL_STATUS: Final = {
    BidCallStatus.DRAFT: "Draft",
    BidCallStatus.OPEN: "Open for bids",
    BidCallStatus.ASSESSING: "Being assessed",
    BidCallStatus.AWARDED: "Awarded",
    BidCallStatus.CANCELLED: "Cancelled",
}
_BID_STATUS: Final = {
    BidStatus.RECEIVED: "Received",
    BidStatus.QUALIFIED: "Qualified",
    BidStatus.REJECTED: "Rejected",
    BidStatus.AWARDED: "Awarded",
    BidStatus.UNSUCCESSFUL: "Unsuccessful",
}
_FAILING: Final = {MustHaveResult.MISSING: "missing", MustHaveResult.NOT_MET: "not met"}


def _text(value: str) -> str:
    return markdown_text(value)


def _day(moment: datetime | None, settings: Settings) -> str:
    if moment is None:
        return NONE
    local = moment.astimezone(settings.tz)
    return f"{local.day} {local:%B %Y}"


def _cell(value: str) -> str:
    """A table cell: one line of escaped text (``|`` included)."""
    return value or NONE


def _table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def _money(value: str | None, currency: str) -> str:
    if value is None:
        return NONE
    try:
        amount = Decimal(value)
    except InvalidOperation:  # pragma: no cover - stored as numeric
        return NONE
    return f"{_text(currency)} {amount:,.2f}"


async def _names(db: AsyncSession, ids: Iterable[UUID | None]) -> dict[UUID, str]:
    wanted = [user_id for user_id in dict.fromkeys(ids) if user_id is not None]
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.display_name).where(any_of(User.id, wanted)))
    return dict(rows.all())


def _summary(data: CallData, view: BidComparison, settings: Settings) -> str:
    call = data.call
    rejected = sum(1 for bid in data.bids if bid.status is BidStatus.REJECTED)
    progress = view.progress
    lines = [
        f"- Status: {_CALL_STATUS[call.status]}",
        f"- Deadline for bids: {_day(call.deadline_at, settings)}",
        f"- Assessments due: {_day(call.assessment_due_at, settings)}",
        f"- Bids: {len(data.bids)} received, {rejected} rejected",
        f"- Assessed: {progress.submitted} of {progress.total}"
        + (" (complete)" if view.complete else ""),
    ]
    if view.ranking_hidden:
        lines.append(
            "\n_You still owe assessments: the ranking shows once you have submitted yours, "
            "and the scores of the bids you owe are hidden until then._"
        )
    return "\n".join(lines)


def _score_cell(row: BidComparisonRow, index: int) -> str:
    if row.bid.status is BidStatus.REJECTED:
        return NONE
    cell = row.sections[index]
    if cell.hidden:
        return HIDDEN
    if cell.score is None:
        return NONE
    return f"{cell.score:.1f}" + (" ‡" if cell.disagreement else "")


def _ranking(view: BidComparison) -> str:
    sections = [f"{_text(s.title)} ({s.weight} %)" for s in view.sections]
    header = [
        "Rank",
        "Bidder",
        "Status",
        *sections,
        "Price",
        "Price score",
        "Total",
        "AI",
        "Assessed",
    ]
    rows = []
    for row in view.rows:
        rank = NONE
        if row.rank is not None:
            rank = f"{row.rank}=" if row.tied else str(row.rank)
        total = (
            HIDDEN if row.total_hidden else (f"{row.total:.1f}" if row.total is not None else NONE)
        )
        rows.append(
            [
                rank,
                _text(row.bid.bidder) + (" (late)" if row.late else ""),
                _BID_STATUS[row.bid.status],
                *(_score_cell(row, index) for index in range(len(view.sections))),
                _money(row.price, view.currency),
                f"{row.price_score:.2f}" if row.price_score is not None else NONE,
                total,
                "Included" if row.ai_included else NONE,
                f"{row.progress.submitted} of {row.progress.total}",
            ]
        )
    notes = [
        "Section scores and totals are out of 100; the price score is out of 5 (the lowest "
        "price of the bids that met every must-have / this price x 5). ‡ two assessors' scores "
        'on a question differ by 2 or more. "AI": an AI assessment counted in the scores.'
    ]
    if view.ranking_hidden:
        notes.append("_No ranks while you owe assessments._")
    elif not any(row.rank is not None for row in view.rows):
        notes.append("_No bid has a total yet._")
    if not view.rows:
        return "_No bids were entered._"
    return _table(header, rows) + "\n\n" + "\n\n".join(notes)


def _must_haves(data: CallData) -> str:
    if not data.must_haves:
        return "_The call has no must-haves._"
    if not data.bids:
        return "_No bids were entered._"
    rows = []
    for bid in data.bids:
        found = data.results.get(bid.id, {})
        counts = dict.fromkeys(MustHaveResult, 0)
        failing = []
        for must_have in data.must_haves:
            result = found[must_have.id].result if must_have.id in found else MustHaveResult.MISSING
            counts[result] += 1
            if result in _FAILING:
                failing.append(f"{_text(must_have.text)} ({_FAILING[result]})")
        rows.append(
            [
                _text(bid.bidder),
                str(counts[MustHaveResult.MET]),
                str(counts[MustHaveResult.NOT_MET]),
                str(counts[MustHaveResult.MISSING]),
                str(counts[MustHaveResult.UNCHECKED]),
                "; ".join(failing) or NONE,
            ]
        )
    return (
        _table(["Bidder", "Met", "Not met", "Missing", "Unchecked", "Missing or not met"], rows)
        + f"\n\n{len(data.must_haves)} must-haves in the call."
    )


def _rejected(bids: Sequence[Bid], names: dict[UUID, str], settings: Settings) -> str:
    rejected = [bid for bid in bids if bid.status is BidStatus.REJECTED]
    if not rejected:
        return "_No bid was rejected._"
    lines = []
    for bid in rejected:
        who = names.get(bid.rejected_by_id) if bid.rejected_by_id else None
        by = f" by {_text(who)}" if who else ""
        reason = _text(bid.rejection_reason) if bid.rejection_reason else "No reason given."
        lines.append(
            f"- **{_text(bid.bidder)}**, rejected {_day(bid.rejected_at, settings)}{by}: {reason}"
        )
    return "\n".join(lines)


def _assessors(data: CallData) -> str:
    lines = []
    for section in data.sections:
        people = []
        for assignment in data.section_users(section.id):
            progress = data.assignment_progress(assignment)
            note = "" if assignment.eligible else ", no longer assesses"
            people.append(
                f"{_text(assignment.user.display_name)} "
                f"({progress.submitted} of {progress.total}{note})"
            )
        who = ", ".join(people) if people else "_nobody assigned_"
        lines.append(f"- **{_text(section.title)}** ({section.weight} %): {who}")
    return "\n".join(lines) if lines else "_The call has no sections._"


def _award(data: CallData, names: dict[UUID, str], settings: Settings) -> str:
    call = data.call
    if call.status is BidCallStatus.AWARDED:
        winner = next((bid for bid in data.bids if bid.status is BidStatus.AWARDED), None)
        who = names.get(call.awarded_by_id) if call.awarded_by_id else None
        by = f" by {_text(who)}" if who else ""
        name = f"**{_text(winner.bidder)}**" if winner is not None else "a bid"
        line = f"Awarded to {name} on {_day(call.awarded_at, settings)}{by}."
        if call.award_reason:
            line += f"\n\nReason: {_text(call.award_reason)}"
        return line
    if call.status is BidCallStatus.CANCELLED:
        line = f"The call was cancelled on {_day(call.cancelled_at, settings)}."
        if call.cancel_reason:
            line += f"\n\nReason: {_text(call.cancel_reason)}"
        return line
    return "_Not awarded yet._"


async def report_document(
    db: AsyncSession,
    principal: Principal,
    loaded: LoadedCall,
    settings: Settings,
    app: Any,
    *,
    now: datetime,
) -> ExportDocument:
    """The report as ``principal`` (a call manager: the route checked ``bid.view_scores``)
    may see it; 429 beyond the export limit (shared with proposal exports)."""
    check_limit(app, principal)
    idea, project, call = loaded.idea, loaded.project, loaded.call
    data = await load_call_data(db, call, answers=True, results=True, ai=True)
    view = comparison(principal, loaded.resource, data)
    names = await _names(
        db,
        [
            idea.owner_id,
            call.awarded_by_id,
            *(bid.rejected_by_id for bid in data.bids if bid.status is BidStatus.REJECTED),
        ],
    )
    sections = (
        ExportSection("summary", "Summary", _summary(data, view, settings)),
        ExportSection("ranking", "Ranking", _ranking(view)),
        ExportSection("must_haves", "Must-haves", _must_haves(data)),
        ExportSection("rejected", "Rejected bids", _rejected(data.bids, names, settings)),
        ExportSection("assessors", "Assessors", _assessors(data)),
        ExportSection("award", "Award", _award(data, names, settings)),
    )
    return ExportDocument(
        title=call.title,
        idea_key=idea_key(idea, project),
        project_name=project.name,
        status_label=status_label(project.status_labels, idea.status, idea.resolution),
        owner_name=names.get(idea.owner_id) if idea.owner_id else None,
        exported_at=now.astimezone(settings.tz),
        exported_by=principal.user.display_name,
        sections=sections,
        branding=await branding_for(db, project.id),
        eyebrow=REPORT_EYEBROW,
    )
