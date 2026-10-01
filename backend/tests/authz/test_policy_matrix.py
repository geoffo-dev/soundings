"""docs/role-matrix.md, row by row: every rule x principal column x condition.

``MATRIX`` is copied by hand from the role matrix (and checked against the markdown,
so a doc change fails here until the policy follows). For every rule and column the
principal is put in a state where every condition holds and the outcome must match
the cell; then each listed condition is broken on its own and the response must be
the one section 4 documents for it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest

from app.authz import POLICY, Decision, IdeaFacts, ProjectFacts, Resource, Rule, authorize
from app.domain.principal import Principal
from app.models.enums import (
    EvaluatorState,
    HoldReason,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
)
from app.models.user import User

ROLE_MATRIX = Path(__file__).resolve().parents[3] / "docs" / "role-matrix.md"

COLUMNS = ("PA", "PAd", "Mem", "Vwr", "NMi", "NMp", "Pub", "+Own", "+Evl")

# fmt: off
MATRIX: dict[str, tuple[str, ...]] = {
    # rule: PA, PAd, Mem, Vwr, NMi, NMp, Pub, +Own, +Evl
    # A. Projects and ideas
    "project.view": ("Y", "Y", "Y", "Y", "Y", "404", "401", "·", "·"),
    "project.create": ("Y", "403", "403", "403", "403", "403", "401", "·", "·"),
    "idea.view": ("Y", "Y", "Y (c12)", "Y (c12)", "Y (c12)", "404", "401", "·", "·"),
    "idea.create": ("Y", "Y", "Y", "403", "403", "404", "401", "·", "·"),
    "idea.edit_own": ("Y", "Y", "Y (c1)", "403", "403", "404", "401", "·", "·"),
    "idea.edit_any": ("Y", "Y", "403", "403", "403", "404", "401", "+ (c5)", "·"),
    "idea.delete": ("Y", "Y", "403", "403", "403", "404", "401", "·", "·"),
    # B. Collaboration
    "comment.create": ("Y", "Y", "Y", "403", "403", "404", "401", "·", "·"),
    "comment.edit_own": ("Y (c2)", "Y (c2)", "Y (c2)", "403", "403", "404", "401", "·", "·"),
    "comment.delete_any": ("Y", "Y", "403", "403", "403", "404", "401", "·", "·"),
    "idea.vote": ("Y", "Y", "Y", "403", "403", "404", "401", "·", "·"),
    "idea.watch": ("Y", "Y", "Y", "Y", "Y", "404", "401", "·", "·"),
    # C. Ownership and evaluation management
    "idea.volunteer_owner": ("Y (c4, c13, c5)", "Y (c13, c5)", "Y (c3, c13, c5)", "403", "403", "404", "401", "·", "·"),
    "idea.release_owner": ("Y", "Y", "403", "403", "403", "404", "401", "+", "·"),
    "idea.assign_owner": ("Y (c4)", "Y (c4)", "403", "403", "403", "404", "401", "·", "·"),
    "evaluator.manage": ("Y (c4, c6)", "Y (c4, c6)", "403", "403", "403", "404", "401", "+ (c4, c6)", "·"),
    "idea.set_due_date": ("Y (c6)", "Y (c6)", "403", "403", "403", "404", "401", "+ (c6)", "·"),
    "evaluation.submit_own": ("403", "403", "403", "403", "403", "404", "401", "·", "+ (c6)"),
    "evaluation.close": ("Y (c5)", "Y (c5)", "403", "403", "403", "404", "401", "+ (c5)", "·"),
    "evaluation.include_ai": ("Y", "Y", "403", "403", "403", "404", "401", "+", "·"),
    "idea.change_status": ("Y", "Y", "403", "403", "403", "404", "401", "+", "·"),
    "idea.moderate": ("Y", "Y", "404", "404", "404", "404", "401", "·", "·"),
    # D. Evaluation visibility
    "evaluation.view_own": ("Y", "Y", "Y", "Y", "Y", "404", "401", "·", "·"),
    "evaluation.view_others": ("Y ✱", "Y ✱", "Y ✱", "Y ✱", "Y ✱", "404", "401", "·", "✱"),
    "score.view_aggregate": ("Y ✱", "Y ✱", "Y ✱", "Y ✱", "Y ✱", "404", "401", "·", "✱"),
    # E. Proposals
    "proposal.view": ("Y", "Y", "Y", "Y", "Y", "404", "401", "·", "·"),
    "proposal.write": ("Y (c7)", "Y (c7)", "403", "403", "403", "404", "401", "+ (c7)", "·"),
    "proposal.comment": ("Y", "Y", "Y", "403", "403", "404", "401", "·", "·"),
    "proposal.suggest_section": ("Y (c7)", "Y (c7)", "Y (c7)", "403", "403", "404", "401", "·", "·"),
    "proposal.export": ("Y", "Y", "Y", "Y", "Y", "404", "401", "·", "·"),
    # F. Project administration
    "project.manage_members": ("Y (c11)", "Y (c11)", "403", "403", "403", "404", "401", "·", "·"),
    "project.edit_rubric": ("Y", "Y", "403", "403", "403", "404", "401", "·", "·"),
    "project.rename_status_labels": ("Y", "Y", "403", "403", "403", "404", "401", "·", "·"),
    "project.edit_settings": ("Y", "Y", "403", "403", "403", "404", "401", "·", "·"),
    "public.erase_submitter": ("Y", "Y", "403", "403", "403", "404", "401", "·", "·"),
    # G. Public submission
    "public.submit": ("Y (c8)",) * 7 + ("·", "·"),
    "public.track": ("Y (c9)",) * 7 + ("·", "·"),
    # H. Platform administration
    "platform.manage_users": ("Y", "403", "403", "403", "403", "403", "401", "·", "·"),
    "platform.manage_groups": ("Y", "403", "403", "403", "403", "403", "401", "·", "·"),
    "platform.configure_sso": ("Y", "403", "403", "403", "403", "403", "401", "·", "·"),
    "platform.configure_email": ("Y", "403", "403", "403", "403", "403", "401", "·", "·"),
    "platform.edit_branding": ("Y", "403", "403", "403", "403", "403", "401", "·", "·"),
    "platform.manage_agents": ("Y", "403", "403", "403", "403", "403", "401", "·", "·"),
    "platform.view_audit_log": ("Y", "403", "403", "403", "403", "403", "401", "·", "·"),
    "api_key.manage_any": ("Y", "403", "403", "403", "403", "403", "401", "·", "·"),
    # I. Self-service, API keys and MCP
    "self.manage_profile": ("Y", "Y", "Y", "Y", "Y", "Y", "401", "·", "·"),
    "self.unsubscribe": ("Y (c14)",) * 7 + ("·", "·"),
    "user.search": ("Y", "Y", "Y", "Y", "Y", "Y", "401", "·", "·"),
    "api_key.manage_own": ("Y", "Y", "Y", "Y", "Y", "Y", "401", "·", "·"),
    "mcp.connect": ("Y (c15)",) * 6 + ("401", "·", "·"),
    # J. AI assistance
    "ai.request_evaluation": ("Y (c6, c10)", "Y (c6, c10)", "403", "403", "403", "404", "401", "+ (c6, c10)", "·"),
    "ai.research": ("Y (c5, c10)", "Y (c5, c10)", "403", "403", "403", "404", "401", "+ (c5, c10)", "·"),
    "ai.draft_section": ("Y (c7, c10)", "Y (c7, c10)", "403", "403", "403", "404", "401", "+ (c7, c10)", "·"),
    "ai.cancel_run": ("Y", "Y", "403", "403", "403", "404", "401", "+", "·"),
}

# Role matrix section 4: the response when each condition fails (c1, c14 and c15 have two
# parts). "breaks" names the ways the tests break it.
CONDITION_RESPONSES: dict[str, dict[str, tuple[int, str]]] = {
    "c1": {"not_submitter": (403, "not_submitter"), "not_new": (409, "idea_not_new")},
    "c2": {"other_author": (403, "not_author")},
    "c3": {"disabled": (403, "volunteering_disabled")},
    "c4": {"ineligible": (422, "assignee_not_eligible")},
    "c5": {"closed": (409, "idea_closed")},
    "c6": {"evaluation_closed": (409, "evaluation_closed"), "idea_closed": (409, "evaluation_closed")},
    "c7": {"too_early": (409, "proposal_not_available")},
    "c8": {
        "disabled": (404, "not_found"),
        "instance_off": (404, "not_found"),
        "archived": (404, "not_found"),
        "reserved_slug": (404, "not_found"),
    },
    "c9": {"no_token": (404, "not_found"), "instance_off": (404, "not_found")},
    "c10": {"no_ai": (409, "ai_unavailable")},
    "c11": {"no_admin_left": (409, "last_admin")},
    "c12": {"moderation": (404, "not_found"), "verification": (404, "not_found")},
    "c13": {"owned": (409, "idea_has_owner")},
    "c14": {"no_token": (404, "not_found"), "narrow_token": (403, "insufficient_scope")},
    "c15": {"session": (401, "unauthorized"), "no_scope": (403, "insufficient_scope")},
}

# Contract section 2: in an archived project every idea-level write is 409.
IDEA_WRITES = {
    "idea.create", "idea.edit_own", "idea.edit_any", "idea.delete", "comment.create",
    "comment.edit_own", "comment.delete_any", "idea.vote", "idea.volunteer_owner",
    "idea.release_owner", "idea.assign_owner", "evaluator.manage", "idea.set_due_date",
    "evaluation.submit_own", "evaluation.close", "evaluation.include_ai",
    "idea.change_status", "idea.moderate", "proposal.write", "proposal.comment",
    "proposal.suggest_section", "ai.request_evaluation", "ai.research", "ai.draft_section",
}
# fmt: on

GLOBAL_RULES = {
    rule for rule in MATRIX if rule.split(".")[0] in {"platform", "api_key", "self", "user", "mcp"}
} | {"project.create"}
PUBLIC_RULES = {"public.submit", "public.track", "self.unsubscribe"}
PROJECT_RULES = {"project.view", "idea.create"} | {
    rule for rule in MATRIX if rule.startswith("project.") and rule not in GLOBAL_RULES
}

ME = uuid4()
OTHER = uuid4()


# --- The markdown ---------------------------------------------------------------------------
def _matrix_rows_in_docs() -> Iterator[tuple[str, tuple[str, ...]]]:
    for line in ROLE_MATRIX.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| `([a-z_]+\.[a-z_]+)` \|", line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        values = tuple(cells[2:])
        if len(values) == 7:  # tables H and I have no overlay columns
            values = (*values, "·", "·")
        yield match.group(1), values


def test_matrix_matches_the_role_matrix_document() -> None:
    documented = dict(_matrix_rows_in_docs())

    assert documented == MATRIX


def test_policy_has_exactly_the_documented_rules() -> None:
    assert {str(rule) for rule in POLICY} == set(MATRIX)
    assert {str(rule) for rule in Rule} == set(MATRIX)


@pytest.mark.parametrize("rule", sorted(MATRIX))
def test_policy_table_is_the_documented_row(rule: str) -> None:
    assert POLICY[Rule(rule)].source == MATRIX[rule]


def test_rules_are_scoped_as_documented() -> None:
    for rule, spec in POLICY.items():
        if rule in PUBLIC_RULES:
            assert spec.scope == "public"
        elif rule in GLOBAL_RULES:
            assert spec.scope == "global"
        elif rule in PROJECT_RULES:
            assert spec.scope == "project"
        else:
            assert spec.scope == "idea", rule
        assert spec.idea_write == (rule in IDEA_WRITES), rule


# --- Building principals and resources ------------------------------------------------------
@dataclass
class State:
    """One principal in one situation; ``build()`` makes the policy's inputs."""

    column: str
    platform_admin: bool = False
    role: ProjectRole | None = None
    anonymous: bool = False
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE
    auth: Literal["session", "api_key"] = "session"
    scopes: frozenset[Literal["read", "write", "evaluate", "mcp"]] | None = None
    archived: bool = False
    allow_volunteer_owners: bool = True
    public_submission_enabled: bool = True
    public_submission_on: bool = True
    slug_reserved: bool = False
    status: IdeaStatus = IdeaStatus.EVALUATING
    owner_id: UUID | None = None
    submitted_by_id: UUID | None = field(default_factory=lambda: OTHER)
    evaluation_closed: bool = False
    held_for: HoldReason | None = None
    my_evaluation: EvaluatorState | None = None
    comment_author_id: UUID | None = None
    assignee_roles: tuple[ProjectRole | None, ...] | None = None
    admins_after_change: int | None = None
    ai_available: bool = True
    token_valid: bool = True
    token_covers_request: bool = True

    def build(self) -> tuple[Principal | None, Resource]:
        principal = None
        if not self.anonymous:
            user = User(id=ME, email="me@example.com", display_name="Me")
            user.is_platform_admin = self.platform_admin
            principal = Principal(user=user, auth=self.auth, scopes=self.scopes)
        project = ProjectFacts(
            id=uuid4(),
            visibility=self.visibility,
            archived=self.archived,
            allow_volunteer_owners=self.allow_volunteer_owners,
            public_submission_enabled=self.public_submission_enabled,
            slug_reserved=self.slug_reserved,
        )
        idea = IdeaFacts(
            id=uuid4(),
            status=self.status,
            owner_id=self.owner_id,
            submitted_by_id=self.submitted_by_id,
            evaluation_closed=self.evaluation_closed,
            held_for=self.held_for,
            my_evaluation=self.my_evaluation,
        )
        return principal, Resource(
            project=project,
            role=self.role,
            idea=idea,
            comment_author_id=self.comment_author_id,
            assignee_roles=self.assignee_roles,
            admins_after_change=self.admins_after_change,
            ai_available=self.ai_available,
            token_valid=self.token_valid,
            token_covers_request=self.token_covers_request,
            public_submission_on=self.public_submission_on,
        )


def state_for(column: str) -> State:
    """The column's principal, every resource condition holding by default."""
    match column:
        case "PA":
            return State(column, platform_admin=True)
        case "PAd":
            return State(column, role=ProjectRole.ADMIN)
        case "Mem":
            return State(column, role=ProjectRole.MEMBER)
        case "Vwr":
            return State(column, role=ProjectRole.VIEWER)
        case "NMi":
            return State(column, visibility=ProjectVisibility.INTERNAL)
        case "NMp":
            return State(column)
        case "Pub":
            return State(column, anonymous=True)
        case "+Own":
            return State(column, role=ProjectRole.MEMBER, owner_id=ME)
        case "+Evl":
            return State(column, role=ProjectRole.MEMBER, my_evaluation=EvaluatorState.INVITED)
    raise AssertionError(column)


def satisfy(state: State, condition: str, rule: str) -> State:
    """Make ``condition`` hold (it may need facts the default state lacks)."""
    match condition:
        case "c1":
            return replace(state, submitted_by_id=ME, status=IdeaStatus.NEW)
        case "c2":
            return replace(state, comment_author_id=ME)
        case "c4" if rule == "idea.volunteer_owner":
            # A platform admin needs a real project role to become owner.
            return replace(state, role=state.role or ProjectRole.MEMBER)
        case "c4":
            return replace(state, assignee_roles=(ProjectRole.MEMBER, ProjectRole.ADMIN))
        case "c7":
            return replace(state, status=IdeaStatus.SHORTLISTED)
        case "c11":
            return replace(state, admins_after_change=1)
        case "c15":
            return replace(state, auth="api_key", scopes=frozenset({"mcp"}))
    return state  # the default state already satisfies the others


BREAKS: dict[str, dict[str, Callable[[State, str], State]]] = {
    "c1": {
        "not_submitter": lambda s, _: replace(s, submitted_by_id=OTHER),
        "not_new": lambda s, _: replace(s, status=IdeaStatus.EVALUATING),
    },
    "c2": {"other_author": lambda s, _: replace(s, comment_author_id=OTHER)},
    "c3": {"disabled": lambda s, _: replace(s, allow_volunteer_owners=False)},
    "c4": {
        "ineligible": lambda s, rule: (
            replace(s, role=None)
            if rule == "idea.volunteer_owner"
            else replace(s, assignee_roles=(ProjectRole.MEMBER, ProjectRole.VIEWER))
        )
    },
    "c5": {"closed": lambda s, _: replace(s, status=IdeaStatus.CLOSED)},
    "c6": {
        "evaluation_closed": lambda s, _: replace(s, evaluation_closed=True),
        "idea_closed": lambda s, _: replace(s, status=IdeaStatus.CLOSED),
    },
    "c7": {"too_early": lambda s, _: replace(s, status=IdeaStatus.EVALUATING)},
    "c8": {
        "disabled": lambda s, _: replace(s, public_submission_enabled=False),
        "instance_off": lambda s, _: replace(s, public_submission_on=False),
        "archived": lambda s, _: replace(s, archived=True),
        "reserved_slug": lambda s, _: replace(s, slug_reserved=True),
    },
    "c9": {
        "no_token": lambda s, _: replace(s, token_valid=False),
        "instance_off": lambda s, _: replace(s, public_submission_on=False),
    },
    "c10": {"no_ai": lambda s, _: replace(s, ai_available=False)},
    "c11": {"no_admin_left": lambda s, _: replace(s, admins_after_change=0)},
    "c12": {
        "moderation": lambda s, _: replace(s, held_for=HoldReason.MODERATION),
        "verification": lambda s, _: replace(s, held_for=HoldReason.EMAIL_VERIFICATION),
    },
    "c13": {"owned": lambda s, _: replace(s, owner_id=OTHER)},
    "c14": {
        "no_token": lambda s, _: replace(s, token_valid=False),
        "narrow_token": lambda s, _: replace(s, token_covers_request=False),
    },
    "c15": {
        "session": lambda s, _: replace(s, auth="session", scopes=None),
        "no_scope": lambda s, _: replace(s, scopes=frozenset({"read", "write", "evaluate"})),
    },
}


def conditions_of(cell: str) -> tuple[str, ...]:
    match = re.search(r"\((.*)\)", cell)
    return tuple(name.strip() for name in match.group(1).split(",")) if match else ()


def happy_state(rule: str, column: str) -> State:
    state = state_for(column)
    cell = MATRIX[rule][COLUMNS.index(column)]
    base_cell = MATRIX[rule][COLUMNS.index("Mem")] if column.startswith("+") else cell
    for condition in conditions_of(cell) + conditions_of(base_cell):
        state = satisfy(state, condition, rule)
    return state


def decide(rule: str, state: State) -> Decision:
    principal, resource = state.build()
    return authorize(principal, Rule(rule), resource)


def outcome(decision: Decision) -> str:
    if decision.hidden:
        return "hidden"
    return "allow" if decision.allowed else str(decision.status)


# --- Row by row: the cell in a state where every condition holds ----------------------------
CASES = [(rule, column) for rule in sorted(MATRIX) for column in COLUMNS]


@pytest.mark.parametrize(("rule", "column"), CASES)
def test_cell(rule: str, column: str) -> None:
    cell = MATRIX[rule][COLUMNS.index(column)]
    decision = decide(rule, happy_state(rule, column))

    if cell == "·":
        # The overlay adds nothing: same answer as a member who isn't owner/evaluator.
        plain = decide(rule, replace(happy_state(rule, column), column="Mem", my_evaluation=None))
        if column == "+Own":
            plain = decide(rule, replace(happy_state(rule, column), owner_id=OTHER))
        assert (decision.allowed, decision.status, decision.code) == (
            plain.allowed,
            plain.status,
            plain.code,
        )
    elif cell == "✱":
        assert outcome(decision) == "hidden"  # a pending evaluator sees no score data
    elif cell.startswith(("Y", "+")):
        assert outcome(decision) == "allow", decision
    else:
        assert outcome(decision) == cell, decision
        assert (
            decision.code == {"401": "unauthorized", "403": "forbidden", "404": "not_found"}[cell]
        )


# --- Each condition broken on its own -------------------------------------------------------
CONDITION_CASES = [
    (rule, column, condition, how)
    for rule in sorted(MATRIX)
    for column in COLUMNS
    for condition in conditions_of(MATRIX[rule][COLUMNS.index(column)])
    if MATRIX[rule][COLUMNS.index(column)].startswith(("Y", "+"))
    for how in CONDITION_RESPONSES[condition]
]


@pytest.mark.parametrize(("rule", "column", "condition", "how"), CONDITION_CASES)
def test_condition(rule: str, column: str, condition: str, how: str) -> None:
    state = BREAKS[condition][how](happy_state(rule, column), rule)

    decision = decide(rule, state)

    assert not decision.allowed
    assert (decision.status, decision.code) == CONDITION_RESPONSES[condition][how]
    if (condition, how) != ("c15", "no_scope"):  # the generic key-scope check answers first
        assert decision.condition == condition


def test_every_condition_is_exercised() -> None:
    exercised = {condition for _, _, condition, _ in CONDITION_CASES}

    assert exercised == set(CONDITION_RESPONSES)


# --- Held ideas: c12 hides them, c19 freezes them (contract-phase4 section 3.6) --------------
IDEA_RULES = sorted(rule for rule, spec in POLICY.items() if spec.scope == "idea")
# c19: every idea write but delete and moderate, plus watching (contract-phase4 section 2).
FROZEN_WHILE_HELD = (IDEA_WRITES - {"idea.create", "idea.delete", "idea.moderate"}) | {"idea.watch"}


@pytest.mark.parametrize("rule", IDEA_RULES)
@pytest.mark.parametrize("column", ["Mem", "Vwr", "NMi", "+Own", "+Evl"])
def test_idea_awaiting_moderation_is_404_for_non_admins(rule: str, column: str) -> None:
    state = replace(happy_state(rule, column), held_for=HoldReason.MODERATION)

    assert outcome(decide(rule, state)) == "404"


@pytest.mark.parametrize("rule", IDEA_RULES)
@pytest.mark.parametrize("column", ["PA", "PAd"])
def test_admins_see_ideas_awaiting_moderation_but_cannot_change_them(
    rule: str, column: str
) -> None:
    happy = decide(rule, happy_state(rule, column))
    moderated = decide(rule, replace(happy_state(rule, column), held_for=HoldReason.MODERATION))

    if happy.allowed and rule in FROZEN_WHILE_HELD:
        assert (moderated.status, moderated.code) == (409, "awaiting_moderation")
        assert moderated.condition == "c19"
    else:
        assert outcome(moderated) == outcome(happy)


@pytest.mark.parametrize("rule", ["idea.delete", "idea.moderate", "public.erase_submitter"])
@pytest.mark.parametrize("column", ["PA", "PAd"])
def test_admins_can_delete_moderate_and_erase_a_held_idea(rule: str, column: str) -> None:
    state = replace(happy_state(rule, column), held_for=HoldReason.MODERATION)

    assert decide(rule, state).allowed


@pytest.mark.parametrize("rule", IDEA_RULES)
@pytest.mark.parametrize("column", COLUMNS)
def test_an_idea_awaiting_email_confirmation_is_404_for_everyone(rule: str, column: str) -> None:
    state = replace(happy_state(rule, column), held_for=HoldReason.EMAIL_VERIFICATION)

    decision = decide(rule, state)

    if column == "Pub":
        assert outcome(decision) == "401"
    else:
        assert outcome(decision) == "404"
        assert decision.code == "not_found"


def test_held_ideas_are_frozen_before_other_state_conditions() -> None:
    """An archived project still answers project_archived first (it leads the 409s),
    then c19 before the rule's own conditions (c7 here)."""
    state = replace(happy_state("proposal.write", "PA"), status=IdeaStatus.NEW)
    held = replace(state, held_for=HoldReason.MODERATION)

    assert decide("proposal.write", state).code == "proposal_not_available"
    assert decide("proposal.write", held).code == "awaiting_moderation"
    assert decide("proposal.write", replace(held, archived=True)).code == "project_archived"


# --- Archived projects (contract section 2) -------------------------------------------------
@pytest.mark.parametrize(("rule", "column"), CASES)
def test_archived_project(rule: str, column: str) -> None:
    happy = decide(rule, happy_state(rule, column))
    archived = decide(rule, replace(happy_state(rule, column), archived=True))

    if happy.allowed and rule in IDEA_WRITES:
        assert (archived.status, archived.code) == (409, "project_archived")
    elif rule == "public.submit":
        # c8: an archived project's public form is unavailable (404, like unknown).
        assert (archived.status, archived.code) == (404, "not_found")
    else:
        assert outcome(archived) == outcome(happy)
