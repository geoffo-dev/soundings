"""The research step (Phase 8, product owner 2026-10-07; contract-phase8 section 3).

Purpose: before the team invests in an idea, check it isn't already being done somewhere
else in the company and that the right departments or teams have been consulted.

* **The step** (``ResearchStep``, project settings -> Research): off (the default),
  before evaluation or before proposal. While it is on, the project's lifecycle gains the
  Research status at that position (:func:`lifecycle`); while it is off there is no
  Research status, column or checklist anywhere in the project.
* **The checklist** (``project.edit_research``): 1-10 items, each a title, a hint (what
  to write) and "Required". An item is completed with a free-text answer
  (``idea.answer_research``: the idea's owner and project or platform admins).
* **The gate:** while a required item has no answer, an idea can't cross into a status
  after Research (:func:`crosses_gate`; reopening a closed idea counts from the status
  it was closed from), get its first evaluator before an evaluation step
  (:func:`starts_evaluation`), or start its proposal before a proposal step: 409
  ``research_incomplete`` (:class:`ResearchIncompleteProblem`). Project and platform
  admins may "Move anyway" (:class:`ResearchOverride`, ``idea.research_override``,
  audited). Moving back, or to Closed, is never blocked; an all-optional checklist never
  blocks; changing the checklist never moves ideas.
* **Where it shows:** cards carry the checklist's progress only for an idea in Research
  or in the status before it (:func:`shows_research_progress`); public tracking reports
  Research as the status before it (:func:`public_status`).

Answers are plain text people wrote: no score data, so everyone who can view the idea
(pending evaluators included) reads them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.models.enums import IdeaStatus, ResearchStep
from app.models.research import RESEARCH_ANSWER_MAX_LENGTH
from app.schemas.base import RequestModel, ResponseModel, SingleLine, VisibleLine, VisibleText
from app.schemas.common import Problem
from app.schemas.users import UserRef

__all__ = [
    "CANONICAL_STATUS_ORDER",
    "DEFAULT_RESEARCH_CHECKLIST",
    "MAX_RESEARCH_ITEMS",
    "MIN_RESEARCH_ITEMS",
    "OVERRIDE_REASON_MAX_LENGTH",
    "RESEARCH_ANSWER_MAX_LENGTH",
    "RESEARCH_HINT_MAX_LENGTH",
    "RESEARCH_TITLE_MAX_LENGTH",
    "DefaultChecklistItem",
    "DefaultResearchItem",
    "IdeaResearch",
    "IdeaResearchItem",
    "IdeasInResearchProblem",
    "RemovedResearchItem",
    "ResearchAnswer",
    "ResearchAnswerIn",
    "ResearchChecklistItem",
    "ResearchIncompleteProblem",
    "ResearchItemIn",
    "ResearchOpenItem",
    "ResearchOverride",
    "ResearchPermissions",
    "ResearchProgress",
    "ResearchSettings",
    "ResearchSettingsUpdate",
    "ResearchStep",
    "crosses_gate",
    "gate_status",
    "gated_statuses",
    "lifecycle",
    "public_status",
    "shows_research_progress",
    "starts_evaluation",
    "status_before_research",
]

MIN_RESEARCH_ITEMS: Final = 1
"""While the step is on (a step that is off may keep an empty checklist)."""
MAX_RESEARCH_ITEMS: Final = 10
RESEARCH_TITLE_MAX_LENGTH: Final = 80
RESEARCH_HINT_MAX_LENGTH: Final = 200
OVERRIDE_REASON_MAX_LENGTH: Final = 200


# --- The lifecycle and the gate (one definition for the services, policy and tests) -----
_BEFORE_EVALUATION: Final = (
    IdeaStatus.NEW,
    IdeaStatus.RESEARCH,
    IdeaStatus.EVALUATING,
    IdeaStatus.SHORTLISTED,
    IdeaStatus.PROPOSAL,
    IdeaStatus.CLOSED,
)
_BEFORE_PROPOSAL: Final = (
    IdeaStatus.NEW,
    IdeaStatus.EVALUATING,
    IdeaStatus.SHORTLISTED,
    IdeaStatus.RESEARCH,
    IdeaStatus.PROPOSAL,
    IdeaStatus.CLOSED,
)
_OFF: Final = tuple(status for status in _BEFORE_EVALUATION if status is not IdeaStatus.RESEARCH)

CANONICAL_STATUS_ORDER: Final[tuple[IdeaStatus, ...]] = tuple(IdeaStatus)
"""The order across projects (My work's groups, search, MCP): Research after New."""

_LIFECYCLES: Final[dict[ResearchStep, tuple[IdeaStatus, ...]]] = {
    ResearchStep.OFF: _OFF,
    ResearchStep.BEFORE_EVALUATION: _BEFORE_EVALUATION,
    ResearchStep.BEFORE_PROPOSAL: _BEFORE_PROPOSAL,
}


def lifecycle(step: ResearchStep) -> tuple[IdeaStatus, ...]:
    """A project's statuses in board order (Closed last): five while the step is off, six
    with Research at the step's position."""
    return _LIFECYCLES[step]


def gate_status(step: ResearchStep) -> IdeaStatus | None:
    """The status right after Research (``evaluating`` or ``proposal``); None while off."""
    if step is ResearchStep.OFF:
        return None
    order = _LIFECYCLES[step]
    return order[order.index(IdeaStatus.RESEARCH) + 1]


def gated_statuses(step: ResearchStep) -> frozenset[IdeaStatus]:
    """The statuses after Research, Closed excluded: the ones the checklist guards."""
    if step is ResearchStep.OFF:
        return frozenset()
    order = _LIFECYCLES[step]
    after = order[order.index(IdeaStatus.RESEARCH) + 1 :]
    return frozenset(status for status in after if status is not IdeaStatus.CLOSED)


def status_before_research(step: ResearchStep) -> IdeaStatus | None:
    """The status right before Research in the lifecycle (``new`` before evaluation,
    ``shortlisted`` before proposal); None while off."""
    if step is ResearchStep.OFF:
        return None
    order = _LIFECYCLES[step]
    return order[order.index(IdeaStatus.RESEARCH) - 1]


def crosses_gate(
    step: ResearchStep,
    from_status: IdeaStatus,
    to_status: IdeaStatus,
    *,
    closed_from: IdeaStatus | None = None,
) -> bool:
    """A status change the checklist guards: into a status after Research from one that
    isn't (New, Research or a status before it). Moving among the statuses after
    Research, back, or to Closed never crosses.

    **Reopening** (``from_status`` closed) counts from ``closed_from``, the status the
    idea was closed from (the ``from_status`` of its latest ``status_changed`` event into
    closed, read under the idea's lock): an idea closed from a status after Research
    reopens into one freely (Undo of a Close, an idea moved on with "Move anyway"), one
    closed from New or Research doesn't. Unknown (``None``: no such event) counts as New."""
    gated = gated_statuses(step)
    if from_status is IdeaStatus.CLOSED:
        from_status = (
            closed_from
            if closed_from is not None and closed_from is not IdeaStatus.CLOSED
            else IdeaStatus.NEW
        )
    return to_status in gated and from_status not in gated


def starts_evaluation(step: ResearchStep, status: IdeaStatus, evaluator_count: int) -> bool:
    """An evaluator invite (or "Ask AI to evaluate") the checklist guards: the step is
    before evaluation, the idea has no evaluator yet and isn't past Research (an idea in
    New or Research; Closed answers 409 ``evaluation_closed`` first)."""
    return (
        step is ResearchStep.BEFORE_EVALUATION
        and evaluator_count == 0
        and status not in gated_statuses(step)
    )


def shows_research_progress(step: ResearchStep, status: IdeaStatus) -> bool:
    """Whether ``IdeaSummary.research`` is set (the card's "2/3"): while the step is on,
    for an idea in Research or in the status right before it (:func:`status_before_research`:
    New before evaluation, Shortlisted before proposal). Never for an idea past Research,
    closed, or further back (a New idea when Research comes before the proposal)."""
    return step is not ResearchStep.OFF and status in (
        IdeaStatus.RESEARCH,
        status_before_research(step),
    )


def public_status(step: ResearchStep, status: IdeaStatus) -> IdeaStatus:
    """The status public tracking reports ("With the team"): Research is reported as the
    status before it in the project's lifecycle (:func:`status_before_research`; ``new``
    while the step is off, for history rows of an earlier step), every other status as
    itself. A change is shown to the submitter (a history row, a status email) only when
    the reported status (or the resolution) changes."""
    if status is not IdeaStatus.RESEARCH:
        return status
    return status_before_research(step) or IdeaStatus.NEW


# --- Shared pieces -------------------------------------------------------------------
class ResearchProgress(ResponseModel):
    """An idea's checklist at a glance ("2/3" on cards): active items only."""

    answered: int = Field(ge=0, description="Items with an answer.")
    total: int = Field(ge=0, description="Items in the checklist.")
    required_open: int = Field(
        ge=0,
        description=(
            "Required items without an answer: while above 0, moves past Research are "
            "refused (409 research_incomplete) unless an admin moves anyway."
        ),
    )


class ResearchOverride(RequestModel):
    """'Move anyway' on a request the research gate guards (``change_idea_status``,
    ``add_evaluators``, ``create_proposal``, ``request_ai_evaluation``)."""

    override_research: bool | None = Field(
        default=None,
        description=(
            'Phase 8: true = "Move anyway" past an unfinished research checklist (omitted, '
            "null or false: no override). true needs idea.research_override (project and "
            "platform admins, in a session; else 403 forbidden, or 403 insufficient_scope with "
            "an API key), even when nothing would block. Audited as idea.research_override "
            "when it lets the request through."
        ),
    )
    override_reason: (
        Annotated[str, Field(min_length=1, max_length=OVERRIDE_REASON_MAX_LENGTH), SingleLine]
        | None
    ) = Field(
        default=None,
        description="Optional, with override_research: why (one line, kept in the audit log).",
    )

    @model_validator(mode="after")
    def _reason_needs_override(self) -> ResearchOverride:
        if self.override_reason is not None and not self.override_research:
            raise ValueError("override_reason needs override_research")
        return self


# --- Project settings -> Research ----------------------------------------------------
class ResearchChecklistItem(ResponseModel):
    """An active checklist item, in order."""

    id: UUID
    position: int = Field(description="0-based order.")
    title: str
    hint: str = Field(description="What to write (shown under the title).")
    required: bool = Field(description="Gates the statuses after Research while unanswered.")


class RemovedResearchItem(ResponseModel):
    """A removed item that ideas answered: its answers are kept, hidden. Restore it by
    putting its id back in the checklist."""

    id: UUID
    title: str
    hint: str
    required: bool
    removed_at: datetime
    answer_count: int = Field(ge=1, description="Ideas whose answer to it is kept.")


@dataclass(frozen=True, slots=True)
class DefaultResearchItem:
    title: str
    hint: str
    required: bool


DEFAULT_RESEARCH_CHECKLIST: Final[tuple[DefaultResearchItem, ...]] = (
    DefaultResearchItem(
        "Not already being done elsewhere",
        "Search Soundings and ask around; note what you found.",
        True,
    ),
    DefaultResearchItem(
        "Departments or teams consulted",
        "Who you spoke to and what they said.",
        True,
    ),
    DefaultResearchItem(
        "Data protection considered",
        "Personal data involved, and who you checked with.",
        False,
    ),
)
"""Offered when a project admin turns the step on with an empty checklist (the SPA fills
the form with it; nothing is created until they save)."""


class DefaultChecklistItem(ResponseModel):
    """A default item, for the settings form to start from."""

    title: str
    hint: str
    required: bool


class ResearchSettings(ResponseModel):
    """Project settings -> Research."""

    step: ResearchStep
    items: list[ResearchChecklistItem] = Field(description="The active checklist, in order.")
    removed_items: list[RemovedResearchItem] = Field(
        description="Removed items that hold answers, most recently removed first."
    )
    default_items: list[DefaultChecklistItem] = Field(
        description=(
            "The default checklist (DEFAULT_RESEARCH_CHECKLIST): fill the form with it when "
            "the step is turned on while items is empty."
        )
    )
    ideas_in_research: int = Field(
        ge=0,
        description=(
            "Ideas of the project in Research now (held ones never are): while above 0 the "
            "step can't be turned off or moved (409 ideas_in_research): say to move them first."
        ),
    )


class ResearchItemIn(RequestModel):
    id: UUID | None = Field(
        default=None,
        description=(
            "An existing item (active, or removed: putting it back restores it with its "
            "answers); omit to add a new one. Unknown: 422 unknown_research_item."
        ),
    )
    title: Annotated[
        str, Field(min_length=1, max_length=RESEARCH_TITLE_MAX_LENGTH), VisibleLine, SingleLine
    ] = Field(
        description=(
            "Invisible characters are removed and at least one visible character must be "
            "left (Phase 8 review L2)."
        )
    )
    hint: Annotated[str, Field(max_length=RESEARCH_HINT_MAX_LENGTH), SingleLine] = ""
    required: bool = True


class ResearchSettingsUpdate(RequestModel):
    """The research step and, while it is on, the complete checklist in order (like
    ``replace_rubric``; last write wins, no version).

    Items left out are removed: archived if an idea answered them (answers kept, hidden),
    deleted otherwise. Changing the checklist never moves an idea. Changing ``step`` (off,
    or to the other position) while ideas are in Research: 409 ``ideas_in_research``.
    With ``step`` off, ``items`` is ignored and the checklist is kept as it is."""

    step: ResearchStep
    items: list[ResearchItemIn] = Field(
        default_factory=list,
        max_length=MAX_RESEARCH_ITEMS,
        description=(
            f"The complete checklist, in order: {MIN_RESEARCH_ITEMS}-{MAX_RESEARCH_ITEMS} "
            "items while the step is on. **Ignored while step is off**: turning the step off "
            "keeps the checklist and its answers as they are (hidden) for when it is turned "
            "on again, so send [] (or nothing) with off."
        ),
    )

    @field_validator("items")
    @classmethod
    def _unique(cls, items: list[ResearchItemIn]) -> list[ResearchItemIn]:
        titles = [item.title.casefold() for item in items]
        if len(set(titles)) != len(titles):
            raise ValueError("item titles must be unique")
        ids = [item.id for item in items if item.id is not None]
        if len(set(ids)) != len(ids):
            raise ValueError("an item id appears more than once")
        return items

    @model_validator(mode="after")
    def _items_while_on(self) -> ResearchSettingsUpdate:
        if self.step is not ResearchStep.OFF and len(self.items) < MIN_RESEARCH_ITEMS:
            raise ValueError("a research step needs at least one checklist item")
        return self


# --- An idea's research ----------------------------------------------------------------
class ResearchAnswer(ResponseModel):
    answer: str = Field(description="Plain text as typed (line breaks kept; not Markdown).")
    answered_by: UserRef | None = Field(description="Who answered first; null if gone.")
    answered_at: datetime
    updated_by: UserRef | None = Field(description="Who changed it last; null if gone.")
    updated_at: datetime = Field(description="Equals answered_at until someone edits it.")


class IdeaResearchItem(ResponseModel):
    """One active checklist item with this idea's answer."""

    item_id: UUID
    title: str
    hint: str
    required: bool
    answer: ResearchAnswer | None = Field(description="Null while unanswered.")


class ResearchPermissions(ResponseModel):
    can_answer: bool = Field(
        description="idea.answer_research: answer, edit and clear items (owner and admins)."
    )
    can_override: bool = Field(
        description='idea.research_override: offer "Move anyway" (project and platform admins).'
    )


class IdeaResearch(ResponseModel):
    """The Research panel of the idea page. While the project's step is off: ``step``
    off, no items, nothing blocking (answers kept from before stay hidden)."""

    step: ResearchStep
    gate_status: IdeaStatus | None = Field(
        description="The status right after Research (evaluating or proposal); null while off."
    )
    items: list[IdeaResearchItem] = Field(description="The active checklist, in order.")
    progress: ResearchProgress
    blocking: bool = Field(
        description=(
            "Moving this idea past Research would be refused now: required items open, the "
            "step on, and the idea neither past Research nor closed (false for a closed "
            'idea). Say "N required items left before <gate status label>".'
        )
    )
    permissions: ResearchPermissions


class ResearchAnswerIn(RequestModel):
    """Answer an item, or replace its answer (last write wins). Plain text, kept as typed
    apart from the stripped ends and invisible characters (removed: zero-width, bidi
    controls, other format characters, :func:`app.schemas.base.visible_text`, as for
    agents' text); line breaks allowed; at least one letter, digit, punctuation mark or
    symbol must be left (:func:`app.schemas.base.has_visible_character`), so a lone
    zero-width space, joiner, variation selector or combining mark never counts as
    answering (and so never passes the gate). The length counts the cleaned text
    (:data:`app.schemas.base.VisibleText`, Phase 8 review L2)."""

    answer: Annotated[
        str,
        Field(min_length=1, max_length=RESEARCH_ANSWER_MAX_LENGTH),
        VisibleText,
    ] = Field(
        description=(
            "1-2,000 characters of plain text with at least one visible character; "
            "zero-width, bidi-control and other invisible characters are removed."
        )
    )


# --- Problems ------------------------------------------------------------------------
class ResearchOpenItem(ResponseModel):
    item_id: UUID
    title: str


class ResearchIncompleteProblem(Problem):
    """409 from a request the research gate guards. With ``code`` ``research_incomplete``
    it lists the open required items and whether you may move anyway; other 409 codes of
    the same routes (``project_archived``, ``awaiting_moderation``, ...) have neither."""

    open_items: list[ResearchOpenItem] | None = Field(
        default=None, description="research_incomplete only: the required items left, in order."
    )
    can_override: bool | None = Field(
        default=None,
        description=(
            'research_incomplete only: you hold idea.research_override: offer "Move anyway" '
            "(send the request again with override_research: true)."
        ),
    )


class IdeasInResearchProblem(Problem):
    """409 ``ideas_in_research`` from ``replace_research_settings``: the step can't be
    turned off or moved while ideas are in Research."""

    idea_count: int | None = Field(
        default=None, description="ideas_in_research only: ideas in Research now."
    )
