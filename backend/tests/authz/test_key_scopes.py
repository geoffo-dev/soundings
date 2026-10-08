"""Role matrix section 5, exhaustively: **effective permission = the owner's live
permission ∩ the key's scopes ∩ the key's projects** (contract-phase5 sections 3.3 and
3.8 "Scopes", "Owner roles").

For every rule, every principal column and overlay (in the state where the cell's
conditions hold, and with each condition broken), every non-empty set of scopes and
every kind of project restriction, a key's decision must equal the session decision
narrowed as section 5 says: a project outside the key's restriction is 404 first, a
hidden resource stays 404, then a rule the scopes don't grant (or a session-only rule)
is 403 ``insufficient_scope``, and otherwise the key gets exactly the owner's answer
(blind evaluation included). Then c20, c21 and c4 for service accounts.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Literal
from uuid import UUID, uuid4

import pytest

from app.authz import (
    POLICY,
    Decision,
    IdeaFacts,
    ProjectFacts,
    Resource,
    Rule,
    authorize,
    can,
    idea_permissions,
    project_permissions,
)
from app.authz.policy import Scope
from app.authz.rules import RULE_SCOPES, SESSION_ONLY_RULES
from app.domain.principal import ApiKeyScope, Principal
from app.models.enums import EvaluatorState, IdeaStatus, ProjectRole, ProjectVisibility
from app.models.user import User
from tests.authz.test_policy_matrix import (
    BREAKS,
    COLUMNS,
    CONDITION_CASES,
    State,
    happy_state,
)

SCOPES: tuple[ApiKeyScope, ...] = ("read", "write", "evaluate", "mcp")
SCOPE_SETS = [
    frozenset(combination)
    for size in range(1, len(SCOPES) + 1)
    for combination in itertools.combinations(SCOPES, size)
]
Restriction = Literal["none", "inside", "outside", "empty"]
RESTRICTIONS: tuple[Restriction, ...] = ("none", "inside", "outside", "empty")
KEY_RULES = sorted(rule for rule, spec in POLICY.items() if spec.scope is not Scope.PUBLIC)
SIGNED_IN_COLUMNS = [column for column in COLUMNS if column != "Pub"]

Outcome = tuple[bool, bool, int, str]  # allowed, hidden, status, code


def _outcome(decision: Decision) -> Outcome:
    return (decision.allowed, decision.hidden, decision.status, decision.code)


def _key(
    state: State, scopes: frozenset[ApiKeyScope], restriction: Restriction
) -> tuple[Principal, Resource]:
    principal, resource = state.build()
    assert principal is not None
    assert resource.project is not None
    project_ids: frozenset[UUID] | None = {
        "none": None,
        "inside": frozenset({resource.project.id}),
        "outside": frozenset({uuid4()}),
        "empty": frozenset(),
    }[restriction]
    key = Principal(
        user=principal.user,
        auth="api_key",
        scopes=scopes,
        project_ids=project_ids,
        api_key_id=uuid4(),
    )
    return key, resource


def expected(
    rule: Rule,
    session: Decision,
    scopes: frozenset[ApiKeyScope],
    restriction: Restriction,
) -> Outcome:
    """Section 5 applied to the session decision."""
    spec = POLICY[rule]
    if rule is Rule.MCP_CONNECT:  # c15: only a key with the mcp scope
        return (
            (True, False, 200, "ok")
            if "mcp" in scopes
            else (False, False, 403, "insufficient_scope")
        )
    if spec.scope in (Scope.PROJECT, Scope.IDEA) and restriction in ("outside", "empty"):
        return (False, False, 404, "not_found")
    if session.status == 404:
        return (False, False, 404, "not_found")
    scope = RULE_SCOPES.get(rule)
    if scope is None or scope not in scopes:
        return (False, False, 403, "insufficient_scope")
    return _outcome(session)


def _check(rule: Rule, state: State, label: str, mismatches: list[str]) -> None:
    principal, resource = replace(state, auth="session", scopes=None).build()
    session = authorize(principal, rule, resource)
    for scopes in SCOPE_SETS:
        for restriction in RESTRICTIONS:
            key, key_resource = _key(state, scopes, restriction)
            got = _outcome(authorize(key, rule, key_resource))
            want = expected(rule, session, scopes, restriction)
            if got != want:
                mismatches.append(
                    f"{rule} {label} scopes={sorted(scopes)} restriction={restriction}: "
                    f"got {got}, want {want}"
                )


@pytest.mark.parametrize("rule", KEY_RULES, ids=str)
def test_a_key_is_the_owners_permission_narrowed_by_scopes_and_projects(rule: Rule) -> None:
    mismatches: list[str] = []
    for column in SIGNED_IN_COLUMNS:
        state = happy_state(str(rule), column)
        if rule is Rule.MCP_CONNECT:
            state = replace(state, auth="session", scopes=None)
        _check(rule, state, column, mismatches)
        # Blind evaluation: the same principal as a pending evaluator (invited, draft)
        # and after submitting, whatever the column.
        for evaluation in (EvaluatorState.INVITED, EvaluatorState.DRAFT, EvaluatorState.SUBMITTED):
            _check(
                rule, replace(state, my_evaluation=evaluation), f"{column}+{evaluation}", mismatches
            )

    assert mismatches == []


CONDITION_RULES = sorted(
    {
        rule
        for rule, _, condition, _ in CONDITION_CASES
        if condition != "c15" and Rule(rule) in KEY_RULES
    }
)


@pytest.mark.parametrize("rule", CONDITION_RULES)
def test_every_broken_condition_answers_a_key_as_it_answers_the_owner(rule: str) -> None:
    mismatches: list[str] = []
    for case_rule, column, condition, how in CONDITION_CASES:
        if case_rule != rule or condition == "c15" or column == "Pub":
            continue
        state = BREAKS[condition][how](happy_state(rule, column), rule)
        _check(Rule(rule), state, f"{column} {condition}:{how}", mismatches)

    assert mismatches == []


# --- Scopes and session-only rules, directly ----------------------------------------------------
def test_scopes_grant_exactly_the_documented_rules() -> None:
    """Role matrix section 5's table (``idea.delete`` and ``idea.moderate`` are session
    only)."""
    by_scope: dict[str, set[str]] = {scope: set() for scope in SCOPES}
    for rule, scope in RULE_SCOPES.items():
        by_scope[scope].add(str(rule))

    assert by_scope["read"] == {
        "project.view",
        "idea.view",
        "user.search",
        "evaluation.view_own",
        "evaluation.view_others",
        "score.view_aggregate",
        "proposal.view",
        "proposal.export",
    }
    assert by_scope["evaluate"] == {"evaluation.submit_own"}
    assert by_scope["mcp"] == {"mcp.connect"}
    assert by_scope["write"] == {
        "idea.create",
        "idea.edit_own",
        "idea.edit_any",
        "comment.create",
        "comment.edit_own",
        "comment.delete_any",
        "idea.vote",
        "idea.watch",
        "idea.volunteer_owner",
        "idea.release_owner",
        "idea.assign_owner",
        "evaluator.manage",
        "idea.set_due_date",
        "evaluation.close",
        "evaluation.include_ai",
        "idea.change_status",
        "proposal.write",
        "proposal.comment",
        "proposal.suggest_section",
        "ai.request_evaluation",
        "ai.research",
        "ai.draft_section",
        "ai.cancel_run",
        "ai.delete_note",
        "idea.answer_research",  # Phase 8
    }
    assert {str(rule) for rule in SESSION_ONLY_RULES} == {
        "project.create",
        "project.manage_members",
        "project.edit_rubric",
        "project.rename_status_labels",
        "project.edit_settings",
        "public.erase_submitter",
        "idea.delete",
        "idea.moderate",
        "platform.manage_users",
        "platform.manage_groups",
        "platform.configure_sso",
        "platform.configure_email",
        "platform.edit_branding",
        "platform.manage_agents",
        "platform.view_audit_log",
        "api_key.manage_any",
        "api_key.manage_own",
        "self.manage_profile",
        # Phase 8: project settings, and "Move anyway" (a key's override is refused)
        "project.edit_proposal_template",
        "project.edit_research",
        "idea.research_override",
    }


@pytest.mark.parametrize("rule", sorted(SESSION_ONLY_RULES, key=str), ids=str)
@pytest.mark.parametrize("column", ["PA", "PAd", "+Own"])
def test_session_only_rules_refuse_a_key_with_every_scope(rule: Rule, column: str) -> None:
    state = happy_state(str(rule), column)
    if rule is Rule.IDEA_MODERATE or rule is Rule.IDEA_DELETE:
        state = replace(state, status=IdeaStatus.NEW)
    principal, resource = state.build()
    key, key_resource = _key(state, frozenset(SCOPES), "none")

    if can(principal, rule, resource):  # the owner may: the key still may not
        decision = authorize(key, rule, key_resource)
        assert (decision.status, decision.code) == (403, "insufficient_scope")


# --- Permission flags reflect the key ---------------------------------------------------------
def _user(**flags: bool) -> User:
    user = User(id=uuid4(), email="me@example.com", display_name="Me")
    for name, value in flags.items():
        setattr(user, name, value)
    return user


def _idea_resource(user: User, **idea: object) -> Resource:
    return Resource(
        project=ProjectFacts(id=uuid4(), visibility=ProjectVisibility.PRIVATE),
        role=ProjectRole.ADMIN,
        idea=IdeaFacts(id=uuid4(), status=IdeaStatus.NEW, submitted_by_id=user.id, **idea),  # type: ignore[arg-type]
    )


def test_permission_flags_are_computed_for_the_key() -> None:
    user = _user()
    resource = _idea_resource(user)
    session = Principal(user=user)
    read = Principal(user=user, auth="api_key", scopes=frozenset({"read"}))
    full = Principal(user=user, auth="api_key", scopes=frozenset(SCOPES))

    assert idea_permissions(session, resource).can_edit is True
    assert idea_permissions(session, resource).can_delete is True
    assert idea_permissions(read, resource).can_edit is False
    assert idea_permissions(read, resource).can_comment is False
    assert idea_permissions(full, resource).can_edit is True
    assert idea_permissions(full, resource).can_delete is False  # idea.delete: session only
    assert project_permissions(full, resource).can_manage is False
    assert project_permissions(full, resource).can_create_ideas is True


# --- c20: the break-glass account doesn't create keys -------------------------------------------
def test_c20_refuses_the_break_glass_account_when_issuing_a_key() -> None:
    glass = Principal(user=_user(is_platform_admin=True, is_break_glass=True))
    person = Principal(user=_user(is_platform_admin=True))
    issuing = Resource(issuing_api_key=True)

    denied = authorize(glass, Rule.API_KEY_MANAGE_OWN, issuing)
    agents = authorize(glass, Rule.PLATFORM_MANAGE_AGENTS, issuing)

    assert (denied.status, denied.code, denied.condition) == (403, "break_glass_account", "c20")
    assert denied.problem().detail
    assert (agents.status, agents.code) == (403, "break_glass_account")
    assert can(glass, Rule.API_KEY_MANAGE_OWN)  # listing and revoking aren't issuing
    assert can(person, Rule.API_KEY_MANAGE_OWN, issuing)
    assert can(person, Rule.PLATFORM_MANAGE_AGENTS, issuing)


def test_c20_comes_after_the_key_scope_check() -> None:
    key = Principal(user=_user(is_break_glass=True), auth="api_key", scopes=frozenset(SCOPES))

    decision = authorize(key, Rule.API_KEY_MANAGE_OWN, Resource(issuing_api_key=True))

    assert decision.code == "insufficient_scope"


# --- c21 and c4: service accounts never own an idea ---------------------------------------------
@pytest.mark.parametrize("role", [ProjectRole.ADMIN, ProjectRole.MEMBER])
def test_c21_a_service_account_never_volunteers(role: ProjectRole) -> None:
    bot = _user(is_service_account=True)
    resource = Resource(
        project=ProjectFacts(id=uuid4(), visibility=ProjectVisibility.PRIVATE),
        role=role,
        idea=IdeaFacts(id=uuid4(), status=IdeaStatus.EVALUATING),
    )
    owned = resource.replace(
        idea=IdeaFacts(id=uuid4(), status=IdeaStatus.EVALUATING, owner_id=uuid4())
    )

    for principal in (
        Principal(user=bot),
        Principal(user=bot, auth="api_key", scopes=frozenset({"read", "write"})),
    ):
        decision = authorize(principal, Rule.IDEA_VOLUNTEER_OWNER, resource)
        assert (decision.status, decision.code, decision.condition) == (403, "forbidden", "c21")
        # 403 before the 409s (c13: the idea already has an owner).
        assert authorize(principal, Rule.IDEA_VOLUNTEER_OWNER, owned).condition == "c21"
    assert can(Principal(user=_user()), Rule.IDEA_VOLUNTEER_OWNER, resource)


def test_c4_refuses_a_service_account_as_owner_but_not_as_evaluator() -> None:
    admin = Principal(user=_user())
    resource = Resource(
        project=ProjectFacts(id=uuid4(), visibility=ProjectVisibility.PRIVATE),
        role=ProjectRole.ADMIN,
        idea=IdeaFacts(id=uuid4(), status=IdeaStatus.EVALUATING),
        assignee_roles=(ProjectRole.MEMBER,),
    )
    bot = resource.replace(assignee_service_account=True)

    owner = authorize(admin, Rule.IDEA_ASSIGN_OWNER, bot)

    assert (owner.status, owner.code, owner.condition) == (422, "assignee_not_eligible", "c4")
    assert can(admin, Rule.IDEA_ASSIGN_OWNER, resource)
    assert can(admin, Rule.EVALUATOR_MANAGE, bot)  # an agent may evaluate
