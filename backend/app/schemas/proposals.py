"""Proposals: the project's template, section edits with optimistic concurrency, margin
comment threads and exports (SPEC sections 2 and 5, screen 5; contract-phase4
sections 3.1-3.3; Phase 8 templates: contract-phase8 section 2).

**Phase 8 (product owner, 2026-10-07): the template is per project**, edited like the
rubric (``project.edit_proposal_template``): 1-12 sections, each with a stable ``key``
(the built-in eight keep theirs; a new section's key comes from its title,
:func:`section_key_for`, and never changes), a title and a one-line hint. Removing a
section archives it (its text is kept, hidden from the editor and the exports) when
anything refers to it, else deletes it; putting its key back restores it with its text.
Every proposal of the project follows the template at once. New projects start from
:data:`DEFAULT_PROPOSAL_TEMPLATE`.

A proposal is one Markdown text per template section. Each section has its own
``version``: a save names the version it was based on (``base_version``) and is refused
with 409 ``proposal_conflict`` if someone saved that section since, so two people can
edit different sections at once and nobody overwrites anyone silently. Proposals carry
no score data; exports add the aggregate only for people who may see it.

Phase 5 adds **suggestions** (contract-phase5 section 3.4): suggested text for a whole
section, from a member (REST) or an agent (MCP ``propose_proposal_section``), which the
owner or an admin accepts (a normal versioned section save) or discards.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator

from app.models.enums import ProposalSectionKey, SuggestionSource, SuggestionStatus
from app.models.proposal import SECTION_KEY_MAX_LENGTH, SECTION_KEY_PATTERN
from app.schemas.base import RequestModel, ResponseModel, SingleLine, VisibleLine
from app.schemas.common import Problem
from app.schemas.ideas import IdeaRef
from app.schemas.research import ResearchOverride
from app.schemas.users import UserRef

__all__ = [
    "COMMENT_MAX_LENGTH",
    "DEFAULT_PROPOSAL_TEMPLATE",
    "MAX_COMMENTS_PER_THREAD",
    "MAX_PENDING_SUGGESTIONS",
    "MAX_TEMPLATE_SECTIONS",
    "MAX_THREADS_PER_PROPOSAL",
    "MIN_TEMPLATE_SECTIONS",
    "PROPOSAL_TEMPLATE",
    "SECTION_HINT_MAX_LENGTH",
    "SECTION_KEY_MAX_LENGTH",
    "SECTION_KEY_PATTERN",
    "SECTION_MAX_LENGTH",
    "SECTION_TITLE_MAX_LENGTH",
    "AcceptedProposalSuggestion",
    "Proposal",
    "ProposalComment",
    "ProposalCommentCreate",
    "ProposalConflictProblem",
    "ProposalPermissions",
    "ProposalSection",
    "ProposalSectionKey",
    "ProposalSectionUpdate",
    "ProposalStart",
    "ProposalSuggestion",
    "ProposalSuggestionAccept",
    "ProposalSuggestionCreate",
    "ProposalSuggestionList",
    "ProposalSuggestionPermissions",
    "ProposalTemplate",
    "ProposalTemplateSection",
    "ProposalTemplateUpdate",
    "ProposalThread",
    "ProposalThreadCreate",
    "ProposalThreadList",
    "ProposalView",
    "RemovedTemplateSection",
    "SectionKey",
    "SectionText",
    "SuggestionSource",
    "SuggestionStatus",
    "TemplateSection",
    "TemplateSectionIn",
    "section_key_for",
]

SECTION_MAX_LENGTH: Final = 20_000
"""Characters per section (8 sections of prose render to PDF in about 2 seconds;
contract-phase4 section 3.4 bounds tables and the render time; Phase 8's 12 sections stay
inside the renderer's limits: the layout is bounded by box count, not section count)."""
MIN_TEMPLATE_SECTIONS: Final = 1
MAX_TEMPLATE_SECTIONS: Final = 12
SECTION_TITLE_MAX_LENGTH: Final = 60
SECTION_HINT_MAX_LENGTH: Final = 200

SectionKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=SECTION_KEY_MAX_LENGTH,
        pattern=SECTION_KEY_PATTERN,
        description=(
            'A section of the project\'s template, by key: "summary", "next_steps", '
            '"carbon_impact" (GET /projects/{slug}/proposal-template, or the proposal\'s '
            "sections). A key the template doesn't have, or a removed section's: 422 "
            "unknown_section (404 in a path)."
        ),
    ),
]
"""A section key in a request (Phase 8: any key of the project's template)."""
COMMENT_MAX_LENGTH: Final = 5_000
MAX_THREADS_PER_PROPOSAL: Final = 500
MAX_COMMENTS_PER_THREAD: Final = 200


@dataclass(frozen=True, slots=True)
class TemplateSection:
    """A section of the built-in default template (``prompt`` is its hint)."""

    key: ProposalSectionKey
    title: str
    prompt: str


DEFAULT_PROPOSAL_TEMPLATE: Final[tuple[TemplateSection, ...]] = (
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
"""The built-in default template (SPEC section 2) in document order: every project starts
with it (migration 0012 gave it to every existing project; ``create_project`` gives it to
new ones). Titles for the outline, headings and exports; prompts (hints) as placeholders
for empty sections."""

PROPOSAL_TEMPLATE: Final = DEFAULT_PROPOSAL_TEMPLATE
"""Phases 4-7 name of :data:`DEFAULT_PROPOSAL_TEMPLATE`. Phase 8: a proposal follows its
project's template (``proposal_template_sections``); use this only for the defaults."""

_NOT_KEY_CHARACTERS: Final = re.compile(r"[^a-z0-9]+")
_KEY_BASE_LENGTH: Final = 36
"""Room for a ``_<n>`` suffix inside :data:`SECTION_KEY_MAX_LENGTH`."""


def section_key_for(title: str, taken: Collection[str]) -> str:
    """The key of a section added with ``title``: ASCII-folded (NFKD, accents dropped),
    lower case, every run of other characters one ``_``, trimmed of ``_``, cut to 36
    characters; ``s_`` in front if it starts with a digit; ``section`` if nothing is
    left. If ``taken`` (every key of the project, removed sections' included) has it,
    ``_2``, ``_3``, ... is appended. "Effort & rollout" -> ``effort_rollout``,
    "Coût" -> ``cout``, "2026 plan" -> ``s_2026_plan``."""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    base = _NOT_KEY_CHARACTERS.sub("_", folded.lower()).strip("_")[:_KEY_BASE_LENGTH]
    base = base.strip("_") or "section"
    if base[0].isdigit():
        base = f"s_{base}"[:_KEY_BASE_LENGTH].rstrip("_")
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}_{n}"
    return key


# --- Responses -----------------------------------------------------------------------
class ProposalSection(ResponseModel):
    """One section of the project's template with this proposal's text. A proposal lists
    every active section of its project's template, in template order (Phase 8)."""

    key: str = Field(
        description=(
            'The section\'s stable key ("summary", "carbon_impact"): use it in paths and '
            "in suggestions; it never changes, even when the section is renamed."
        )
    )
    title: str = Field(description='From the project\'s template, e.g. "Market & users".')
    prompt: str = Field(
        description="The template section's hint: the placeholder while the section is empty."
    )
    body_md: str = Field(description="Markdown; empty until someone writes it.")
    version: int = Field(
        ge=1, description="Send it back as base_version when you save this section."
    )
    updated_at: datetime
    updated_by: UserRef | None = Field(description="Who saved it last; null if nobody has.")


class Proposal(ResponseModel):
    id: UUID
    idea: IdeaRef
    sections: list[ProposalSection] = Field(
        description=(
            "Every active section of the project's template, in its order (Phase 8: 1-12; "
            "removed sections and their text are left out)."
        )
    )
    created_at: datetime
    created_by: UserRef | None
    updated_at: datetime = Field(description="The latest section save.")


class ProposalPermissions(ResponseModel):
    """What the current user may do on the Proposal tab (the API enforces the same)."""

    can_create: bool = Field(
        description=(
            'proposal.write and no proposal yet: show "Start proposal" (the idea is '
            "Shortlisted or in Proposal, c7; Phase 8: or in Research when the project's "
            "research step is before_proposal)."
        )
    )
    start_blocked_by_research: bool = Field(
        default=False,
        description=(
            "Phase 8: starting now would be refused (409 research_incomplete): the project's "
            "research step is before_proposal, the idea is Shortlisted or in Research and "
            'required items are open. Say so next to "Start proposal"; admins '
            "(IdeaResearch.permissions.can_override) may start anyway."
        ),
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
    """A margin thread on one section; resolved threads collapse. Threads of a removed
    section are hidden with it (and back when it is restored)."""

    id: UUID
    section_key: str = Field(description="A key of the project's template.")
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: UserRef | None
    comments: list[ProposalComment] = Field(
        description="Oldest first; the first one opened the thread."
    )


class ProposalThreadList(ResponseModel):
    """Every thread of the proposal with at least one comment that isn't deleted, on an
    active section, in template-section order, then oldest first (at most 500 threads: no
    paging)."""

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

    section_key: SectionKey
    body_md: str = Field(min_length=1, max_length=COMMENT_MAX_LENGTH, description="Markdown.")


class ProposalCommentCreate(RequestModel):
    """Reply in a thread (replies are flat)."""

    body_md: str = Field(min_length=1, max_length=COMMENT_MAX_LENGTH, description="Markdown.")


# --- Phase 5: suggestions (contract-phase5 section 3.4) ---------------------------------
MAX_PENDING_SUGGESTIONS: Final = 50
"""Pending suggestions one proposal may hold on its active sections; more: 409
``too_many_suggestions``. Phase 8: pending suggestions of removed sections (hidden, kept)
don't count."""


class ProposalSuggestion(ResponseModel):
    """Suggested text for a whole section, from a member or an agent. Accepting it saves
    it as the section's text (a normal versioned save); discarding dismisses it."""

    id: UUID
    section_key: str = Field(description="A key of the project's template.")
    body_md: str = Field(description="The proposed text of the whole section (Markdown).")
    base_version: int = Field(ge=1, description="The section version its author read.")
    section_changed: bool = Field(
        description=(
            "The section has been saved since base_version: say so next to the suggestion "
            '("The section has changed since this was suggested").'
        )
    )
    author: UserRef | None = Field(description="Null if the user no longer exists.")
    source: SuggestionSource = Field(
        description=(
            "ai whenever the author is an AI agent's service account (show the AI badge), "
            "whatever the channel; otherwise mcp (an MCP client) or api (the app or an API "
            "client)."
        )
    )
    status: SuggestionStatus
    created_at: datetime
    decided_at: datetime | None
    decided_by: UserRef | None = Field(
        description="Who accepted or discarded it (the author when a newer one replaced it)."
    )


class ProposalSuggestionPermissions(ResponseModel):
    """What you may do with suggestions on this proposal (the API enforces the same)."""

    can_suggest: bool = Field(
        description="proposal.suggest_section: members and admins while c7 holds."
    )
    can_decide: bool = Field(
        description="proposal.write: accept or discard (the owner and admins, while c7 holds)."
    )


class ProposalSuggestionList(ResponseModel):
    """Pending suggestions for active sections, in template-section order, then oldest
    first (no paging: at most 50 are pending on active sections when one is created;
    restoring a removed section can bring back a few more)."""

    items: list[ProposalSuggestion]
    permissions: ProposalSuggestionPermissions


class AcceptedProposalSuggestion(ResponseModel):
    """The accepted suggestion and the section as saved (keep editing from
    ``section.version``)."""

    suggestion: ProposalSuggestion
    section: ProposalSection


class ProposalSuggestionCreate(RequestModel):
    """Suggest the whole text of one section. Your earlier pending suggestion for the
    same section, if any, is replaced (discarded)."""

    section_key: SectionKey
    body_md: SectionText = Field(
        min_length=1, description="Markdown, kept verbatim; not only whitespace."
    )
    base_version: int | None = Field(
        default=None,
        ge=1,
        description=(
            "The section version you read (from get_proposal); default the current one. "
            "Above the current version: 422 validation_error."
        ),
    )

    @field_validator("body_md")
    @classmethod
    def _not_blank(cls, body_md: str) -> str:
        if not body_md.strip():
            raise ValueError("the suggested text is empty")
        return body_md


class ProposalSuggestionAccept(RequestModel):
    """Accept: the section's text becomes the suggestion's. ``base_version`` is the
    section version you are looking at (as for a section save): 409
    ``proposal_conflict`` with ``current`` if someone saved it since."""

    base_version: int = Field(ge=1)


# --- Phase 8: starting a proposal, and the project's template (contract-phase8 §2) -------
class ProposalStart(ResearchOverride):
    """``create_proposal``'s optional body: "Start anyway" past an unfinished research
    checklist (the project's research step is before_proposal). Without a body: no
    override."""


class ProposalTemplateSection(ResponseModel):
    """An active section of a project's template."""

    key: str = Field(description="Stable and immutable (paths, MCP, AI drafts use it).")
    title: str
    hint: str = Field(description="One line shown in the editor while the section is empty.")
    position: int = Field(description="0-based order.")
    proposal_count: int = Field(
        ge=0,
        description=(
            "Proposals of the project with text in this section: before removing it, say "
            '"Its text in N proposals is kept and comes back if you restore it" (N > 0).'
        ),
    )


class RemovedTemplateSection(ResponseModel):
    """A removed section that holds something (text in a proposal, a margin thread, a
    suggestion or an AI draft run): hidden from the editor and the exports, kept.
    Restore it by putting its key back in the template."""

    key: str
    title: str
    hint: str
    position: int = Field(
        default=0,
        ge=0,
        description=(
            "Phase 8b: where it was in the template when it was removed (0-based): Restore "
            "puts it back there (at the end when the template is shorter now)."
        ),
    )
    removed_at: datetime
    proposal_count: int = Field(
        ge=0,
        description=(
            'Proposals with text in it ("Text in 3 proposals"). May be 0: a section is also '
            'kept for a margin thread, a suggestion or an AI run ("Kept for its comments '
            'and suggestions").'
        ),
    )


class ProposalTemplate(ResponseModel):
    """A project's proposal template (project settings -> Workflow -> Proposal template).
    Saves are last write wins (no version), like the rubric."""

    sections: list[ProposalTemplateSection] = Field(
        description=f"{MIN_TEMPLATE_SECTIONS}-{MAX_TEMPLATE_SECTIONS} active sections, in order."
    )
    removed_sections: list[RemovedTemplateSection] = Field(
        description="Most recently removed first."
    )


class TemplateSectionIn(RequestModel):
    key: SectionKey | None = Field(
        default=None,
        description=(
            "An existing section (active, or removed: putting it back restores it with its "
            "text); omit to add a new one, whose key the server makes from the title "
            "(section_key_for). Unknown: 422 unknown_section."
        ),
    )
    title: Annotated[
        str, Field(min_length=1, max_length=SECTION_TITLE_MAX_LENGTH), VisibleLine, SingleLine
    ] = Field(
        description=(
            "Invisible characters are removed and at least one visible character must be "
            "left (Phase 8 review L2)."
        )
    )
    hint: Annotated[str, Field(max_length=SECTION_HINT_MAX_LENGTH), SingleLine] = ""


class ProposalTemplateUpdate(RequestModel):
    """The complete new template, in order (like ``replace_rubric``). Renaming keeps a
    section's key and text. Sections left out are removed: archived if anything refers
    to them (text in a proposal, a thread, a suggestion, an AI run), deleted otherwise.
    Every proposal of the project follows the new template at once."""

    sections: list[TemplateSectionIn] = Field(
        min_length=MIN_TEMPLATE_SECTIONS, max_length=MAX_TEMPLATE_SECTIONS
    )

    @field_validator("sections")
    @classmethod
    def _unique(cls, sections: list[TemplateSectionIn]) -> list[TemplateSectionIn]:
        titles = [section.title.casefold() for section in sections]
        if len(set(titles)) != len(titles):
            raise ValueError("section titles must be unique")
        keys = [section.key for section in sections if section.key is not None]
        if len(set(keys)) != len(keys):
            raise ValueError("a section key appears more than once")
        return sections
