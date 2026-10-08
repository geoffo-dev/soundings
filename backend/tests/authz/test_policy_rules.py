"""Policy behaviour beyond single cells: blind evaluation (exhaustive), overlays and
demotion, the evaluator-removal variant (c16), API keys, check order, problems and
permission flags."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

import pytest

from app.authz import (
    Decision,
    IdeaFacts,
    ProjectFacts,
    Resource,
    Rule,
    authorize,
    can,
    idea_permissions,
    project_permissions,
    require,
    require_any,
    require_view,
)
from app.authz.policy import POLICY
from app.authz.rules import RULE_SCOPES, SESSION_ONLY_RULES
from app.domain.principal import ApiKeyScope, Principal
from app.errors import ProblemError
from app.models.enums import (
    EvaluatorState,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    ResearchStep,
)
from app.models.user import User

ME = uuid4()
OTHER = uuid4()
PROJECT = uuid4()

Column = Literal["PA", "PA+member", "PAd", "Mem", "Vwr", "NMi", "NMp", "Pub"]


def principal(
    *,
    platform_admin: bool = False,
    auth: Literal["session", "api_key"] = "session",
    scopes: set[ApiKeyScope] | None = None,
    projects: set[UUID] | None = None,
) -> Principal:
    user = User(id=ME, email="me@example.com", display_name="Me")
    user.is_platform_admin = platform_admin
    return Principal(
        user=user,
        auth=auth,
        scopes=None if scopes is None else frozenset(scopes),
        project_ids=None if projects is None else frozenset(projects),
    )


def resource(
    *,
    role: ProjectRole | None = ProjectRole.MEMBER,
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE,
    archived: bool = False,
    allow_volunteer_owners: bool = True,
    status: IdeaStatus = IdeaStatus.EVALUATING,
    owner_id: UUID | None = None,
    submitted_by_id: UUID | None = OTHER,
    evaluation_closed: bool = False,
    my_evaluation: EvaluatorState | None = None,
    **extra: Any,
) -> Resource:
    return Resource(
        project=ProjectFacts(
            id=PROJECT,
            visibility=visibility,
            archived=archived,
            allow_volunteer_owners=allow_volunteer_owners,
        ),
        role=role,
        idea=IdeaFacts(
            id=uuid4(),
            status=status,
            owner_id=owner_id,
            submitted_by_id=submitted_by_id,
            evaluation_closed=evaluation_closed,
            my_evaluation=my_evaluation,
        ),
    ).replace(**extra)


def as_column(column: Column) -> tuple[Principal | None, dict[str, Any]]:
    """A principal and the resource fields that put it in ``column``."""
    match column:
        case "PA":
            return principal(platform_admin=True), {"role": None}
        case "PA+member":
            return principal(platform_admin=True), {"role": ProjectRole.MEMBER}
        case "PAd":
            return principal(), {"role": ProjectRole.ADMIN}
        case "Mem":
            return principal(), {"role": ProjectRole.MEMBER}
        case "Vwr":
            return principal(), {"role": ProjectRole.VIEWER}
        case "NMi":
            return principal(), {"role": None, "visibility": ProjectVisibility.INTERNAL}
        case "NMp":
            return principal(), {"role": None}
        case "Pub":
            return None, {"role": None, "visibility": ProjectVisibility.INTERNAL}
    raise AssertionError(column)


# --- Blind evaluation: exhaustive -----------------------------------------------------------
BLIND_RULES = (Rule.SCORE_VIEW_AGGREGATE, Rule.EVALUATION_VIEW_OTHERS)
COLUMNS: tuple[Column, ...] = ("PA", "PA+member", "PAd", "Mem", "Vwr", "NMi", "NMp", "Pub")


@pytest.mark.parametrize("rule", BLIND_RULES)
@pytest.mark.parametrize("column", COLUMNS)
@pytest.mark.parametrize("my_evaluation", [None, *EvaluatorState])
@pytest.mark.parametrize("is_owner", [False, True])
@pytest.mark.parametrize("evaluation_closed", [False, True])
@pytest.mark.parametrize("status", [IdeaStatus.EVALUATING, IdeaStatus.CLOSED])
def test_blind_rules(
    rule: Rule,
    column: Column,
    my_evaluation: EvaluatorState | None,
    is_owner: bool,
    evaluation_closed: bool,
    status: IdeaStatus,
) -> None:
    """Role matrix section 3: a pending evaluator (assigned, not submitted) sees no
    score data whatever their role, ownership, or the evaluation/idea state; everyone
    else who can view the idea sees it. Viewers and internal non-members holding an
    assignment (e.g. demoted evaluators) stay blind too."""
    who, facts = as_column(column)
    decision = authorize(
        who,
        rule,
        resource(
            my_evaluation=my_evaluation,
            owner_id=ME if is_owner else None,
            evaluation_closed=evaluation_closed,
            status=status,
            **facts,
        ),
    )

    if column == "Pub":
        assert (decision.status, decision.hidden) == (401, False)
    elif column == "NMp":
        assert (decision.status, decision.hidden) == (404, False)
    elif my_evaluation in (EvaluatorState.INVITED, EvaluatorState.DRAFT):
        assert not decision.allowed
        assert decision.hidden
    else:
        assert decision.allowed


@pytest.mark.parametrize("rule", BLIND_RULES)
def test_hidden_is_denied_by_require(rule: Rule) -> None:
    with pytest.raises(ProblemError) as raised:
        require(principal(), rule, resource(my_evaluation=EvaluatorState.DRAFT))

    assert raised.value.status == 403


def test_viewing_your_own_evaluation_is_never_blind() -> None:
    for state in (None, *EvaluatorState):
        assert can(principal(), Rule.EVALUATION_VIEW_OWN, resource(my_evaluation=state))


# --- Overlays -------------------------------------------------------------------------------
def test_owner_overlay_counts_only_with_member_or_admin_role() -> None:
    for role, expected in [
        (ProjectRole.MEMBER, True),
        (ProjectRole.ADMIN, True),
        (ProjectRole.VIEWER, False),
        (None, False),
    ]:
        facts = resource(role=role, owner_id=ME, visibility=ProjectVisibility.INTERNAL)
        assert can(principal(), Rule.IDEA_CHANGE_STATUS, facts) is expected, role


def test_evaluator_overlay_counts_only_with_member_or_admin_role() -> None:
    demoted = resource(role=ProjectRole.VIEWER, my_evaluation=EvaluatorState.DRAFT)

    decision = authorize(principal(), Rule.EVALUATION_SUBMIT_OWN, demoted)

    assert (decision.status, decision.code) == (403, "forbidden")
    assert can(
        principal(), Rule.EVALUATION_SUBMIT_OWN, resource(my_evaluation=EvaluatorState.INVITED)
    )


def test_platform_admin_needs_a_role_for_overlays_but_not_for_admin_rules() -> None:
    pa = principal(platform_admin=True)
    assigned = resource(role=None, my_evaluation=EvaluatorState.INVITED)

    assert not can(pa, Rule.EVALUATION_SUBMIT_OWN, assigned)
    assert can(pa, Rule.EVALUATION_SUBMIT_OWN, assigned.replace(role=ProjectRole.MEMBER))
    assert can(pa, Rule.IDEA_CHANGE_STATUS, assigned)


def test_admin_evaluator_submits_through_the_overlay_only() -> None:
    assert not can(principal(), Rule.EVALUATION_SUBMIT_OWN, resource(role=ProjectRole.ADMIN))
    assert can(
        principal(),
        Rule.EVALUATION_SUBMIT_OWN,
        resource(role=ProjectRole.ADMIN, my_evaluation=EvaluatorState.INVITED),
    )


# --- Several grants: the failure that got furthest wins -------------------------------------
def test_owner_of_a_closed_idea_hears_idea_closed() -> None:
    decision = authorize(
        principal(), Rule.IDEA_EDIT_ANY, resource(owner_id=ME, status=IdeaStatus.CLOSED)
    )

    assert (decision.status, decision.code) == (409, "idea_closed")


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        # The submitter while new; not new -> 409 idea_not_new.
        ({"submitted_by_id": ME, "status": IdeaStatus.NEW}, None),
        ({"submitted_by_id": ME, "status": IdeaStatus.EVALUATING}, (409, "idea_not_new")),
        # The owner while not closed; closed -> 409 idea_closed.
        ({"owner_id": ME, "status": IdeaStatus.SHORTLISTED}, None),
        ({"owner_id": ME, "status": IdeaStatus.CLOSED}, (409, "idea_closed")),
        # Admins always.
        ({"role": ProjectRole.ADMIN, "status": IdeaStatus.CLOSED}, None),
        # Anyone else with view access: 403 not_submitter.
        ({}, (403, "not_submitter")),
        ({"role": ProjectRole.VIEWER, "submitted_by_id": ME}, (403, "forbidden")),
        # Can't see it: 404.
        ({"role": None}, (404, "not_found")),
    ],
)
def test_update_idea_combines_edit_own_and_edit_any(
    facts: dict[str, Any], expected: tuple[int, str] | None
) -> None:
    """Contract section 3.2, via ``require_any``."""
    rules = (Rule.IDEA_EDIT_OWN, Rule.IDEA_EDIT_ANY)
    if expected is None:
        assert require_any(principal(), rules, resource(**facts)) in rules
        return
    with pytest.raises(ProblemError) as raised:
        require_any(principal(), rules, resource(**facts))
    assert (raised.value.status, raised.value.code) == expected


# --- evaluator.manage: the removal variant (contract 3.5) -----------------------------------
REMOVERS: dict[str, tuple[bool, ProjectRole, UUID | None]] = {
    # who: (platform admin, role, owner)
    "owner": (False, ProjectRole.MEMBER, ME),
    "admin": (False, ProjectRole.ADMIN, None),
    "platform": (True, ProjectRole.MEMBER, None),
    "member": (False, ProjectRole.MEMBER, None),
}


@pytest.mark.parametrize(
    ("who", "facts", "expected"),
    [
        ("owner", {}, "allow"),
        ("admin", {}, "allow"),
        ("platform", {}, "allow"),
        # Not c6: removing works when evaluation or the idea is closed.
        ("owner", {"evaluation_closed": True}, "allow"),
        ("admin", {"status": IdeaStatus.CLOSED}, "allow"),
        # c16: never yourself, not even an admin or an owner who is pending.
        (
            "owner",
            {"evaluator_to_remove": ME, "my_evaluation": EvaluatorState.DRAFT},
            "403 cannot_remove_self",
        ),
        ("admin", {"evaluator_to_remove": ME}, "403 cannot_remove_self"),
        ("platform", {"evaluator_to_remove": ME}, "403 cannot_remove_self"),
        ("member", {}, "403 forbidden"),
        ("admin", {"archived": True}, "409 project_archived"),
    ],
)
def test_removing_an_evaluator(who: str, facts: dict[str, Any], expected: str) -> None:
    platform_admin, role, owner = REMOVERS[who]
    merged: dict[str, Any] = {"evaluator_to_remove": OTHER, "role": role, "owner_id": owner}

    decision = authorize(
        principal(platform_admin=platform_admin),
        Rule.EVALUATOR_MANAGE,
        resource(**(merged | facts)),
    )

    assert ("allow" if decision.allowed else f"{decision.status} {decision.code}") == expected


def test_inviting_evaluators_needs_open_evaluation_and_eligible_users() -> None:
    admin = resource(role=ProjectRole.ADMIN)
    viewer_invitee = admin.replace(assignee_roles=(ProjectRole.MEMBER, ProjectRole.VIEWER))
    closed = resource(role=ProjectRole.ADMIN, evaluation_closed=True)

    assert can(principal(), Rule.EVALUATOR_MANAGE, admin)
    assert authorize(principal(), Rule.EVALUATOR_MANAGE, viewer_invitee).code == (
        "assignee_not_eligible"
    )
    # 422 (body) comes before 409 (state).
    assert (
        authorize(principal(), Rule.EVALUATOR_MANAGE, closed.replace(assignee_roles=(None,))).code
        == "assignee_not_eligible"
    )
    assert authorize(principal(), Rule.EVALUATOR_MANAGE, closed).code == "evaluation_closed"


# --- API keys (role matrix section 5) -------------------------------------------------------
def test_every_rule_is_either_scoped_session_only_or_public() -> None:
    scoped = set(RULE_SCOPES)
    public = {Rule.PUBLIC_SUBMIT, Rule.PUBLIC_TRACK, Rule.SELF_UNSUBSCRIBE}

    assert scoped | SESSION_ONLY_RULES | public == set(POLICY)
    assert not scoped & SESSION_ONLY_RULES
    assert {
        Rule.PROJECT_CREATE,
        Rule.PROJECT_MANAGE_MEMBERS,
        Rule.PROJECT_EDIT_RUBRIC,
        Rule.PROJECT_RENAME_STATUS_LABELS,
        Rule.PROJECT_EDIT_SETTINGS,
        Rule.PUBLIC_ERASE_SUBMITTER,
        Rule.SELF_MANAGE_PROFILE,
        Rule.API_KEY_MANAGE_OWN,
        Rule.API_KEY_MANAGE_ANY,
    } <= SESSION_ONLY_RULES


def _fits_everything(rule: Rule) -> Resource:
    """A state where a platform admin who is also a project admin and the idea's
    owner and a pending evaluator passes every rule's conditions."""
    return resource(
        role=ProjectRole.ADMIN,
        owner_id=None if rule is Rule.IDEA_VOLUNTEER_OWNER else ME,
        status=IdeaStatus.SHORTLISTED,
        my_evaluation=None if rule not in {Rule.EVALUATION_SUBMIT_OWN} else EvaluatorState.INVITED,
        comment_author_id=ME,
        admins_after_change=1,
        ai_available=True,
        assignee_roles=(ProjectRole.MEMBER,),
    )


KEY_RULES = sorted((rule for rule, spec in POLICY.items() if spec.scope.value != "public"), key=str)


@pytest.mark.parametrize("rule", KEY_RULES)
@pytest.mark.parametrize("scope", ["read", "write", "evaluate", "mcp"])
def test_each_scope_alone(rule: Rule, scope: ApiKeyScope) -> None:
    key = principal(platform_admin=True, auth="api_key", scopes={scope})
    decision = authorize(key, rule, _fits_everything(rule).replace(evaluator_to_remove=None))

    if RULE_SCOPES.get(rule) == scope:
        assert decision.allowed, decision
    else:
        assert (decision.status, decision.code) == (403, "insufficient_scope")


@pytest.mark.parametrize("rule", sorted(SESSION_ONLY_RULES, key=str))
def test_session_only_rules_refuse_every_key(rule: Rule) -> None:
    key = principal(
        platform_admin=True, auth="api_key", scopes={"read", "write", "evaluate", "mcp"}
    )

    assert authorize(key, rule, _fits_everything(rule)).code == "insufficient_scope"
    assert can(principal(platform_admin=True), rule, _fits_everything(rule))


def test_project_restricted_key_is_404_elsewhere() -> None:
    elsewhere = principal(auth="api_key", scopes={"read", "write"}, projects={uuid4()})
    here = principal(auth="api_key", scopes={"read", "write"}, projects={PROJECT})

    assert authorize(elsewhere, Rule.IDEA_VIEW, resource()).status == 404
    assert authorize(elsewhere, Rule.IDEA_CREATE, resource()).status == 404
    assert can(here, Rule.IDEA_VIEW, resource())
    assert can(here, Rule.IDEA_CREATE, resource())


def test_key_acts_with_its_owners_live_role() -> None:
    key = principal(auth="api_key", scopes={"read", "write"})

    assert can(key, Rule.IDEA_CREATE, resource(role=ProjectRole.MEMBER))
    # The owner was demoted after the key was created: the key loses the right too.
    assert authorize(key, Rule.IDEA_CREATE, resource(role=ProjectRole.VIEWER)).status == 403
    assert authorize(key, Rule.IDEA_VIEW, resource(role=None)).status == 404


def test_the_implied_view_is_the_owners_but_loading_needs_read() -> None:
    """Inside a rule the implied view is the owner's (the rule's scope decides); a route
    that loads an idea to read it (``require_view``) needs ``read`` too, so a key with
    only ``mcp`` reads nothing through REST (contract-phase5 section 3.3). Keys with
    ``write`` or ``evaluate`` always have ``read`` (section 3.1)."""
    write_only = principal(auth="api_key", scopes={"write"})
    mcp_only = principal(auth="api_key", scopes={"mcp"})
    read = principal(auth="api_key", scopes={"read"})

    assert can(write_only, Rule.COMMENT_CREATE, resource())
    assert authorize(write_only, Rule.IDEA_VIEW, resource()).code == "insufficient_scope"
    for key in (write_only, mcp_only):
        with pytest.raises(ProblemError) as refused:
            require_view(key, resource())
        assert (refused.value.status, refused.value.code) == (403, "insufficient_scope")
    require_view(read, resource())
    require_view(principal(), resource())
    with pytest.raises(ProblemError) as hidden:  # 404 before the scope
        require_view(mcp_only, resource(role=None))
    assert hidden.value.status == 404


def test_mcp_connect() -> None:
    assert authorize(principal(), Rule.MCP_CONNECT).status == 401  # no key
    assert authorize(None, Rule.MCP_CONNECT).status == 401
    assert authorize(principal(auth="api_key", scopes={"read"}), Rule.MCP_CONNECT).code == (
        "insufficient_scope"
    )
    assert can(principal(auth="api_key", scopes={"mcp"}), Rule.MCP_CONNECT)


# --- Check order and defaults ---------------------------------------------------------------
def test_anonymous_is_401_before_anything_else() -> None:
    for rule, spec in POLICY.items():
        if spec.scope.value == "public":
            continue
        assert authorize(None, rule, resource(role=None)).status == 401, rule


def test_not_viewable_is_404_before_403_and_409() -> None:
    hidden = resource(role=None, archived=True, status=IdeaStatus.CLOSED)

    for rule, spec in POLICY.items():
        if spec.scope.value in {"project", "idea"}:
            assert authorize(principal(), rule, hidden).status == 404, rule


def test_rule_outside_the_policy_is_denied() -> None:
    unknown = "idea.teleport"

    decision = authorize(principal(platform_admin=True), unknown, resource())  # type: ignore[arg-type]

    assert (decision.allowed, decision.status) == (False, 403)


def test_idea_rules_need_the_idea_facts() -> None:
    with pytest.raises(ValueError, match="idea"):
        authorize(principal(), Rule.IDEA_VIEW, Resource(project=resource().project))


@pytest.mark.parametrize(
    ("decision", "status", "code"),
    [
        (Decision(Rule.IDEA_VIEW, False, 404, "not_found"), 404, "not_found"),
        (Decision(Rule.IDEA_VIEW, False, 401, "unauthorized"), 401, "unauthorized"),
        (Decision(Rule.IDEA_EDIT_OWN, False, 403, "not_submitter"), 403, "not_submitter"),
        (Decision(Rule.EVALUATOR_MANAGE, False, 422, "assignee_not_eligible"), 422, None),
        (Decision(Rule.IDEA_EDIT_ANY, False, 409, "idea_closed"), 409, "idea_closed"),
    ],
)
def test_decision_problems(decision: Decision, status: int, code: str | None) -> None:
    problem = decision.problem()

    assert problem.status == status
    assert problem.code == (code or decision.code)
    assert problem.detail  # a human-readable sentence for the UI


# --- Permission flags -----------------------------------------------------------------------
def test_project_permissions() -> None:
    pa = principal(platform_admin=True)

    assert project_permissions(pa, resource(role=None)).model_dump() == {
        "can_manage": True,
        "can_create_ideas": True,  # without a role: permissions, not my_role
    }
    assert project_permissions(principal(), resource(role=ProjectRole.MEMBER)).model_dump() == {
        "can_manage": False,
        "can_create_ideas": True,
    }
    assert project_permissions(principal(), resource(role=ProjectRole.ADMIN, archived=True)) == (
        project_permissions(principal(), resource(role=ProjectRole.ADMIN)).model_copy(
            update={"can_create_ideas": False}
        )
    )


def test_idea_permissions_for_the_owner() -> None:
    flags = idea_permissions(principal(), resource(owner_id=ME, status=IdeaStatus.EVALUATING))

    assert flags.model_dump() == {
        "can_change_status": True,
        "can_edit": True,
        "can_assign_owner": False,
        "can_release_owner": True,
        "can_volunteer": False,
        "can_invite_evaluators": True,
        "can_remove_evaluators": True,
        "can_evaluate": False,
        "can_close_evaluation": True,
        "can_comment": True,
        "can_vote": True,
        "can_delete": False,
        "can_answer_research": False,  # the project's research step is off
        "invite_blocked_by_research": False,
    }
    stepped = resource(owner_id=ME, status=IdeaStatus.NEW).replace(
        project=ProjectFacts(
            PROJECT, ProjectVisibility.PRIVATE, research_step=ResearchStep.BEFORE_EVALUATION
        )
    )
    assert idea_permissions(principal(), stepped).can_answer_research


def test_idea_permissions_are_all_false_in_an_archived_project() -> None:
    admin = resource(role=ProjectRole.ADMIN, owner_id=ME, my_evaluation=EvaluatorState.INVITED)

    flags = idea_permissions(
        principal(platform_admin=True),
        admin.replace(project=ProjectFacts(PROJECT, ProjectVisibility.PRIVATE, archived=True)),
    )

    assert not any(flags.model_dump().values())


def test_idea_permissions_after_evaluation_closes() -> None:
    evaluator = resource(my_evaluation=EvaluatorState.DRAFT, evaluation_closed=True)
    owner = resource(owner_id=ME, evaluation_closed=True)

    assert not idea_permissions(principal(), evaluator).can_evaluate
    flags = idea_permissions(principal(), owner)
    assert not flags.can_invite_evaluators
    assert flags.can_remove_evaluators  # releasing blind evaluators still works


@pytest.mark.parametrize("role", [ProjectRole.MEMBER, ProjectRole.VIEWER])
@pytest.mark.parametrize("volunteering", [True, False])
@pytest.mark.parametrize("owner", [None, OTHER])
def test_volunteer_flag(role: ProjectRole, volunteering: bool, owner: UUID | None) -> None:
    facts = resource(role=role, owner_id=owner, allow_volunteer_owners=volunteering)

    flag = idea_permissions(principal(), facts).can_volunteer

    assert flag == (role is ProjectRole.MEMBER and volunteering and owner is None)


# --- Platform admins changing users' access: c17 and c18 (contract-phase2 section 3.4) ------
@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({}, "allow"),  # not an access change: c17 and c18 don't apply
        ({"user_to_change": OTHER}, "allow"),
        ({"user_to_change": OTHER, "platform_admins_after_change": 1}, "allow"),
        ({"user_to_change": OTHER, "platform_admins_after_change": 0}, "409 last_platform_admin"),
        ({"user_to_change": ME}, "403 cannot_change_self"),
        # c17 (403) before c18 (409).
        ({"user_to_change": ME, "platform_admins_after_change": 0}, "403 cannot_change_self"),
    ],
)
def test_changing_a_users_access(facts: dict[str, Any], expected: str) -> None:
    decision = authorize(
        principal(platform_admin=True), Rule.PLATFORM_MANAGE_USERS, Resource().replace(**facts)
    )

    assert ("allow" if decision.allowed else f"{decision.status} {decision.code}") == expected
    if not decision.allowed:
        assert decision.condition == ("c17" if decision.status == 403 else "c18")


@pytest.mark.parametrize("column", ["PAd", "Mem", "Vwr", "NMi", "NMp"])
def test_only_platform_admins_change_access(column: Column) -> None:
    who, _ = as_column(column)

    decision = authorize(who, Rule.PLATFORM_MANAGE_USERS, Resource(user_to_change=OTHER))

    assert (decision.status, decision.code) == (403, "forbidden")


def test_access_change_problems() -> None:
    admin = principal(platform_admin=True)

    with pytest.raises(ProblemError) as self_change:
        require(admin, Rule.PLATFORM_MANAGE_USERS, Resource(user_to_change=ME))
    with pytest.raises(ProblemError) as last:
        require(
            admin,
            Rule.PLATFORM_MANAGE_USERS,
            Resource(user_to_change=OTHER, platform_admins_after_change=0),
        )

    assert (self_change.value.status, self_change.value.code) == (403, "cannot_change_self")
    assert (last.value.status, last.value.code) == (409, "last_platform_admin")
    assert self_change.value.detail
    assert last.value.detail


def test_access_change_is_session_only() -> None:
    key = principal(platform_admin=True, auth="api_key", scopes={"read", "write"})

    decision = authorize(key, Rule.PLATFORM_MANAGE_USERS, Resource(user_to_change=OTHER))

    assert (decision.status, decision.code) == (403, "insufficient_scope")


# --- Phase 8: c7 with the research step (role matrix c7) --------------------------------------
@pytest.mark.parametrize(
    "rule", [Rule.PROPOSAL_WRITE, Rule.PROPOSAL_SUGGEST_SECTION, Rule.AI_DRAFT_SECTION]
)
@pytest.mark.parametrize(
    ("step", "allowed"),
    [
        (ResearchStep.BEFORE_PROPOSAL, True),  # "Start proposal" is the next step there
        (ResearchStep.BEFORE_EVALUATION, False),
        (ResearchStep.OFF, False),
    ],
)
def test_c7_allows_research_only_before_a_proposal_step(
    rule: Rule, step: ResearchStep, allowed: bool
) -> None:
    facts = resource(role=ProjectRole.ADMIN, status=IdeaStatus.RESEARCH, ai_available=True)
    facts = facts.replace(
        project=ProjectFacts(PROJECT, ProjectVisibility.PRIVATE, research_step=step)
    )

    decision = authorize(principal(), rule, facts)

    assert decision.allowed is allowed
    if not allowed:
        assert (decision.status, decision.code, decision.condition) == (
            409,
            "proposal_not_available",
            "c7",
        )


def test_answering_and_overriding_follow_table_k() -> None:
    owner = resource(owner_id=ME, status=IdeaStatus.RESEARCH)
    admin = resource(role=ProjectRole.ADMIN, status=IdeaStatus.RESEARCH)
    member = resource(status=IdeaStatus.RESEARCH)

    assert can(principal(), Rule.IDEA_ANSWER_RESEARCH, owner)
    assert not can(principal(), Rule.IDEA_RESEARCH_OVERRIDE, owner)  # owners never skip it
    assert can(principal(), Rule.IDEA_RESEARCH_OVERRIDE, admin)
    assert authorize(principal(), Rule.IDEA_ANSWER_RESEARCH, member).code == "forbidden"
    closed = resource(owner_id=ME, status=IdeaStatus.CLOSED)
    assert authorize(principal(), Rule.IDEA_ANSWER_RESEARCH, closed).code == "idea_closed"
    key = principal(auth="api_key", scopes={"read", "write"})
    assert can(key, Rule.IDEA_ANSWER_RESEARCH, owner)
    assert authorize(key, Rule.IDEA_RESEARCH_OVERRIDE, admin).code == "insufficient_scope"
