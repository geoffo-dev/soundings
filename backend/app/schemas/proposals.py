"""Proposals: the fixed template, section edits with optimistic concurrency, margin
comment threads and exports (SPEC sections 2 and 5, screen 5; contract-phase4
sections 3.1-3.3).

A proposal is one Markdown text per template section. Each section has its own
``version``: a save names the version it was based on (``base_version``) and is refused
with 409 ``proposal_conflict`` if someone saved that section since, so two people can
edit different sections at once and nobody overwrites anyone silently. Proposals carry
no score data; exports add the aggregate only for people who may see it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from pydantic import Field, StringConstraints

from app.models.enums import ProposalSectionKey
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.common import Problem
from app.schemas.ideas import IdeaRef
from app.schemas.users import UserRef

__all__ = [
    "COMMENT_MAX_LENGTH",
    "MAX_COMMENTS_PER_THREAD",
    "MAX_THREADS_PER_PROPOSAL",
    "PROPOSAL_TEMPLATE",
    "SECTION_MAX_LENGTH",
    "Proposal",
    "ProposalComment",
    "ProposalCommentCreate",
    "ProposalConflictProblem",
    "ProposalPermissions",
    "ProposalSection",
    "ProposalSectionKey",
    "ProposalSectionUpdate",
    "ProposalThread",
    "ProposalThreadCreate",
    "ProposalThreadList",
    "ProposalView",
    "TemplateSection",
]

SECTION_MAX_LENGTH: Final = 20_000
"""Characters per section (8 sections of prose render to PDF in about 2 seconds;
contract-phase4 section 3.4 bounds tables and the render time)."""
COMMENT_MAX_LENGTH: Final = 5_000
MAX_THREADS_PER_PROPOSAL: Final = 500
MAX_COMMENTS_PER_THREAD: Final = 200


@dataclass(frozen=True, slots=True)
class TemplateSection:
    key: ProposalSectionKey
    title: str
    prompt: str


PROPOSAL_TEMPLATE: Final[tuple[TemplateSection, ...]] = (
    TemplateSection(
        ProposalSectionKey.SUMMARY,
        "Summary",
        "The idea in a few sentences: what we would do and why it matters.",
    ),
    TemplateSection(
        ProposalSectionKey.PROBLEM, "Problem", "Who has this problem, and how do we know?"
    ),
    TemplateSection(
        ProposalSectionKey.SOLUTION,
        "Solution",
        "Describe what we would build or change, and how it solves the problem.",
    ),
    TemplateSection(
        ProposalSectionKey.MARKET,
        "Market & users",
        "Who would use or buy this, how many of them are there, and how do we reach them?",
    ),
    TemplateSection(
        ProposalSectionKey.COST,
        "Cost & effort",
        "What would it take: people, time, money and dependencies?",
    ),
    TemplateSection(
        ProposalSectionKey.BENEFITS,
        "Benefits / revenue",
        "What do we gain: revenue, savings or other benefits, and how will we measure them?",
    ),
    TemplateSection(
        ProposalSectionKey.RISKS, "Risks", "What could go wrong, and how would we reduce it?"
    ),
    TemplateSection(
        ProposalSectionKey.NEXT_STEPS,
        "Next steps / the ask",
        "What do you need, from whom, and by when?",
    ),
)
"""The fixed template (SPEC section 2) in document order: titles for the outline,
headings and exports; prompts as placeholders for empty sections."""


# --- Responses -----------------------------------------------------------------------
class ProposalSection(ResponseModel):
    """One template section. Always all eight, in template order."""

    key: ProposalSectionKey
    title: str = Field(description='From the template, e.g. "Market & users".')
    prompt: str = Field(description="Placeholder while the section is empty.")
    body_md: str = Field(description="Markdown; empty until someone writes it.")
    version: int = Field(
        ge=1, description="Send it back as base_version when you save this section."
    )
    updated_at: datetime
    updated_by: UserRef | None = Field(description="Who saved it last; null if nobody has.")


class Proposal(ResponseModel):
    id: UUID
    idea: IdeaRef
    sections: list[ProposalSection] = Field(description="All eight, in template order.")
    created_at: datetime
    created_by: UserRef | None
    updated_at: datetime = Field(description="The latest section save.")


class ProposalPermissions(ResponseModel):
    """What the current user may do on the Proposal tab (the API enforces the same)."""

    can_create: bool = Field(
        description=(
            'proposal.write and no proposal yet: show "Start proposal" (the idea is '
            "Shortlisted or in Proposal, c7)."
        )
    )
    can_edit: bool = Field(
        description="proposal.write: edit sections (owner and admins, while c7 holds)."
    )
    can_comment: bool = Field(
        description="proposal.comment: open threads, reply, resolve and reopen."
    )
    can_export: bool = Field(description="proposal.export: PDF and Markdown.")


class ProposalView(ResponseModel):
    """The Proposal tab: the proposal, if one has been started, and what you may do."""

    proposal: Proposal | None = Field(
        description=(
            'Null until the owner starts one ("The owner will write a proposal once this '
            'idea is shortlisted.")'
        )
    )
    permissions: ProposalPermissions


class ProposalComment(ResponseModel):
    """A comment in a margin thread (plain Markdown; no @mentions in Phase 4)."""

    id: UUID
    author: UserRef | None = Field(description="Null if the user no longer exists.")
    body_md: str = Field(description="Empty when deleted.")
    created_at: datetime
    deleted: bool = Field(description='Show a "comment deleted" placeholder.')
    can_delete: bool = Field(description="You wrote it, or you are a project admin.")


class ProposalThread(ResponseModel):
    """A margin thread on one section; resolved threads collapse."""

    id: UUID
    section_key: ProposalSectionKey
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: UserRef | None
    comments: list[ProposalComment] = Field(
        description="Oldest first; the first one opened the thread."
    )


class ProposalThreadList(ResponseModel):
    """Every thread of the proposal with at least one comment that isn't deleted, in
    template-section order, then oldest first (at most 500 threads: no paging)."""

    items: list[ProposalThread]


class ProposalConflictProblem(Problem):
    """409 from ``update_proposal_section``. With ``code`` ``proposal_conflict`` it
    carries the section as it is now, so "Reload" shows it and "Keep mine" saves again
    with ``current.version`` without a second request that could race another save.
    Other 409 codes (``proposal_not_available``, ``project_archived``,
    ``awaiting_moderation``) have no ``current``."""

    current: ProposalSection | None = Field(
        default=None, description="proposal_conflict only: the section as saved now."
    )


# --- Requests ------------------------------------------------------------------------
SectionText = Annotated[
    str, StringConstraints(strip_whitespace=False, max_length=SECTION_MAX_LENGTH)
]
"""A section's Markdown exactly as typed: unlike other request strings it is **not**
stripped (leading indentation is an indented code block; autosave must not eat the
spaces and newlines someone is typing). NUL is still refused."""


class ProposalSectionUpdate(RequestModel):
    """Save one section. ``base_version`` is the ``version`` your text started from:
    409 ``proposal_conflict`` if the section has changed since (the problem's
    ``current`` is the section now: reload it, or keep yours by saving again with
    ``current.version``). Saving identical text changes nothing. The text is stored
    exactly as sent (no whitespace trimming)."""

    body_md: SectionText = Field(description="Markdown, kept verbatim.")
    base_version: int = Field(ge=1)


class ProposalThreadCreate(RequestModel):
    """Open a thread on a section with its first comment."""

    section_key: ProposalSectionKey
    body_md: str = Field(min_length=1, max_length=COMMENT_MAX_LENGTH, description="Markdown.")


class ProposalCommentCreate(RequestModel):
    """Reply in a thread (replies are flat)."""

    body_md: str = Field(min_length=1, max_length=COMMENT_MAX_LENGTH, description="Markdown.")
