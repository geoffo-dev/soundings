"""The authorisation policy: docs/role-matrix.md as a table, and :func:`authorize`.

Deny by default: a rule missing from :data:`POLICY`, a column without a grant or a
failed condition denies. Evaluation order (role matrix section 2), first failure wins:

1. **401**: no principal (anonymous) for a rule that needs one;
2. **404**: an API key restricted away from the project, a column that may not know
   the resource exists (``NMp``, or ``404`` in the matrix), an idea held for email
   confirmation (c12, for everyone), or the implied view rule (``project.view`` /
   ``idea.view``, incl. c12) failing;
3. **403**: the key's scopes, then no grant for the column or an overlay, then the
   principal conditions (c1 submitter, c2, c3, c15, c16, c17, c20, c21);
4. **422**: request-body conditions (c4);
5. **409**: state conditions (archived project, then c19 (an idea held for moderation),
   then c1 status, c5, c6, c7, c10, c11, c13, c18).

When several grants apply (the column and the owner/evaluator overlays), the principal
is allowed if any grant passes; otherwise the failure that got furthest wins, so the
owner of a closed idea hears ``409 idea_closed`` rather than ``403``.

Phase 8b, the researcher (role matrix table L, ADR 0016): column **R** is the idea's
live researcher (c24) without a role in its **private** project, for idea-scoped rules on
that one idea (its cells replace NMp's; :data:`GUEST_CELLS`), and while a request is
served, :mod:`app.authz.guest` hides every operation R may not reach (404). The overlay
**+Rsr** (:data:`RESEARCHER_OVERLAY`) adds commenting, answering and "Hand back" to the
live researcher in **any** column, without a role (unlike +Own and +Evl).

Blind evaluation (✱) is part of the policy: ``evaluation.view_others`` and
``score.view_aggregate`` are denied with ``hidden=True`` for a pending evaluator
(assigned, not submitted), whatever their role, and always for a service account (an AI
agent: role matrix section 3 rule 9). Hidden is not an error: callers
null the data and set ``score_hidden`` (use :func:`can`, not :func:`require`).

Everything here is pure (no I/O); :mod:`app.authz.loaders` builds :class:`Resource`
from the database and :mod:`app.authz.queries` applies the same rules in SQL.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.authz.guest import GuestAccess, guest_access
from app.authz.rules import RULE_SCOPES, Rule
from app.domain.principal import Principal
from app.errors import NotFoundProblem, ProblemError
from app.models.enums import (
    EvaluatorState,
    HoldReason,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    ResearchStep,
)
from app.models.idea import Idea
from app.models.project import Project
from app.schemas.projects import RESERVED_SLUGS

__all__ = [
    "ASSIGNABLE_ROLES",
    "CONDITIONS",
    "FROZEN_WHILE_HELD",
    "ISSUING_KEYS",
    "MANAGE_USER_ACCESS",
    "PERSONS_ONLY",
    "POLICY",
    "Column",
    "Decision",
    "IdeaFacts",
    "NamedResearcher",
    "ProjectFacts",
    "Resource",
    "RuleSpec",
    "Scope",
    "authorize",
    "best_decision",
    "can",
    "counted_by_default",
    "is_agent",
    "may_cite_sources",
    "not_found",
    "require",
    "require_any",
    "require_view",
    "researcher_live",
    "searches_co_members_only",
    "sees_email_trouble",
    "writes_as_ai",
]

ASSIGNABLE_ROLES: Final = frozenset({ProjectRole.ADMIN, ProjectRole.MEMBER})
"""Roles that can own or evaluate ideas, and that make overlays count (c4, section 1)."""


# --- Facts about the resource ----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProjectFacts:
    """A project. ``public_submission_enabled`` is the project's own switch for its
    public form; ``slug_reserved``: an older project whose slug is one of the app's own
    paths (``RESERVED_SLUGS``), which can never have a public form (c8);
    ``research_step``: the project's research step (Phase 8; c7 allows a proposal from
    Research when it comes before the proposal)."""

    id: UUID
    visibility: ProjectVisibility
    archived: bool = False
    allow_volunteer_owners: bool = True
    public_submission_enabled: bool = False
    slug_reserved: bool = False
    research_step: ResearchStep = ResearchStep.OFF

    @classmethod
    def of(cls, project: Project) -> ProjectFacts:
        return cls(
            id=project.id,
            visibility=project.visibility,
            archived=project.archived_at is not None,
            allow_volunteer_owners=project.allow_volunteer_owners,
            public_submission_enabled=project.public_submission_enabled,
            slug_reserved=project.slug in RESERVED_SLUGS,
            research_step=project.research_step,
        )


@dataclass(frozen=True, slots=True)
class IdeaFacts:
    """An idea, plus the principal's own evaluator assignment on it.

    ``my_evaluation``: ``None`` when the principal is not an assigned evaluator,
    else their state (``invited`` = nothing saved yet, ``draft``, ``submitted``).
    ``held_for``: a public submission not visible yet (``ideas.held_for``; c12, c19).
    ``researcher_id``: Phase 8b, the idea's assigned researcher (column R, +Rsr, c24).
    """

    id: UUID
    status: IdeaStatus
    owner_id: UUID | None = None
    submitted_by_id: UUID | None = None
    evaluation_closed: bool = False
    held_for: HoldReason | None = None
    my_evaluation: EvaluatorState | None = None
    researcher_id: UUID | None = None

    @property
    def awaiting_moderation(self) -> bool:
        """Held until a project admin approves it: only PA and PAd see it (c12), and
        nobody may change it (c19)."""
        return self.held_for is HoldReason.MODERATION

    @property
    def awaiting_verification(self) -> bool:
        """Held until the submitter confirms their address: nobody sees it (c12)."""
        return self.held_for is HoldReason.EMAIL_VERIFICATION

    @property
    def evaluation_open(self) -> bool:
        return self.status is not IdeaStatus.CLOSED and not self.evaluation_closed

    @property
    def pending_evaluator(self) -> bool:
        """The principal owes this idea an evaluation: blind (role matrix section 3)."""
        return self.my_evaluation in (EvaluatorState.INVITED, EvaluatorState.DRAFT)

    @classmethod
    def of(cls, idea: Idea, my_evaluation: EvaluatorState | None = None) -> IdeaFacts:
        return cls(
            id=idea.id,
            status=idea.status,
            owner_id=idea.owner_id,
            submitted_by_id=idea.submitted_by_id,
            evaluation_closed=idea.evaluation_closed_at is not None,
            held_for=idea.held_for,
            my_evaluation=my_evaluation,
            researcher_id=idea.researcher_id,
        )


@dataclass(frozen=True, slots=True)
class NamedResearcher:
    """Phase 8b: the person a request names as the idea's new researcher.

    ``eligible``: an active person (not a service account, the break-glass account or a
    deactivated user; an unknown id is not eligible): c23. ``role``: their effective role
    in the idea's project, read after their user row is locked (c25)."""

    eligible: bool
    role: ProjectRole | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Resource:
    """What a decision is about. Unset optional facts make their conditions pass or
    fail as documented on each field, so permission flags can be computed without a
    request body.

    * ``role``: the principal's **effective** project role (from the
      ``project_effective_roles`` view), ``None`` without one.
    * ``comment_author_id``: c2; unset fails (deny by default).
    * ``assignee_roles``: c4, the effective roles of the users being assigned (owner
      or evaluators). ``None`` = not an assignment request (permission flags).
      ``idea.volunteer_owner`` always checks the principal's own ``role``.
    * ``evaluator_to_remove``: selects the *remove* variant of ``evaluator.manage``
      (c16 instead of c4 and c6; contract section 3.5).
    * ``admins_after_change``: c11, admins the project would have after a membership
      change (count it from the view: :func:`app.authz.loaders.admin_count`). ``None``
      = not a membership change.
    * ``user_to_change``: selects the *access change* variant of
      ``platform.manage_users`` (changing a user's ``is_active`` or
      ``is_platform_admin``; contract-phase2 section 3.4): c17 and c18 apply.
    * ``platform_admins_after_change``: c18, the active platform admins (not the
      break-glass account) who would remain after demoting or deactivating one
      (:func:`app.authz.loaders.other_platform_admins`). ``None`` = the change takes
      no platform admin away.
    * ``assignee_service_account``: c4 for an **owner** assignment (``idea.assign_owner``):
      the user being made owner is a service account, which never owns an idea
      (contract-phase5 section 3.7). Evaluators may be service accounts.
    * ``issuing_api_key``: the request creates an API key (``api_key.manage_own``; Phase
      6 ``platform.manage_agents`` for an agent's key): c20 applies.
    * ``ai_available``: c10. ``token_valid``: c9 / c14.
    * ``public_submission_on``: the instance switch
      (``SOUNDINGS_PUBLIC_SUBMISSION_ENABLED``) for c8 and c9; unset fails.
    * ``token_covers_request``: c14, the unsubscribe token's scope covers what is
      asked (``all=true`` needs a token scoped to ``all``); unset fails.
    * ``researcher_named``: Phase 8b, c23 and c25 for ``idea.assign_researcher``: the
      person a request makes the idea's researcher. ``None`` = nobody new is named
      (permission flags, removing the researcher, the same researcher again).
    """

    project: ProjectFacts | None = None
    role: ProjectRole | None = None
    idea: IdeaFacts | None = None
    comment_author_id: UUID | None = None
    assignee_roles: tuple[ProjectRole | None, ...] | None = None
    assignee_service_account: bool = False
    evaluator_to_remove: UUID | None = None
    admins_after_change: int | None = None
    user_to_change: UUID | None = None
    platform_admins_after_change: int | None = None
    ai_available: bool = False
    token_valid: bool = False
    token_covers_request: bool = False
    public_submission_on: bool = False
    issuing_api_key: bool = False
    researcher_named: NamedResearcher | None = None

    def replace(self, **changes: object) -> Resource:
        return dataclasses.replace(self, **changes)  # type: ignore[arg-type]


NO_RESOURCE: Final = Resource()
"""For rules that are not about a project or idea (platform, self-service)."""


# --- Conditions (role matrix section 4) ------------------------------------------------
Test = Callable[["Principal | None", Resource, Rule], bool]


@dataclass(frozen=True, slots=True)
class Check:
    """One testable part of a condition, with the response when it fails."""

    condition: str
    status: int
    code: str
    test: Test


def _user_id(principal: Principal | None) -> UUID | None:
    return principal.user_id if principal is not None else None


def _idea(resource: Resource) -> IdeaFacts:
    if resource.idea is None:
        raise ValueError("this condition needs the idea's facts")
    return resource.idea


def _project(resource: Resource) -> ProjectFacts:
    if resource.project is None:
        raise ValueError("this condition needs the project's facts")
    return resource.project


def _assignees_eligible(principal: Principal | None, resource: Resource, rule: Rule) -> bool:
    if rule is Rule.IDEA_VOLUNTEER_OWNER:  # the principal assigns themselves (c21 first)
        return resource.role in ASSIGNABLE_ROLES
    if rule is Rule.IDEA_ASSIGN_OWNER and resource.assignee_service_account:
        return False  # an owner is a person (contract-phase5 section 3.7)
    return all(role in ASSIGNABLE_ROLES for role in resource.assignee_roles or ())


def _is_api_key(principal: Principal | None, _resource: Resource, _rule: Rule) -> bool:
    return principal is not None and principal.auth == "api_key"


def _has_mcp_scope(principal: Principal | None, _resource: Resource, _rule: Rule) -> bool:
    return principal is not None and principal.has_scope("mcp")


def _not_issuing_for_break_glass(principal: Principal | None, resource: Resource, _: Rule) -> bool:
    return not (
        resource.issuing_api_key and principal is not None and principal.user.is_break_glass
    )


def _proposal_available(resource: Resource) -> bool:
    """c7: Shortlisted or Proposal, or (Phase 8) Research while the project's research
    step comes before the proposal (so "Start proposal" is the next step there)."""
    status = _idea(resource).status
    if status in (IdeaStatus.SHORTLISTED, IdeaStatus.PROPOSAL):
        return True
    return (
        status is IdeaStatus.RESEARCH
        and _project(resource).research_step is ResearchStep.BEFORE_PROPOSAL
    )


def _a_person(principal: Principal | None, _resource: Resource, _rule: Rule) -> bool:
    return principal is not None and not principal.user.is_service_account


def _researcher_eligible(_p: Principal | None, resource: Resource, _rule: Rule) -> bool:
    """c23: whoever is named researcher is an active person (nobody named: passes)."""
    return resource.researcher_named is None or resource.researcher_named.eligible


def _researcher_in_private_project(_p: Principal | None, resource: Resource, _: Rule) -> bool:
    """c25 (product owner, review S1 (a)): the owner names, in a private project, only
    someone with a role there; an internal project's owner names anyone."""
    named = resource.researcher_named
    if named is None or named.role is not None:
        return True
    return _project(resource).visibility is ProjectVisibility.INTERNAL


CONDITIONS: Final[Mapping[str, tuple[Check, ...]]] = {
    "c1": (
        Check("c1", 403, "not_submitter", lambda p, r, _: _idea(r).submitted_by_id == _user_id(p)),
        Check("c1", 409, "idea_not_new", lambda p, r, _: _idea(r).status is IdeaStatus.NEW),
    ),
    "c2": (
        Check(
            "c2",
            403,
            "not_author",
            lambda p, r, _: p is not None and r.comment_author_id == p.user_id,
        ),
    ),
    "c3": (
        Check(
            "c3", 403, "volunteering_disabled", lambda p, r, _: _project(r).allow_volunteer_owners
        ),
    ),
    "c4": (Check("c4", 422, "assignee_not_eligible", _assignees_eligible),),
    "c5": (
        Check("c5", 409, "idea_closed", lambda p, r, _: _idea(r).status is not IdeaStatus.CLOSED),
    ),
    "c6": (Check("c6", 409, "evaluation_closed", lambda p, r, _: _idea(r).evaluation_open),),
    "c7": (Check("c7", 409, "proposal_not_available", lambda p, r, _: _proposal_available(r)),),
    # c8: the public form is available. Every part answers the same 404 as an unknown
    # project (contract-phase4 section 3.5), so nothing tells them apart.
    "c8": (
        Check("c8", 404, "not_found", lambda p, r, _: r.public_submission_on),
        Check("c8", 404, "not_found", lambda p, r, _: _project(r).public_submission_enabled),
        Check("c8", 404, "not_found", lambda p, r, _: not _project(r).archived),
        Check("c8", 404, "not_found", lambda p, r, _: not _project(r).slug_reserved),
    ),
    "c9": (
        Check("c9", 404, "not_found", lambda p, r, _: r.public_submission_on),
        Check("c9", 404, "not_found", lambda p, r, _: r.token_valid),
    ),
    "c10": (Check("c10", 409, "ai_unavailable", lambda p, r, _: r.ai_available),),
    "c11": (
        Check(
            "c11",
            409,
            "last_admin",
            lambda p, r, _: r.admins_after_change is None or r.admins_after_change >= 1,
        ),
    ),
    # c12 in the cells (Mem, Vwr, NMi): not held at all. Held for email confirmation is
    # 404 for every column, PA and PAd included (:func:`_locate`).
    "c12": (Check("c12", 404, "not_found", lambda p, r, _: _idea(r).held_for is None),),
    "c13": (Check("c13", 409, "idea_has_owner", lambda p, r, _: _idea(r).owner_id is None),),
    "c14": (
        Check("c14", 404, "not_found", lambda p, r, _: r.token_valid),
        Check("c14", 403, "insufficient_scope", lambda p, r, _: r.token_covers_request),
    ),
    "c15": (
        Check("c15", 401, "unauthorized", _is_api_key),
        Check("c15", 403, "insufficient_scope", _has_mcp_scope),
    ),
    "c16": (
        Check(
            "c16",
            403,
            "cannot_remove_self",
            lambda p, r, _: p is not None and r.evaluator_to_remove != p.user_id,
        ),
    ),
    "c17": (
        Check(
            "c17",
            403,
            "cannot_change_self",
            lambda p, r, _: p is not None and r.user_to_change != p.user_id,
        ),
    ),
    "c18": (
        Check(
            "c18",
            409,
            "last_platform_admin",
            lambda p, r, _: (
                r.platform_admins_after_change is None or r.platform_admins_after_change >= 1
            ),
        ),
    ),
    # Not in the role matrix: contract section 2, "in an archived project every
    # idea-level write returns 409 project_archived".
    "archived": (
        Check("archived", 409, "project_archived", lambda p, r, _: not _project(r).archived),
    ),
    # Not in the cells (role matrix section 4): every write on an idea held for
    # moderation but delete and moderate (:data:`FROZEN_WHILE_HELD`).
    "c19": (
        Check("c19", 409, "awaiting_moderation", lambda p, r, _: not _idea(r).awaiting_moderation),
    ),
    # Not in the cells (role matrix section 4): properties of the principal.
    "c20": (Check("c20", 403, "break_glass_account", _not_issuing_for_break_glass),),
    "c21": (Check("c21", 403, "forbidden", _a_person),),
    # Phase 8b: who may be named the idea's researcher.
    "c23": (Check("c23", 422, "researcher_not_eligible", _researcher_eligible),),
    "c25": (Check("c25", 403, "outside_researcher_needs_admin", _researcher_in_private_project),),
}

_PHASE: Final = {404: 0, 401: 1, 403: 1, 422: 2, 409: 3}
"""Check order within a grant: 404 conditions, then 403, 422 and 409 (section 2)."""


# --- The table -------------------------------------------------------------------------
class Column(StrEnum):
    """Principal columns of the role matrix (section 1)."""

    PA = "PA"
    PAD = "PAd"
    MEM = "Mem"
    VWR = "Vwr"
    NMI = "NMi"
    NMP = "NMp"
    PUB = "Pub"
    R = "R"
    """Phase 8b: the guest researcher (table L), never a column of tables A-K."""


MATRIX_COLUMNS: Final = tuple(column for column in Column if column is not Column.R)
"""The nine-column tables' principal columns (A-K)."""


class Scope(StrEnum):
    GLOBAL = "global"  # tables H and I, project.create: not about one project
    PROJECT = "project"  # needs project.view first
    IDEA = "idea"  # needs idea.view first
    PUBLIC = "public"  # public.submit, public.track, self.unsubscribe: tokens/settings


@dataclass(frozen=True, slots=True)
class Grant:
    """``Y`` / ``+``, possibly with conditions (``Y (c3, c13, c5)``)."""

    conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Refuse:
    """A ``401``, ``403`` or ``404`` cell."""

    status: int


Cell = Grant | Refuse


@dataclass(frozen=True, slots=True)
class RuleSpec:
    rule: Rule
    scope: Scope
    cells: Mapping[Column, Cell]
    owner: Grant | None = None
    evaluator: Grant | None = None
    guest: Cell | None = None
    """Phase 8b, column R's cell (table L); ``None`` = NMp's (every rule table L doesn't
    list: project-scoped, global, public)."""
    researcher: Grant | None = None
    """Phase 8b, the +Rsr overlay (table L); ``None`` = ``·``."""
    blind: bool = False
    idea_write: bool = False
    """Refused with 409 ``project_archived`` in an archived project (contract section 2)."""
    source: tuple[str, ...] = field(default=(), compare=False)
    """The row as written in the matrix (for the documentation test)."""

    @property
    def frozen_while_held(self) -> bool:
        """c19 applies: refused with 409 ``awaiting_moderation`` on an idea held for
        moderation (:data:`FROZEN_WHILE_HELD`)."""
        return self.rule in FROZEN_WHILE_HELD

    def cell(self, column: Column) -> Cell:
        if column is Column.R:
            return self.guest if self.guest is not None else self.cells[Column.NMP]
        return self.cells[column]

    def conditions_for(self, grant: Grant) -> tuple[Check, ...]:
        """The grant's checks in evaluation order: by phase, then as listed; the
        archived-project check leads the 409s, then c19. c20 (:data:`ISSUING_KEYS`) and
        c21 (:data:`PERSONS_ONLY`) are 403s that aren't written in the cells."""
        names = (
            (("archived",) if self.idea_write else ())
            + (("c19",) if self.frozen_while_held else ())
            + (("c20",) if self.rule in ISSUING_KEYS else ())
            + (("c21",) if self.rule in PERSONS_ONLY else ())
            + grant.conditions
        )
        checks = [check for name in names for check in CONDITIONS[name]]
        return tuple(sorted(checks, key=lambda check: _PHASE[check.status]))


def _cell(text: str) -> Cell:
    text = text.replace("✱", "").strip()
    if text in {"401", "403", "404"}:
        return Refuse(int(text))
    if text.startswith(("Y", "+")):
        rest = text[1:].strip()
        if not rest:
            return Grant()
        if not (rest.startswith("(") and rest.endswith(")")):
            raise ValueError(f"bad cell {text!r}")
        names = tuple(name.strip() for name in rest[1:-1].split(","))
        unknown = [name for name in names if name not in CONDITIONS]
        if unknown:
            raise ValueError(f"unknown conditions {unknown}")
        return Grant(names)
    raise ValueError(f"bad cell {text!r}")


def _overlay(text: str) -> Grant | None:
    text = text.strip()
    if text in {"·", "✱"}:
        return None
    grant = _cell(text)
    if not isinstance(grant, Grant) or not text.startswith("+"):
        raise ValueError(f"bad overlay cell {text!r}")
    return grant


def _row(
    rule: Rule,
    scope: Scope,
    *cells: str,
    owner: str = "·",
    evaluator: str = "·",
    idea_write: bool = False,
) -> RuleSpec:
    if len(cells) != len(MATRIX_COLUMNS):
        raise ValueError(f"{rule}: expected {len(MATRIX_COLUMNS)} cells")
    return RuleSpec(
        rule=rule,
        scope=scope,
        cells=dict(zip(MATRIX_COLUMNS, (_cell(cell) for cell in cells), strict=True)),
        owner=_overlay(owner),
        evaluator=_overlay(evaluator),
        blind=any("✱" in cell for cell in (*cells, owner, evaluator)),
        idea_write=idea_write,
        source=(*cells, owner, evaluator),
    )


FROZEN_WHILE_HELD: Final = frozenset(
    {
        Rule.IDEA_EDIT_OWN,
        Rule.IDEA_EDIT_ANY,
        Rule.COMMENT_CREATE,
        Rule.COMMENT_EDIT_OWN,
        Rule.COMMENT_DELETE_ANY,
        Rule.IDEA_VOTE,
        Rule.IDEA_WATCH,
        Rule.IDEA_VOLUNTEER_OWNER,
        Rule.IDEA_RELEASE_OWNER,
        Rule.IDEA_ASSIGN_OWNER,
        Rule.EVALUATOR_MANAGE,
        Rule.IDEA_SET_DUE_DATE,
        Rule.EVALUATION_SUBMIT_OWN,
        Rule.EVALUATION_CLOSE,
        Rule.EVALUATION_INCLUDE_AI,
        Rule.IDEA_CHANGE_STATUS,
        Rule.PROPOSAL_WRITE,
        Rule.PROPOSAL_COMMENT,
        Rule.PROPOSAL_SUGGEST_SECTION,
        Rule.AI_REQUEST_EVALUATION,
        Rule.AI_RESEARCH,
        Rule.AI_DRAFT_SECTION,
        Rule.AI_DELETE_NOTE,
        Rule.IDEA_ANSWER_RESEARCH,
        Rule.IDEA_RESEARCH_OVERRIDE,
        Rule.IDEA_ASSIGN_RESEARCHER,
        Rule.IDEA_RELEASE_RESEARCHER,
    }
)
"""c19 (contract-phase4 section 3.6): every idea write on an idea held for moderation
is 409 ``awaiting_moderation`` (watching included), except ``idea.delete``,
``idea.moderate`` (approve, reject) and ``public.erase_submitter``, so admins see a
read-only idea with Approve and Reject until they decide."""

ISSUING_KEYS: Final = frozenset({Rule.API_KEY_MANAGE_OWN, Rule.PLATFORM_MANAGE_AGENTS})
"""c20: when the request creates an API key (``Resource.issuing_api_key``), the
break-glass account is refused (403 ``break_glass_account``): a key would outlive the
emergency (contract-phase5 section 3.1). Listing and revoking aren't affected."""

PERSONS_ONLY: Final = frozenset({Rule.IDEA_VOLUNTEER_OWNER})
"""c21: a service account (an AI agent) never volunteers as owner (403 ``forbidden``;
contract-phase5 section 3.7). ``idea.assign_owner`` refuses one through c4."""

_G, _P, _I, _U = Scope.GLOBAL, Scope.PROJECT, Scope.IDEA, Scope.PUBLIC
_W = True  # idea_write: 409 project_archived in archived projects

# fmt: off
_ROWS: Final[tuple[RuleSpec, ...]] = (
    # A. Projects and ideas     PA               PAd           Mem              Vwr      NMi      NMp    Pub
    _row(Rule.PROJECT_VIEW, _P,  "Y",             "Y",          "Y",             "Y",     "Y",     "404", "401"),
    _row(Rule.PROJECT_CREATE, _G, "Y",            "403",        "403",           "403",   "403",   "403", "401"),
    _row(Rule.IDEA_VIEW, _I,     "Y",             "Y",          "Y (c12)",       "Y (c12)", "Y (c12)", "404", "401"),
    _row(Rule.IDEA_CREATE, _P,   "Y",             "Y",          "Y",             "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.IDEA_EDIT_OWN, _I, "Y",             "Y",          "Y (c1)",        "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.IDEA_EDIT_ANY, _I, "Y",             "Y",          "403",           "403",   "403",   "404", "401", owner="+ (c5)", idea_write=_W),
    _row(Rule.IDEA_DELETE, _I,   "Y",             "Y",          "403",           "403",   "403",   "404", "401", idea_write=_W),
    # B. Collaboration
    _row(Rule.COMMENT_CREATE, _I, "Y",            "Y",          "Y",             "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.COMMENT_EDIT_OWN, _I, "Y (c2)",     "Y (c2)",     "Y (c2)",        "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.COMMENT_DELETE_ANY, _I, "Y",        "Y",          "403",           "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.IDEA_VOTE, _I,     "Y",             "Y",          "Y",             "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.IDEA_WATCH, _I,    "Y",             "Y",          "Y",             "Y",     "Y",     "404", "401"),
    # C. Ownership and evaluation management
    _row(Rule.IDEA_VOLUNTEER_OWNER, _I, "Y (c4, c13, c5)", "Y (c13, c5)", "Y (c3, c13, c5)", "403", "403", "404", "401", idea_write=_W),
    _row(Rule.IDEA_RELEASE_OWNER, _I, "Y",        "Y",          "403",           "403",   "403",   "404", "401", owner="+", idea_write=_W),
    _row(Rule.IDEA_ASSIGN_OWNER, _I, "Y (c4)",    "Y (c4)",     "403",           "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.EVALUATOR_MANAGE, _I, "Y (c4, c6)", "Y (c4, c6)", "403",           "403",   "403",   "404", "401", owner="+ (c4, c6)", idea_write=_W),
    _row(Rule.IDEA_SET_DUE_DATE, _I, "Y (c6)",    "Y (c6)",     "403",           "403",   "403",   "404", "401", owner="+ (c6)", idea_write=_W),
    _row(Rule.EVALUATION_SUBMIT_OWN, _I, "403",   "403",        "403",           "403",   "403",   "404", "401", evaluator="+ (c6)", idea_write=_W),
    _row(Rule.EVALUATION_CLOSE, _I, "Y (c5)",     "Y (c5)",     "403",           "403",   "403",   "404", "401", owner="+ (c5)", idea_write=_W),
    _row(Rule.EVALUATION_INCLUDE_AI, _I, "Y",     "Y",          "403",           "403",   "403",   "404", "401", owner="+", idea_write=_W),
    _row(Rule.IDEA_CHANGE_STATUS, _I, "Y",        "Y",          "403",           "403",   "403",   "404", "401", owner="+", idea_write=_W),
    _row(Rule.IDEA_MODERATE, _I, "Y",             "Y",          "404",           "404",   "404",   "404", "401", idea_write=_W),
    # D. Evaluation visibility (blind evaluation)
    _row(Rule.EVALUATION_VIEW_OWN, _I, "Y",       "Y",          "Y",             "Y",     "Y",     "404", "401"),
    _row(Rule.EVALUATION_VIEW_OTHERS, _I, "Y ✱",  "Y ✱",        "Y ✱",           "Y ✱",   "Y ✱",   "404", "401", evaluator="✱"),
    _row(Rule.SCORE_VIEW_AGGREGATE, _I, "Y ✱",    "Y ✱",        "Y ✱",           "Y ✱",   "Y ✱",   "404", "401", evaluator="✱"),
    # E. Proposals
    _row(Rule.PROPOSAL_VIEW, _I, "Y",             "Y",          "Y",             "Y",     "Y",     "404", "401"),
    _row(Rule.PROPOSAL_WRITE, _I, "Y (c7)",       "Y (c7)",     "403",           "403",   "403",   "404", "401", owner="+ (c7)", idea_write=_W),
    _row(Rule.PROPOSAL_COMMENT, _I, "Y",          "Y",          "Y",             "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.PROPOSAL_SUGGEST_SECTION, _I, "Y (c7)", "Y (c7)", "Y (c7)",        "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.PROPOSAL_EXPORT, _I, "Y",           "Y",          "Y",             "Y",     "Y",     "404", "401"),
    # F. Project administration
    _row(Rule.PROJECT_MANAGE_MEMBERS, _P, "Y (c11)", "Y (c11)", "403",           "403",   "403",   "404", "401"),
    _row(Rule.PROJECT_EDIT_RUBRIC, _P, "Y",       "Y",          "403",           "403",   "403",   "404", "401"),
    _row(Rule.PROJECT_RENAME_STATUS_LABELS, _P, "Y", "Y",       "403",           "403",   "403",   "404", "401"),
    _row(Rule.PROJECT_EDIT_SETTINGS, _P, "Y",     "Y",          "403",           "403",   "403",   "404", "401"),
    _row(Rule.PUBLIC_ERASE_SUBMITTER, _I, "Y",    "Y",          "403",           "403",   "403",   "404", "401"),
    _row(Rule.PROJECT_EDIT_PROPOSAL_TEMPLATE, _P, "Y", "Y",     "403",           "403",   "403",   "404", "401"),
    _row(Rule.PROJECT_EDIT_RESEARCH, _P, "Y",     "Y",          "403",           "403",   "403",   "404", "401"),
    # G. Public submission
    _row(Rule.PUBLIC_SUBMIT, _U, "Y (c8)",        "Y (c8)",     "Y (c8)",        "Y (c8)", "Y (c8)", "Y (c8)", "Y (c8)"),
    _row(Rule.PUBLIC_TRACK, _U,  "Y (c9)",        "Y (c9)",     "Y (c9)",        "Y (c9)", "Y (c9)", "Y (c9)", "Y (c9)"),
    # H. Platform administration
    _row(Rule.PLATFORM_MANAGE_USERS, _G, "Y",     "403",        "403",           "403",   "403",   "403", "401"),
    _row(Rule.PLATFORM_MANAGE_GROUPS, _G, "Y",    "403",        "403",           "403",   "403",   "403", "401"),
    _row(Rule.PLATFORM_CONFIGURE_SSO, _G, "Y",    "403",        "403",           "403",   "403",   "403", "401"),
    _row(Rule.PLATFORM_CONFIGURE_EMAIL, _G, "Y",  "403",        "403",           "403",   "403",   "403", "401"),
    _row(Rule.PLATFORM_EDIT_BRANDING, _G, "Y",    "403",        "403",           "403",   "403",   "403", "401"),
    _row(Rule.PLATFORM_MANAGE_AGENTS, _G, "Y",    "403",        "403",           "403",   "403",   "403", "401"),
    _row(Rule.PLATFORM_VIEW_AUDIT_LOG, _G, "Y",   "403",        "403",           "403",   "403",   "403", "401"),
    _row(Rule.API_KEY_MANAGE_ANY, _G, "Y",        "403",        "403",           "403",   "403",   "403", "401"),
    # I. Self-service, API keys and MCP
    _row(Rule.SELF_MANAGE_PROFILE, _G, "Y",       "Y",          "Y",             "Y",     "Y",     "Y",   "401"),
    _row(Rule.SELF_UNSUBSCRIBE, _U, "Y (c14)",    "Y (c14)",    "Y (c14)",       "Y (c14)", "Y (c14)", "Y (c14)", "Y (c14)"),
    _row(Rule.USER_SEARCH, _G,   "Y",             "Y",          "Y",             "Y",     "Y",     "Y",   "401"),
    _row(Rule.API_KEY_MANAGE_OWN, _G, "Y",        "Y",          "Y",             "Y",     "Y",     "Y",   "401"),
    _row(Rule.MCP_CONNECT, _G,   "Y (c15)",       "Y (c15)",    "Y (c15)",       "Y (c15)", "Y (c15)", "Y (c15)", "401"),
    # J. AI assistance (kagent)
    _row(Rule.AI_REQUEST_EVALUATION, _I, "Y (c6, c10)", "Y (c6, c10)", "403",    "403",   "403",   "404", "401", owner="+ (c6, c10)", idea_write=_W),
    _row(Rule.AI_RESEARCH, _I,   "Y (c5, c10)",   "Y (c5, c10)", "403",          "403",   "403",   "404", "401", owner="+ (c5, c10)", idea_write=_W),
    _row(Rule.AI_DRAFT_SECTION, _I, "Y (c7, c10)", "Y (c7, c10)", "403",         "403",   "403",   "404", "401", owner="+ (c7, c10)", idea_write=_W),
    _row(Rule.AI_CANCEL_RUN, _I, "Y",             "Y",          "403",           "403",   "403",   "404", "401", owner="+"),
    _row(Rule.AI_DELETE_NOTE, _I, "Y",            "Y",          "403",           "403",   "403",   "404", "401", owner="+", idea_write=_W),
    # K. The research step (Phase 8)
    _row(Rule.IDEA_ANSWER_RESEARCH, _I, "Y (c5)", "Y (c5)",     "403",           "403",   "403",   "404", "401", owner="+ (c5)", idea_write=_W),
    _row(Rule.IDEA_RESEARCH_OVERRIDE, _I, "Y",    "Y",          "403",           "403",   "403",   "404", "401", idea_write=_W),
    _row(Rule.IDEA_ASSIGN_RESEARCHER, _I, "Y (c5, c23)", "Y (c5, c23)", "403",   "403",   "403",   "404", "401", owner="+ (c5, c23, c25)", idea_write=_W),
    _row(Rule.IDEA_RELEASE_RESEARCHER, _I, "403", "403",        "403",           "403",   "403",   "404", "401", idea_write=_W),
)

# L. Researcher access (Phase 8b): column R's cell and the +Rsr overlay of every
# idea-scoped rule. Rules not listed: R = NMp's cell, +Rsr = "·".
#                                         R          +Rsr
TABLE_L: Final[Mapping[Rule, tuple[str, str]]] = {
    Rule.IDEA_VIEW:                      ("Y (c12)", "·"),
    Rule.IDEA_EDIT_OWN:                  ("403",     "·"),
    Rule.IDEA_EDIT_ANY:                  ("403",     "·"),
    Rule.IDEA_DELETE:                    ("403",     "·"),
    Rule.COMMENT_CREATE:                 ("403",     "+"),
    Rule.COMMENT_EDIT_OWN:               ("403",     "+ (c2)"),
    Rule.COMMENT_DELETE_ANY:             ("403",     "·"),
    Rule.IDEA_VOTE:                      ("403",     "·"),
    Rule.IDEA_WATCH:                     ("Y",       "·"),
    Rule.IDEA_VOLUNTEER_OWNER:           ("403",     "·"),
    Rule.IDEA_RELEASE_OWNER:             ("403",     "·"),
    Rule.IDEA_ASSIGN_OWNER:              ("403",     "·"),
    Rule.EVALUATOR_MANAGE:               ("404",     "·"),
    Rule.IDEA_SET_DUE_DATE:              ("404",     "·"),
    Rule.EVALUATION_SUBMIT_OWN:          ("404",     "·"),
    Rule.EVALUATION_CLOSE:               ("404",     "·"),
    Rule.EVALUATION_INCLUDE_AI:          ("404",     "·"),
    Rule.IDEA_CHANGE_STATUS:             ("403",     "·"),
    Rule.IDEA_MODERATE:                  ("404",     "·"),
    Rule.EVALUATION_VIEW_OWN:            ("404",     "·"),
    Rule.EVALUATION_VIEW_OTHERS:         ("404",     "·"),
    Rule.SCORE_VIEW_AGGREGATE:           ("404",     "·"),
    Rule.PROPOSAL_VIEW:                  ("404",     "·"),
    Rule.PROPOSAL_WRITE:                 ("404",     "·"),
    Rule.PROPOSAL_COMMENT:               ("404",     "·"),
    Rule.PROPOSAL_SUGGEST_SECTION:       ("404",     "·"),
    Rule.PROPOSAL_EXPORT:                ("404",     "·"),
    Rule.PUBLIC_ERASE_SUBMITTER:         ("404",     "·"),
    Rule.AI_REQUEST_EVALUATION:          ("404",     "·"),
    Rule.AI_RESEARCH:                    ("404",     "·"),
    Rule.AI_DRAFT_SECTION:               ("404",     "·"),
    Rule.AI_CANCEL_RUN:                  ("404",     "·"),
    Rule.AI_DELETE_NOTE:                 ("403",     "·"),
    Rule.IDEA_ANSWER_RESEARCH:           ("403",     "+"),
    Rule.IDEA_RESEARCH_OVERRIDE:         ("403",     "·"),
    Rule.IDEA_ASSIGN_RESEARCHER:         ("403",     "·"),
    Rule.IDEA_RELEASE_RESEARCHER:        ("403",     "+"),
}
# fmt: on


def _with_table_l(spec: RuleSpec) -> RuleSpec:
    row = TABLE_L.get(spec.rule)
    if row is None:
        return spec
    if spec.scope is not Scope.IDEA:
        raise ValueError(f"{spec.rule}: table L lists idea-scoped rules only")
    guest, researcher = row
    return dataclasses.replace(spec, guest=_cell(guest), researcher=_overlay(researcher))


POLICY: Final[Mapping[Rule, RuleSpec]] = {spec.rule: _with_table_l(spec) for spec in _ROWS}
"""Every rule of the role matrix. Anything else is denied."""

EVALUATOR_REMOVE: Final = dataclasses.replace(
    POLICY[Rule.EVALUATOR_MANAGE],
    cells={
        column: Grant(("c16",)) if isinstance(cell, Grant) else cell
        for column, cell in POLICY[Rule.EVALUATOR_MANAGE].cells.items()
    },
    owner=Grant(("c16",)),
    source=(),
)
"""``evaluator.manage`` when removing an evaluator (contract section 3.5): c16 instead
of c4 and c6, so a pending evaluator can be released from blindness even after
evaluation closed, but never by removing themselves."""

MANAGE_USER_ACCESS: Final = dataclasses.replace(
    POLICY[Rule.PLATFORM_MANAGE_USERS],
    cells={
        column: Grant(("c17", "c18")) if isinstance(cell, Grant) else cell
        for column, cell in POLICY[Rule.PLATFORM_MANAGE_USERS].cells.items()
    },
    source=(),
)
"""``platform.manage_users`` when changing a user's ``is_active`` or
``is_platform_admin`` (contract-phase2 section 3.4, role matrix table H notes): c17,
not yourself (403 ``cannot_change_self``), then c18, another active platform admin
remains (409 ``last_platform_admin``)."""


# --- Decisions -------------------------------------------------------------------------
_DETAILS: Final[Mapping[str, str]] = {
    "unauthorized": "Sign in to continue.",
    "not_found": "Not found.",
    "forbidden": "You don't have permission to do that.",
    "insufficient_scope": "This API key's scopes don't allow that.",
    "not_submitter": "Only the person who submitted this idea can edit it.",
    "not_author": "You can only change your own comments.",
    "volunteering_disabled": "This project doesn't let members volunteer as owner.",
    "cannot_remove_self": "You can't remove yourself as an evaluator.",
    "assignee_not_eligible": "Owners and evaluators need the member or admin role here.",
    "idea_not_new": "The idea can only be edited by its submitter while it is New.",
    "idea_closed": "The idea is closed.",
    "evaluation_closed": "Evaluation is closed for this idea.",
    "proposal_not_available": "The idea needs to be shortlisted or in proposal first.",
    "ai_unavailable": "AI assistance isn't available.",
    "last_admin": "A project needs at least one admin.",
    "cannot_change_self": "You can't deactivate yourself or change your own platform-admin role.",
    "last_platform_admin": "Soundings needs at least one other active platform admin.",
    "idea_has_owner": "The idea already has an owner.",
    "project_archived": "The project is archived, so its ideas are read-only.",
    "awaiting_moderation": "This idea is waiting for review: approve it first.",
    "break_glass_account": (
        "The break-glass account can't create API keys: a key would outlive the emergency."
    ),
    "researcher_not_eligible": "Only an active person can do the research.",
    "outside_researcher_needs_admin": (
        "Only a project admin can ask someone outside this project to research it."
    ),
}


@dataclass(frozen=True, slots=True)
class Decision:
    """The answer for one rule. ``status``/``code`` describe the denial."""

    rule: Rule
    allowed: bool
    status: int = 200
    code: str = "ok"
    condition: str | None = None
    """The failed condition (``c6``, ``archived``), or ``None``."""
    hidden: bool = False
    """Denied only by blind evaluation: hide the data, don't fail the request."""

    def __bool__(self) -> bool:
        return self.allowed

    def problem(self) -> ProblemError:
        """The problem to raise for this denial."""
        if self.allowed:
            raise ValueError("an allowed decision has no problem")
        if self.status == 404:  # the same answer whether missing or hidden
            return not_found()
        return ProblemError(self.status, self.code, detail=_DETAILS.get(self.code))

    @property
    def _rank(self) -> tuple[int, int]:
        # How far the evaluation got: a condition failure beats a missing grant.
        return (_PHASE.get(self.status, 0), 0 if self.condition is None else 1)


def _allow(rule: Rule) -> Decision:
    return Decision(rule, True)


def _deny(
    rule: Rule, status: int, code: str | None = None, condition: str | None = None
) -> Decision:
    default = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(status, "forbidden")
    return Decision(rule, False, status, code or default, condition)


def not_found() -> ProblemError:
    """The 404 for anything missing or hidden: identical either way, so nothing leaks."""
    return NotFoundProblem(_DETAILS["not_found"])


def best_decision(decisions: Iterable[Decision]) -> Decision:
    """An allowed decision if any; else the denial that got furthest (see module doc)."""
    denials: list[Decision] = []
    for decision in decisions:
        if decision.allowed:
            return decision
        denials.append(decision)
    if not denials:
        raise ValueError("no decisions")
    return max(denials, key=lambda decision: decision._rank)  # first of equals wins


def researcher_live(principal: Principal | None, resource: Resource) -> bool:
    """c24: the principal is the idea's assigned researcher and the assignment is live
    (the project's research step on, the idea not closed, the project not archived), and
    a person (c23 holds for whoever is assigned; checked again here; a deactivated user
    can't sign in, holds no assignment and is never a recipient)."""
    idea, project = resource.idea, resource.project
    return (
        principal is not None
        and idea is not None
        and project is not None
        and idea.researcher_id is not None
        and idea.researcher_id == principal.user_id
        and not principal.user.is_service_account
        and not principal.user.is_break_glass
        and project.research_step is not ResearchStep.OFF
        and idea.status is not IdeaStatus.CLOSED
        and not project.archived
    )


def _column(principal: Principal, spec: RuleSpec, resource: Resource) -> Column:
    if principal.is_platform_admin:
        return Column.PA
    if spec.scope is Scope.GLOBAL:
        return Column.MEM  # H and I: every signed-in non-platform-admin column is equal
    match resource.role:
        case ProjectRole.ADMIN:
            return Column.PAD
        case ProjectRole.MEMBER:
            return Column.MEM
        case ProjectRole.VIEWER:
            return Column.VWR
    if principal.user.is_service_account:
        # A service account needs a real project role (role matrix section 1,
        # contract-phase5 section 3.7): never the internal-project non-member.
        return Column.NMP
    if _project(resource).visibility is ProjectVisibility.INTERNAL:
        return Column.NMI
    if spec.scope is Scope.IDEA and researcher_live(principal, resource):
        return Column.R  # Phase 8b: that one idea, as its guest researcher (table L)
    return Column.NMP


def _evaluate_grant(
    principal: Principal | None, spec: RuleSpec, grant: Grant, resource: Resource
) -> Decision:
    for check in spec.conditions_for(grant):
        if not check.test(principal, resource, spec.rule):
            return _deny(spec.rule, check.status, check.code, check.condition)
    return _allow(spec.rule)


def _locate(principal: Principal, spec: RuleSpec, resource: Resource) -> Column | Decision:
    """Steps 1-2 for a signed-in principal: their column, or the 404 that hides the
    resource (key restriction, a 404 cell, or the implied view rule failing).

    The implied ``project.view`` / ``idea.view`` is the owner's, not a scope check:
    the rule's own scope is checked next (every key that can change something has
    ``read`` anyway). :func:`require_view` adds the ``read`` scope for routes that
    load what they read.
    """
    if spec.scope in (Scope.PROJECT, Scope.IDEA):
        project = _project(resource)
        if not principal.may_access_project(project.id):
            return _deny(spec.rule, 404)  # API key restricted to other projects
        if spec.scope is Scope.IDEA and _idea(resource).awaiting_verification:
            # c12: not a submission until its address is confirmed; 404 for everyone.
            return _deny(spec.rule, 404, condition="c12")
    column = _column(principal, spec, resource)
    if column is Column.R and guest_access(principal.operation) is GuestAccess.HIDDEN:
        # Phase 8b: the request's operation isn't part of the guest's view (deny by
        # default; app.authz.guest), whatever rule it checks.
        return _deny(spec.rule, 404, condition="guest_route")
    cell = spec.cell(column)
    if isinstance(cell, Refuse) and cell.status in (401, 404):
        return _deny(spec.rule, cell.status)
    if spec.scope is not Scope.GLOBAL:
        view = POLICY[Rule.IDEA_VIEW if spec.scope is Scope.IDEA else Rule.PROJECT_VIEW]
        view_cell = view.cell(column)
        if not isinstance(view_cell, Grant):
            return _deny(spec.rule, 404)
        seen = _evaluate_grant(principal, view, view_cell, resource)
        if not seen.allowed:
            return _deny(spec.rule, 404, condition=seen.condition)
    return column


def authorize(
    principal: Principal | None, rule: Rule, resource: Resource = NO_RESOURCE
) -> Decision:
    """May ``principal`` (``None`` = anonymous) do ``rule`` on ``resource``?"""
    spec = POLICY.get(rule)
    if spec is None:
        return _deny(rule, 403)  # deny by default
    if rule is Rule.EVALUATOR_MANAGE and resource.evaluator_to_remove is not None:
        spec = EVALUATOR_REMOVE
    elif rule is Rule.PLATFORM_MANAGE_USERS and resource.user_to_change is not None:
        spec = MANAGE_USER_ACCESS

    if spec.scope is Scope.PUBLIC:
        # Decided by a token or project setting; identical for every column.
        cell = spec.cells[Column.PUB]
        assert isinstance(cell, Grant)  # noqa: S101 - table invariant, tested
        return _evaluate_grant(principal, spec, cell, resource)
    if principal is None:
        return _deny(rule, 401)
    located = _locate(principal, spec, resource)
    if isinstance(located, Decision):
        return located
    cell = spec.cell(located)

    # 403: the API key's scopes (session-only rules have no scope at all).
    if principal.auth == "api_key":
        scope = RULE_SCOPES.get(rule)
        if scope is None or not principal.has_scope(scope):
            return _deny(rule, 403, "insufficient_scope")

    grants: list[Grant] = [cell] if isinstance(cell, Grant) else []
    idea = resource.idea
    if idea is not None and resource.role in ASSIGNABLE_ROLES:
        # Overlays count only while the user holds member or admin (section 1).
        if spec.owner is not None and idea.owner_id == principal.user_id:
            grants.append(spec.owner)
        if spec.evaluator is not None and idea.my_evaluation is not None:
            grants.append(spec.evaluator)
    if spec.researcher is not None and researcher_live(principal, resource):
        # +Rsr counts whatever the role, or without one (Phase 8b, table L).
        grants.append(spec.researcher)
    if not grants:
        return _deny(rule, 403)

    decision = best_decision(_evaluate_grant(principal, spec, grant, resource) for grant in grants)
    if (
        decision.allowed
        and spec.blind
        and idea is not None
        and (idea.pending_evaluator or principal.user.is_service_account)
    ):
        # ✱: no role lifts blind evaluation, and it applies to demoted evaluators too.
        # Rule 9: an AI agent's service account is blind on every idea, before and after
        # it submits, so nothing it writes can carry others' scores to anyone.
        return Decision(rule, False, 403, "forbidden", condition="blind", hidden=True)
    return decision


def require_view(principal: Principal | None, resource: Resource) -> None:
    """The view rule (``idea.view`` when the resource has an idea, else
    ``project.view``) as routes use it to load what they read or change: 401, 404
    (hidden, or outside a key's projects), then 403 ``insufficient_scope`` for a key
    without ``read`` (a key with only ``mcp`` reads nothing through REST; every key
    that can change something has ``read``, contract-phase5 section 3.1). Check the
    actual rule afterwards."""
    if principal is None:
        raise _deny(Rule.PROJECT_VIEW, 401).problem()
    view = POLICY[Rule.IDEA_VIEW if resource.idea is not None else Rule.PROJECT_VIEW]
    located = _locate(principal, view, resource)
    if isinstance(located, Decision):
        raise located.problem()
    if principal.auth == "api_key" and not principal.has_scope("read"):
        raise _deny(view.rule, 403, "insufficient_scope").problem()


def can(principal: Principal | None, rule: Rule, resource: Resource = NO_RESOURCE) -> bool:
    return authorize(principal, rule, resource).allowed


def require(principal: Principal | None, rule: Rule, resource: Resource = NO_RESOURCE) -> None:
    """Raise the rule's problem (401/404/403/422/409) unless allowed."""
    decision = authorize(principal, rule, resource)
    if not decision.allowed:
        raise decision.problem()


def require_any(
    principal: Principal | None, rules: Iterable[Rule], resource: Resource = NO_RESOURCE
) -> Rule:
    """Pass if any rule allows (e.g. ``idea.edit_own`` or ``idea.edit_any``); return it.

    Otherwise raise the denial that got furthest, so the submitter of an idea that
    left ``new`` gets ``409 idea_not_new`` and a member gets ``403 not_submitter``.
    """
    decision = best_decision(authorize(principal, rule, resource) for rule in rules)
    if not decision.allowed:
        raise decision.problem()
    return decision.rule


# --- Principal traits (role matrix section 1a) ---------------------------------------------
# Decisions that follow from *who* the principal is rather than from a rule's cells. They
# live here, named, so nothing outside the policy branches on roles or account kinds
# (ADR 0010; security review P7 N4).
def is_agent(principal: Principal | None) -> bool:
    """``principal.agent``: an AI agent's service account (c21, c22, rule 9)."""
    return principal is not None and principal.user.is_service_account


def sees_email_trouble(principal: Principal | None) -> bool:
    """``principal.sees_email_trouble``: the "Email isn't being delivered" banner goes to
    whoever may configure email (``platform.configure_email``)."""
    return can(principal, Rule.PLATFORM_CONFIGURE_EMAIL)


def may_cite_sources(principal: Principal | None) -> bool:
    """``evaluation.cite_sources``: only an AI evaluator attaches cited sources to its
    scores (contract-phase6 §4); a person's sources are 422."""
    return is_agent(principal)


def counted_by_default(principal: Principal | None) -> bool:
    """``evaluation.counted_by_default``: a first submission counts in the aggregate,
    except an AI agent's, which waits for ``evaluation.include_ai`` (section 3 rule 10)."""
    return not is_agent(principal)


def writes_as_ai(principal: Principal | None) -> bool:
    """``proposal.suggest_as_ai``: an agent's proposal suggestions are labelled AI
    whatever channel they came through; its Markdown and comments lose invisible and
    direction characters before validation (Phase 6 review M2)."""
    return is_agent(principal)


def searches_co_members_only(principal: Principal | None) -> bool:
    """``user.search`` narrowed: an agent finds only people who share a project with it
    (Phase 5 decision), a person finds everyone active."""
    return is_agent(principal)
