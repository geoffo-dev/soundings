"""Phase 8b: researcher access in the policy (role matrix table L, c23-c25; contract-phase8b
section 4), as tables.

* Table L is copied by hand (``TABLE_L``) and checked against the markdown and the policy.
* Column R and the +Rsr overlay, for every idea-scoped rule: the guest researcher of a
  private project (R), an internal project's non-member researcher (NMi + Rsr), a viewer,
  member, project admin and platform admin researcher, in every assignment state (live;
  never assigned; someone else's; the idea closed; the step off; the project archived),
  with sessions and API keys.
* The guest route table (``app.authz.guest``): every idea route and MCP tool has a row
  (deny by default), and a hidden operation is 404 for R whatever the rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest

from app.authz import (
    POLICY,
    RESEARCH_GUEST_ACCESS,
    Decision,
    GuestAccess,
    IdeaFacts,
    NamedResearcher,
    ProjectFacts,
    Resource,
    Rule,
    authorize,
    can,
    guest_access,
    idea_permissions,
    mcp_operation,
    require_view,
)
from app.authz.policy import TABLE_L, researcher_live
from app.domain.principal import ApiKeyScope, Principal
from app.errors import ProblemError
from app.models.enums import IdeaStatus, ProjectRole, ProjectVisibility, ResearchStep
from app.models.user import User
from app.schemas.mcp import MCP_TOOLS

ROLE_MATRIX = Path(__file__).resolve().parents[3] / "docs" / "role-matrix.md"
OPENAPI = (
    Path(__file__).resolve().parents[3] / "frontend" / "src" / "api" / "generated" / "openapi.json"
)

ME = uuid4()
SOMEONE = uuid4()

# fmt: off
# Role matrix table L: rule -> (R, +Rsr), copied by hand.
TABLE: dict[str, tuple[str, str]] = {
    "idea.view": ("Y (c12)", "·"),
    "idea.edit_own": ("403", "·"),
    "idea.edit_any": ("403", "·"),
    "idea.delete": ("403", "·"),
    "comment.create": ("403", "+"),
    "comment.edit_own": ("403", "+ (c2)"),
    "comment.delete_any": ("403", "·"),
    "idea.vote": ("403", "·"),
    "idea.watch": ("Y", "·"),
    "idea.volunteer_owner": ("403", "·"),
    "idea.release_owner": ("403", "·"),
    "idea.assign_owner": ("403", "·"),
    "evaluator.manage": ("404", "·"),
    "idea.set_due_date": ("404", "·"),
    "evaluation.submit_own": ("404", "·"),
    "evaluation.close": ("404", "·"),
    "evaluation.include_ai": ("404", "·"),
    "idea.change_status": ("403", "·"),
    "idea.moderate": ("404", "·"),
    "evaluation.view_own": ("404", "·"),
    "evaluation.view_others": ("404", "·"),
    "score.view_aggregate": ("404", "·"),
    "proposal.view": ("404", "·"),
    "proposal.write": ("404", "·"),
    "proposal.comment": ("404", "·"),
    "proposal.suggest_section": ("404", "·"),
    "proposal.export": ("404", "·"),
    "public.erase_submitter": ("404", "·"),
    "ai.request_evaluation": ("404", "·"),
    "ai.research": ("404", "·"),
    "ai.draft_section": ("404", "·"),
    "ai.cancel_run": ("404", "·"),
    "ai.delete_note": ("403", "·"),
    "idea.answer_research": ("403", "+ (c26)"),
    "idea.research_override": ("403", "·"),
    "idea.assign_researcher": ("403", "·"),
    "idea.release_researcher": ("403", "+"),
}
# Table L's route table, copied by hand (operation -> R).
ROUTES: dict[str, str] = {
    "get_idea": "view", "list_idea_activity": "view", "watch_idea": "view",
    "unwatch_idea": "view", "get_idea_research": "view", "list_similar_ideas": "view",
    "get_research_note": "view",
    "create_comment": "rule", "update_comment": "rule", "delete_comment": "rule",
    "answer_research_item": "rule", "clear_research_item": "rule",
    "remove_researcher": "rule", "update_idea": "rule", "delete_idea": "rule",
    "change_idea_status": "rule", "set_idea_owner": "rule", "volunteer_as_owner": "rule",
    "vote_idea": "rule", "unvote_idea": "rule", "set_research_assignment": "rule",
    "delete_research_note": "rule",
    "add_evaluators": "hidden", "remove_evaluator": "hidden",
    "set_evaluation_due_date": "hidden", "close_evaluation": "hidden",
    "reopen_evaluation": "hidden", "list_evaluations": "hidden",
    "get_my_evaluation": "hidden", "save_my_evaluation": "hidden",
    "set_evaluation_inclusion": "hidden",
    "get_proposal": "hidden", "create_proposal": "hidden", "update_proposal_section": "hidden",
    "export_proposal_markdown": "hidden", "export_proposal_pdf": "hidden",
    "list_proposal_threads": "hidden", "create_proposal_thread": "hidden",
    "reply_to_proposal_thread": "hidden", "resolve_proposal_thread": "hidden",
    "reopen_proposal_thread": "hidden", "delete_proposal_comment": "hidden",
    "list_proposal_suggestions": "hidden", "create_proposal_suggestion": "hidden",
    "accept_proposal_suggestion": "hidden", "discard_proposal_suggestion": "hidden",
    "get_idea_submission": "hidden", "approve_submission": "hidden",
    "reject_submission": "hidden", "erase_submitter": "hidden",
    "list_idea_ai_runs": "hidden", "request_ai_evaluation": "hidden",
    "request_ai_research": "hidden", "request_ai_section_draft": "hidden",
    "get_ai_run": "hidden", "cancel_ai_run": "hidden", "stream_ai_run_events": "hidden",
    "get_my_work": "list", "get_my_work_counts": "list", "list_my_research_to_do": "list",
    "global_search": "list", "list_notifications": "list",
    "get_notification_summary": "list", "mark_notification_read": "list",
    "mark_all_notifications_read": "list",
    "mcp.get_idea": "view", "mcp.search_ideas": "list", "mcp.add_comment": "rule",
    "mcp.list_projects": "list", "mcp.add_research_note": "rule",
    "mcp.get_rubric": "hidden", "mcp.get_proposal": "hidden", "mcp.create_idea": "hidden",
    "mcp.propose_proposal_section": "hidden", "mcp.submit_evaluation": "hidden",
}
# fmt: on

IDEA_RULES = sorted(str(rule) for rule, spec in POLICY.items() if spec.scope == "idea")


# --- The documents ---------------------------------------------------------------------------
def _table_l_rows() -> dict[str, tuple[str, str]]:
    text = ROLE_MATRIX.read_text(encoding="utf-8")
    section = text.split("### L. Researcher access (Phase 8b)", 1)[1].split("\n## ", 1)[0]
    rows: dict[str, tuple[str, str]] = {}
    for line in section.splitlines():
        match = re.match(r"^\| ([a-z_]+\.[a-z_]+) \| ([^|]+) \| ([^|]+) \|", line)
        if match:
            rows[match.group(1)] = (match.group(2).strip(), match.group(3).strip())
    return rows


def test_table_l_matches_the_role_matrix_document() -> None:
    assert _table_l_rows() == TABLE


def test_the_policy_carries_table_l() -> None:
    assert {str(rule): cells for rule, cells in TABLE_L.items()} == TABLE


def test_table_l_lists_every_idea_scoped_rule() -> None:
    assert set(TABLE) == set(IDEA_RULES)


def test_the_route_table_matches_the_documented_one() -> None:
    assert {op: str(access) for op, access in RESEARCH_GUEST_ACCESS.items()} == ROUTES


def _idea_operations() -> set[str]:
    import json

    document = json.loads(OPENAPI.read_text(encoding="utf-8"))
    return {
        operation["operationId"]
        for path, item in document["paths"].items()
        if "{idea}" in path or path.startswith("/api/v1/comments/")
        for operation in item.values()
    }


def test_every_idea_route_and_mcp_tool_has_a_guest_row() -> None:
    """Deny by default: a new idea route or tool is hidden from guests until someone puts
    it in the table on purpose (and so this test fails until then)."""
    missing = (_idea_operations() | {mcp_operation(tool.name) for tool in MCP_TOOLS}) - set(
        RESEARCH_GUEST_ACCESS
    )

    assert not missing


def test_an_operation_without_a_row_is_hidden() -> None:
    assert guest_access("some_new_route") is GuestAccess.HIDDEN
    assert guest_access(None) is None  # outside a request: the rules decide


# --- Principals and states ------------------------------------------------------------------
Kind = Literal["R", "NMi+Rsr", "Vwr+Rsr", "Mem+Rsr", "PAd+Rsr", "PA+Rsr"]
State = Literal["live", "never", "someone_else", "closed", "step_off", "archived"]
KINDS: tuple[Kind, ...] = ("R", "NMi+Rsr", "Vwr+Rsr", "Mem+Rsr", "PAd+Rsr", "PA+Rsr")
STATES: tuple[State, ...] = ("live", "never", "someone_else", "closed", "step_off", "archived")


@dataclass(frozen=True)
class Case:
    kind: Kind
    state: State = "live"
    auth: Literal["session", "api_key"] = "session"
    scopes: frozenset[ApiKeyScope] | None = None
    key_projects: frozenset[UUID] | None = None
    operation: str | None = None
    service_account: bool = False
    unassigned: bool = False
    """The same idea and state with nobody assigned (the column alone decides)."""

    def build(self, project_id: UUID) -> tuple[Principal, Resource]:
        user = User(id=ME, email="me@example.com", display_name="Me")
        user.is_platform_admin = self.kind == "PA+Rsr"
        user.is_service_account = self.service_account
        principal = Principal(
            user=user,
            auth=self.auth,
            scopes=self.scopes,
            project_ids=self.key_projects,
            operation=self.operation,
        )
        role = {
            "Vwr+Rsr": ProjectRole.VIEWER,
            "Mem+Rsr": ProjectRole.MEMBER,
            "PAd+Rsr": ProjectRole.ADMIN,
        }.get(self.kind)
        visibility = (
            ProjectVisibility.INTERNAL if self.kind == "NMi+Rsr" else ProjectVisibility.PRIVATE
        )
        project = ProjectFacts(
            id=project_id,
            visibility=visibility,
            archived=self.state == "archived",
            research_step=(
                ResearchStep.OFF if self.state == "step_off" else ResearchStep.BEFORE_EVALUATION
            ),
        )
        researcher = {"never": None, "someone_else": SOMEONE}.get(self.state, ME)
        if self.unassigned:
            researcher = None
        idea = IdeaFacts(
            id=uuid4(),
            status=IdeaStatus.CLOSED if self.state == "closed" else IdeaStatus.RESEARCH,
            owner_id=SOMEONE,
            submitted_by_id=SOMEONE,
            researcher_id=researcher,
        )
        return principal, Resource(project=project, role=role, idea=idea)


PROJECT = uuid4()


def decide(case: Case, rule: str, **facts: object) -> Decision:
    principal, resource = case.build(PROJECT)
    return authorize(principal, Rule(rule), resource.replace(**facts))


def outcome(decision: Decision) -> str:
    if decision.hidden:
        return "hidden"
    return "allow" if decision.allowed else str(decision.status)


def _without_researcher(case: Case) -> Case:
    """The same principal and idea with nobody assigned (the column alone decides)."""
    return replace(case, unassigned=True)


# --- Column R: the guest researcher of a private project ------------------------------------
def _facts_for(rule: str) -> dict[str, object]:
    """Facts that make the rule's own conditions hold, so the cell is what's tested."""
    if rule == "comment.edit_own":
        return {"comment_author_id": ME}
    return {}


@pytest.mark.parametrize("rule", IDEA_RULES)
def test_column_r_is_table_l(rule: str) -> None:
    guest, overlay = TABLE[rule]
    decision = decide(Case("R"), rule, **_facts_for(rule))

    if overlay.startswith("+") or guest.startswith("Y"):
        assert outcome(decision) == "allow", decision
    else:
        assert outcome(decision) == guest, decision
        assert decision.code == {"403": "forbidden", "404": "not_found"}[guest]


@pytest.mark.parametrize("rule", IDEA_RULES)
@pytest.mark.parametrize("state", [s for s in STATES if s != "live"])
def test_r_ends_with_the_live_assignment(rule: str, state: State) -> None:
    """Never assigned, someone else's, closed, step off, archived: a private project's
    non-member is NMp again, 404 for every idea rule (c24)."""
    assert outcome(decide(Case("R", state), rule, **_facts_for(rule))) == "404"


@pytest.mark.parametrize("rule", IDEA_RULES)
def test_a_service_account_is_never_r(rule: str) -> None:
    """c23 in depth: even with the column's facts, an agent's account stays NMp."""
    case = Case("R", service_account=True)

    assert outcome(decide(case, rule, **_facts_for(rule))) == "404"


# --- The +Rsr overlay in the other columns -----------------------------------------------------
@pytest.mark.parametrize("rule", IDEA_RULES)
@pytest.mark.parametrize("kind", ["NMi+Rsr", "Vwr+Rsr", "Mem+Rsr", "PAd+Rsr", "PA+Rsr"])
def test_the_overlay_adds_only_its_cells(rule: str, kind: Kind) -> None:
    """+Rsr: the column's own answer, plus commenting, answering and handing back."""
    _, overlay = TABLE[rule]
    facts = _facts_for(rule)
    with_researcher = decide(Case(kind), rule, **facts)
    column_alone = decide(_without_researcher(Case(kind)), rule, **facts)

    if overlay.startswith("+"):
        assert outcome(with_researcher) == "allow", (kind, rule, with_researcher)
    else:
        assert outcome(with_researcher) == outcome(column_alone), (kind, rule)


@pytest.mark.parametrize("kind", ["NMi+Rsr", "Vwr+Rsr", "Mem+Rsr"])
@pytest.mark.parametrize("state", ["closed", "step_off", "archived"])
def test_the_overlay_grants_nothing_unless_live(kind: Kind, state: State) -> None:
    for rule in ("comment.create", "idea.answer_research", "idea.release_researcher"):
        case = Case(kind, state)
        assert outcome(decide(case, rule)) == outcome(decide(_without_researcher(case), rule))


def test_an_internal_researcher_keeps_the_internal_view() -> None:
    """Assignment adds, never takes away: NMi + Rsr still reads scores and the proposal."""
    for rule in ("score.view_aggregate", "evaluation.view_others", "proposal.view"):
        assert outcome(decide(Case("NMi+Rsr"), rule)) == "allow"


# --- Assigning: c23 and c25 --------------------------------------------------------------------
def _assign(kind: str, named: NamedResearcher | None, *, internal: bool = False) -> Decision:
    user = User(id=ME, email="me@example.com", display_name="Me")
    user.is_platform_admin = kind == "PA"
    role = {"PAd": ProjectRole.ADMIN, "Own": ProjectRole.MEMBER, "Mem": ProjectRole.MEMBER}.get(
        kind
    )
    project = ProjectFacts(
        PROJECT,
        ProjectVisibility.INTERNAL if internal else ProjectVisibility.PRIVATE,
        research_step=ResearchStep.BEFORE_EVALUATION,
    )
    idea = IdeaFacts(id=uuid4(), status=IdeaStatus.NEW, owner_id=ME if kind == "Own" else SOMEONE)
    resource = Resource(project=project, role=role, idea=idea, researcher_named=named)
    return authorize(Principal(user=user), Rule.IDEA_ASSIGN_RESEARCHER, resource)


OUTSIDER = NamedResearcher(eligible=True, role=None)
MEMBER = NamedResearcher(eligible=True, role=ProjectRole.VIEWER)
AGENT = NamedResearcher(eligible=False, role=ProjectRole.MEMBER)


@pytest.mark.parametrize(
    ("kind", "named", "internal", "expected"),
    [
        ("Own", MEMBER, False, ("allow", None)),
        ("Own", None, False, ("allow", None)),  # removing, or the same researcher again
        ("Own", OUTSIDER, False, ("403", "outside_researcher_needs_admin")),
        ("Own", OUTSIDER, True, ("allow", None)),  # internal: the owner names anyone
        ("Own", AGENT, False, ("422", "researcher_not_eligible")),
        ("Own", NamedResearcher(eligible=False), False, ("403", "outside_researcher_needs_admin")),
        ("PAd", OUTSIDER, False, ("allow", None)),
        ("PA", OUTSIDER, False, ("allow", None)),
        ("PAd", AGENT, False, ("422", "researcher_not_eligible")),
        ("PA", NamedResearcher(eligible=False), False, ("422", "researcher_not_eligible")),
        ("Mem", MEMBER, False, ("403", "forbidden")),
    ],
)
def test_who_may_be_named(
    kind: str, named: NamedResearcher | None, internal: bool, expected: tuple[str, str | None]
) -> None:
    decision = _assign(kind, named, internal=internal)

    assert (outcome(decision), None if decision.allowed else decision.code) == expected


def test_assign_flags_follow_c25() -> None:
    def flags(kind: str, visibility: ProjectVisibility) -> tuple[bool, bool]:
        user = User(id=ME, email="me@example.com", display_name="Me")
        user.is_platform_admin = kind == "PA"
        role = {"PAd": ProjectRole.ADMIN, "Own": ProjectRole.MEMBER}.get(kind)
        resource = Resource(
            project=ProjectFacts(PROJECT, visibility, research_step=ResearchStep.BEFORE_PROPOSAL),
            role=role,
            idea=IdeaFacts(
                id=uuid4(), status=IdeaStatus.NEW, owner_id=ME if kind == "Own" else None
            ),
        )
        found = idea_permissions(Principal(user=user), resource)
        return found.can_assign_researcher, found.can_assign_outside_researcher

    private, internal = ProjectVisibility.PRIVATE, ProjectVisibility.INTERNAL
    assert flags("Own", private) == (True, False)
    assert flags("Own", internal) == (True, True)
    assert flags("PAd", private) == (True, True)
    assert flags("PA", private) == (True, True)


# --- The guest's permission flags ---------------------------------------------------------------
def test_the_guest_shape_flags() -> None:
    principal, resource = Case("R").build(PROJECT)

    flags = idea_permissions(principal, resource)

    assert flags.can_comment
    assert flags.can_answer_research
    assert flags.can_hand_back_research
    assert not flags.can_view_project
    assert not any(
        flags.model_dump(
            exclude={"can_comment", "can_answer_research", "can_hand_back_research"}
        ).values()
    )


def test_a_member_researcher_keeps_the_project() -> None:
    principal, resource = Case("Mem+Rsr").build(PROJECT)

    flags = idea_permissions(principal, resource)

    assert flags.can_view_project
    assert flags.can_hand_back_research
    assert flags.can_answer_research


# --- API keys: key ∩ person ∩ policy -----------------------------------------------------------
@pytest.mark.parametrize(
    ("scopes", "rule", "expected"),
    [
        (frozenset({"read"}), "idea.view", "allow"),
        (frozenset({"read"}), "comment.create", "403"),  # needs write
        (frozenset({"read", "write"}), "comment.create", "allow"),
        (frozenset({"read", "write"}), "idea.answer_research", "allow"),
        (frozenset({"read", "write"}), "idea.release_researcher", "allow"),
        (frozenset({"read", "write"}), "score.view_aggregate", "404"),
        (frozenset({"read", "write", "evaluate"}), "evaluation.view_own", "404"),
        (frozenset({"mcp"}), "idea.view", "403"),
    ],
)
def test_a_guest_researchers_unrestricted_key(
    scopes: frozenset[ApiKeyScope], rule: str, expected: str
) -> None:
    case = Case("R", auth="api_key", scopes=scopes)

    assert outcome(decide(case, rule)) == expected


def test_a_restricted_key_reaches_the_idea_only_as_r_does() -> None:
    """Made while a member (the restriction names the project): it reaches the idea only
    with R's cells; restricted to another project: 404 (contract review C2)."""
    here = Case("R", auth="api_key", scopes=frozenset({"read"}), key_projects=frozenset({PROJECT}))
    elsewhere = replace(here, key_projects=frozenset({uuid4()}))

    assert outcome(decide(here, "idea.view")) == "allow"
    assert outcome(decide(here, "proposal.view")) == "404"
    assert outcome(decide(elsewhere, "idea.view")) == "404"


# --- The route table in the policy ---------------------------------------------------------------
@pytest.mark.parametrize(
    "operation", sorted(op for op, access in ROUTES.items() if access == "hidden")
)
@pytest.mark.parametrize("rule", ["idea.view", "comment.create", "idea.answer_research"])
def test_a_hidden_operation_is_404_for_r(operation: str, rule: str) -> None:
    decision = decide(Case("R", operation=operation), rule)

    assert (decision.status, decision.code) == (404, "not_found")


@pytest.mark.parametrize("operation", ["list_evaluations", "get_proposal", "made_up_route"])
def test_require_view_hides_the_operation_from_r_only(operation: str) -> None:
    guest, guest_resource = Case("R", operation=operation).build(PROJECT)
    member, member_resource = Case("Mem+Rsr", operation=operation).build(PROJECT)

    with pytest.raises(ProblemError) as raised:
        require_view(guest, guest_resource)
    assert raised.value.status == 404
    require_view(member, member_resource)  # a member researcher keeps the member view


@pytest.mark.parametrize(
    "operation", sorted(op for op, access in ROUTES.items() if access != "hidden")
)
def test_a_visible_operation_lets_the_rules_decide(operation: str) -> None:
    principal, resource = Case("R", operation=operation).build(PROJECT)

    require_view(principal, resource)
    assert can(principal, Rule.IDEA_ANSWER_RESEARCH, resource)
    assert not can(principal, Rule.SCORE_VIEW_AGGREGATE, resource)


def test_live_is_c24() -> None:
    for state in STATES:
        principal, resource = Case("Mem+Rsr", state).build(PROJECT)
        assert researcher_live(principal, resource) is (state == "live"), state


# --- c26: past Research only the owner and admins change the answers (lead decision D1) -----
@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("R", ("409", "research_finished")),
        ("NMi+Rsr", ("409", "research_finished")),
        ("Vwr+Rsr", ("409", "research_finished")),
        ("Mem+Rsr", ("409", "research_finished")),
        ("PAd+Rsr", ("allow", "ok")),  # the column's own grant
        ("PA+Rsr", ("allow", "ok")),
    ],
)
@pytest.mark.parametrize(
    ("step", "status", "past"),
    [
        (ResearchStep.BEFORE_EVALUATION, IdeaStatus.NEW, False),
        (ResearchStep.BEFORE_EVALUATION, IdeaStatus.RESEARCH, False),
        (ResearchStep.BEFORE_EVALUATION, IdeaStatus.EVALUATING, True),
        (ResearchStep.BEFORE_EVALUATION, IdeaStatus.PROPOSAL, True),
        (ResearchStep.BEFORE_PROPOSAL, IdeaStatus.SHORTLISTED, False),
        (ResearchStep.BEFORE_PROPOSAL, IdeaStatus.PROPOSAL, True),
    ],
)
def test_c26_the_researcher_answers_only_until_research_ends(
    kind: Kind,
    expected: tuple[str, str],
    step: ResearchStep,
    status: IdeaStatus,
    past: bool,
) -> None:
    principal, resource = Case(kind).build(PROJECT)
    assert resource.idea is not None
    assert resource.project is not None
    resource = resource.replace(
        idea=replace(resource.idea, status=status),
        project=replace(resource.project, research_step=step),
    )

    decision = authorize(principal, Rule.IDEA_ANSWER_RESEARCH, resource)

    assert (outcome(decision), decision.code) == (expected if past else ("allow", "ok"))
    assert idea_permissions(principal, resource).can_answer_research is decision.allowed


@pytest.mark.parametrize("role", [ProjectRole.MEMBER, ProjectRole.ADMIN])
def test_c26_an_owner_researcher_keeps_the_owners_rule(role: ProjectRole) -> None:
    principal, resource = Case("Mem+Rsr").build(PROJECT)
    assert resource.idea is not None
    resource = resource.replace(
        role=role, idea=replace(resource.idea, status=IdeaStatus.PROPOSAL, owner_id=ME)
    )

    assert can(principal, Rule.IDEA_ANSWER_RESEARCH, resource)


def test_c26_a_viewer_owner_researcher_follows_the_researchers_rule() -> None:
    """The owner overlay needs a member or admin role; +Rsr then decides (c26)."""
    principal, resource = Case("Vwr+Rsr").build(PROJECT)
    assert resource.idea is not None
    resource = resource.replace(
        idea=replace(resource.idea, status=IdeaStatus.EVALUATING, owner_id=ME)
    )

    decision = authorize(principal, Rule.IDEA_ANSWER_RESEARCH, resource)

    assert (decision.status, decision.code) == (409, "research_finished")


def test_c26_a_write_key_hears_the_same_409() -> None:
    case = Case("R", auth="api_key", scopes=frozenset({"read", "write"}))
    principal, resource = case.build(PROJECT)
    assert resource.idea is not None
    resource = resource.replace(idea=replace(resource.idea, status=IdeaStatus.EVALUATING))

    decision = authorize(principal, Rule.IDEA_ANSWER_RESEARCH, resource)

    assert (decision.status, decision.code) == (409, "research_finished")
