"""Phase 10: bid access in the policy (role matrix table M, section 3a, c28-c30), beyond
the row-by-row matrix test (``test_policy_matrix.py``).

* The **+Asr** overlay in every column it can be added to (PA to NMi), and never in NMp,
  for a guest researcher (column R; review M6), an AI agent or the break-glass account.
* c29 per section (another section: 403 ``not_section_assessor``; the price section for
  ``bid.view_price``).
* Section 3a: a pending assessor of (bid, section) is blind for it whatever their role (a
  call manager who assesses too), not after submitting; agents always.
* c30: an awarded call is deleted by platform admins only.
* The idea evaluation's blind rule (✱ of table D) never hides bid data, and the bid rule
  never hides evaluations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4

import pytest

from app.authz import (
    BidCallFacts,
    Decision,
    IdeaFacts,
    ProjectFacts,
    Resource,
    Rule,
    authorize,
    bid_call_flags,
)
from app.domain.principal import ApiKeyScope, Principal
from app.models.enums import (
    BidCallStatus,
    EvaluatorState,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    ResearchStep,
)
from app.models.user import User

ME = uuid4()
OWNER = uuid4()
TECHNICAL = uuid4()
COMMERCIAL = uuid4()  # holds the price question

Column = Literal["PA", "PAd", "Mem", "Vwr", "NMi", "NMp", "R"]


@dataclass(frozen=True)
class Who:
    column: Column
    sections: frozenset[UUID] = frozenset({TECHNICAL})
    service_account: bool = False
    break_glass: bool = False
    owner: bool = False
    auth: Literal["session", "api_key"] = "session"
    scopes: frozenset[ApiKeyScope] | None = None
    my_evaluation: EvaluatorState | None = None
    call_status: BidCallStatus = BidCallStatus.ASSESSING
    operation: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def build(self, **facts: object) -> tuple[Principal, Resource]:
        user = User(id=ME, email="me@example.com", display_name="Me")
        user.is_platform_admin = self.column == "PA"
        user.is_service_account = self.service_account
        user.is_break_glass = self.break_glass
        principal = Principal(
            user=user, auth=self.auth, scopes=self.scopes, operation=self.operation
        )
        role = {"PAd": ProjectRole.ADMIN, "Mem": ProjectRole.MEMBER, "Vwr": ProjectRole.VIEWER}
        visibility = (
            ProjectVisibility.INTERNAL if self.column == "NMi" else ProjectVisibility.PRIVATE
        )
        idea = IdeaFacts(
            id=uuid4(),
            status=IdeaStatus.PROPOSAL,
            owner_id=ME if self.owner else OWNER,
            submitted_by_id=OWNER,
            my_evaluation=self.my_evaluation,
            # Column R: the idea's live researcher without a role in its private project.
            researcher_id=ME if self.column == "R" else None,
        )
        resource = Resource(
            project=ProjectFacts(uuid4(), visibility, research_step=ResearchStep.BEFORE_EVALUATION),
            role=role.get(self.column),
            idea=idea,
            ai_available=True,
            bid_call=BidCallFacts(
                id=uuid4(),
                status=self.call_status,
                my_section_ids=self.sections,
                price_section_id=COMMERCIAL,
            ),
            bid_section_id=TECHNICAL,
        )
        return principal, resource.replace(**{**self.extra, **facts})


def decide(who: Who, rule: Rule, **facts: object) -> Decision:
    principal, resource = who.build(**facts)
    return authorize(principal, rule, resource)


def outcome(decision: Decision) -> str:
    if decision.hidden:
        return "hidden"
    return "allow" if decision.allowed else f"{decision.status} {decision.code}"


ASSESSOR_RULES = (Rule.BID_VIEW_BIDS, Rule.BID_VIEW_OWN_ASSESSMENT, Rule.BID_ASSESS)


# --- +Asr: who it is added to -------------------------------------------------------------
@pytest.mark.parametrize("column", ["PA", "PAd", "Mem", "Vwr", "NMi"])
@pytest.mark.parametrize("rule", ASSESSOR_RULES, ids=str)
def test_an_assessor_in_any_column_from_pa_to_nmi_assesses(column: Column, rule: Rule) -> None:
    assert outcome(decide(Who(column), rule)) == "allow"
    # The same principal without the assignment: what the column alone gives.
    alone = outcome(decide(Who(column, sections=frozenset()), rule))
    if rule is Rule.BID_VIEW_BIDS and column in ("PA", "PAd"):
        assert alone == "allow"  # call managers see the bids anyway
    else:
        assert alone == "403 forbidden"


@pytest.mark.parametrize(
    "rule", [*ASSESSOR_RULES, Rule.BID_VIEW_CALL, Rule.BID_VIEW_PRICE], ids=str
)
def test_a_private_projects_non_member_holds_nothing_through_an_assignment(rule: Rule) -> None:
    """c28 live (review M6): someone who left the private project is NMp: 404."""
    assert outcome(decide(Who("NMp"), rule)) == "404 not_found"


@pytest.mark.parametrize(
    "rule", [*ASSESSOR_RULES, Rule.BID_VIEW_CALL, Rule.BID_VIEW_PRICE], ids=str
)
def test_a_guest_researcher_holds_nothing_through_an_assignment(rule: Rule) -> None:
    """Column R is never +Asr: an assessor who left the private project but researches the
    idea gets nothing of the call (review M6, table L)."""
    assert outcome(decide(Who("R"), rule)) == "404 not_found"
    # ... also while a request is served (the guest route table hides every bid route).
    assert outcome(decide(Who("R", operation="get_bid"), rule)) == "404 not_found"
    # Without the assignment, R still sees the idea itself.
    assert decide(Who("R", sections=frozenset()), Rule.IDEA_VIEW).allowed


@pytest.mark.parametrize("rule", ASSESSOR_RULES, ids=str)
def test_an_agent_is_never_an_assessor(rule: Rule) -> None:
    """c28: never a service account, even with a role and an assignment row."""
    assert not decide(Who("Mem", service_account=True), rule).allowed


@pytest.mark.parametrize("rule", [Rule.BID_VIEW_OWN_ASSESSMENT, Rule.BID_ASSESS], ids=str)
def test_the_break_glass_account_is_never_an_assessor(rule: Rule) -> None:
    assert outcome(decide(Who("PA", break_glass=True), rule)) == "403 forbidden"


def test_an_assessor_does_not_manage_the_call() -> None:
    for rule in (
        Rule.BID_MANAGE,
        Rule.BID_UPLOAD_DOCUMENT,
        Rule.BID_DECIDE,
        Rule.BID_DELETE_CALL,
        Rule.BID_VIEW_SCORES,
        Rule.AI_ASSESS_BID,
    ):
        assert outcome(decide(Who("Mem"), rule)) == "403 forbidden", rule


def test_a_demoted_owner_is_no_call_manager() -> None:
    """+Own counts only with member or admin (section 1)."""
    assert decide(Who("Mem", owner=True, sections=frozenset()), Rule.BID_MANAGE).allowed
    assert outcome(decide(Who("Vwr", owner=True, sections=frozenset()), Rule.BID_MANAGE)) == (
        "403 forbidden"
    )


# --- c29: the section in question ------------------------------------------------------------
@pytest.mark.parametrize(
    "rule", [Rule.BID_VIEW_OWN_ASSESSMENT, Rule.BID_ASSESS, Rule.BID_VIEW_SECTION_SCORES], ids=str
)
def test_another_section_is_not_section_assessor(rule: Rule) -> None:
    decision = decide(Who("Mem"), rule, bid_section_id=COMMERCIAL, bid_section_submitted=True)

    assert outcome(decision) == "403 not_section_assessor"
    assert decision.condition == "c29"


def test_no_section_named_fails_c29() -> None:
    assert outcome(decide(Who("Mem"), Rule.BID_ASSESS, bid_section_id=None)) == (
        "403 not_section_assessor"
    )


def test_prices_are_for_the_price_sections_assessors() -> None:
    assert outcome(decide(Who("Mem"), Rule.BID_VIEW_PRICE)) == "403 not_section_assessor"
    assert decide(Who("Mem", sections=frozenset({TECHNICAL, COMMERCIAL})), Rule.BID_VIEW_PRICE)
    # Call managers see prices without assessing anything.
    for who in (Who("PA", sections=frozenset()), Who("PAd"), Who("Mem", owner=True)):
        assert decide(who, Rule.BID_VIEW_PRICE).allowed
    # A call without a price question: nobody's section holds it.
    assert not decide(
        Who("Mem"),
        Rule.BID_VIEW_PRICE,
        bid_call=BidCallFacts(uuid4(), BidCallStatus.ASSESSING, frozenset({TECHNICAL}), None),
    ).allowed


# --- Section 3a: blind until you submit -------------------------------------------------------
@pytest.mark.parametrize("column", ["PA", "PAd", "Mem", "Vwr", "NMi"])
def test_a_pending_assessor_is_blind_for_that_bid_and_section(column: Column) -> None:
    who = Who(column)

    assert outcome(decide(who, Rule.BID_VIEW_SECTION_SCORES)) == "hidden"
    assert outcome(decide(who, Rule.BID_VIEW_SECTION_SCORES, bid_section_submitted=True)) == (
        "allow"
    )


@pytest.mark.parametrize("column", ["PA", "PAd"])
def test_a_call_manager_who_assesses_is_blind_for_what_they_owe(column: Column) -> None:
    who = Who(column)

    assert outcome(decide(who, Rule.BID_VIEW_SCORES)) == "hidden"
    assert outcome(decide(who, Rule.BID_VIEW_SCORES, bid_section_submitted=True)) == "allow"
    # Another section's scores: they don't assess it, so nothing hides it.
    assert outcome(decide(who, Rule.BID_VIEW_SECTION_SCORES, bid_section_id=COMMERCIAL)) == "allow"
    # The comparison itself (no section in question): allowed; its cells are hidden one by one.
    assert outcome(decide(who, Rule.BID_VIEW_SCORES, bid_section_id=None)) == "allow"


def test_the_owner_who_assesses_is_blind_too() -> None:
    owner = Who("Mem", owner=True)

    assert outcome(decide(owner, Rule.BID_VIEW_SCORES)) == "hidden"
    assert outcome(decide(owner, Rule.BID_VIEW_SECTION_SCORES)) == "hidden"


def test_the_evaluation_blind_rule_never_hides_bids_and_back() -> None:
    """A pending evaluator of the idea still sees the bid comparison; a pending assessor
    still sees the idea's evaluations."""
    evaluator = Who("PAd", sections=frozenset(), my_evaluation=EvaluatorState.INVITED)
    assert outcome(decide(evaluator, Rule.BID_VIEW_SCORES)) == "allow"
    assert outcome(decide(evaluator, Rule.SCORE_VIEW_AGGREGATE)) == "hidden"

    assessor = Who("PAd")
    assert outcome(decide(assessor, Rule.SCORE_VIEW_AGGREGATE)) == "allow"


def test_a_key_follows_its_owner_narrowed_by_scopes() -> None:
    read = Who("Mem", auth="api_key", scopes=frozenset({"read"}))
    evaluate = Who("Mem", auth="api_key", scopes=frozenset({"read", "evaluate"}))

    assert decide(read, Rule.BID_VIEW_BIDS).allowed
    assert decide(read, Rule.BID_VIEW_OWN_ASSESSMENT).allowed  # review C5: read is enough
    assert outcome(decide(read, Rule.BID_ASSESS)) == "403 insufficient_scope"
    assert decide(evaluate, Rule.BID_ASSESS).allowed
    # Session only, whatever the scopes.
    everything = Who("PA", auth="api_key", scopes=frozenset({"read", "write", "evaluate", "mcp"}))
    for rule in (Rule.BID_DECIDE, Rule.BID_UPLOAD_DOCUMENT, Rule.BID_DELETE_CALL):
        assert outcome(decide(everything, rule, bid_call=None)) == "403 insufficient_scope"


# --- c30 ----------------------------------------------------------------------------------------
def test_an_awarded_call_is_deleted_by_platform_admins_only() -> None:
    awarded = BidCallStatus.AWARDED

    assert decide(Who("PA", sections=frozenset(), call_status=awarded), Rule.BID_DELETE_CALL)
    for who in (Who("PAd", call_status=awarded), Who("Mem", owner=True, call_status=awarded)):
        assert outcome(decide(who, Rule.BID_DELETE_CALL)) == "409 bid_call_active"
    for status in (BidCallStatus.DRAFT, BidCallStatus.CANCELLED):
        assert decide(Who("PAd", call_status=status), Rule.BID_DELETE_CALL)


def test_deleting_a_call_ignores_a_closed_idea() -> None:
    """c5 isn't on bid.delete_call: deleting only removes."""
    who = Who("PAd", call_status=BidCallStatus.CANCELLED)
    principal, resource = who.build()
    assert resource.idea is not None
    closed = resource.replace(idea=IdeaFacts(resource.idea.id, IdeaStatus.CLOSED, owner_id=OWNER))

    assert authorize(principal, Rule.BID_DELETE_CALL, closed).allowed
    assert authorize(principal, Rule.BID_MANAGE, closed).code == "idea_closed"


# --- The idea page's flags ------------------------------------------------------------------------
def test_the_bids_tab_flags() -> None:
    manager = Who("PAd", sections=frozenset())
    principal, with_call = manager.build()
    assert bid_call_flags(principal, with_call) == (True, False)  # a call exists
    assert bid_call_flags(principal, with_call.replace(bid_call=None)) == (True, True)
    # A viewer sees the tab only once a call exists, and never creates one.
    viewer, resource = Who("Vwr", sections=frozenset()).build()
    assert bid_call_flags(viewer, resource) == (True, False)
    assert bid_call_flags(viewer, resource.replace(bid_call=None)) == (False, False)
    # A guest researcher: nothing.
    guest, resource = Who("R", sections=frozenset()).build()
    assert bid_call_flags(guest, resource) == (False, False)
