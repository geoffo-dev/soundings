"""The demo data: people, projects and ideas, as plain data.

Times are in days before the moment of seeding, or days after an earlier event of the
same idea, so every run tells the same story ending "now". :mod:`app.seed.runner`
plays it through the application services.

Score strings hold one digit per active criterion in rubric order ("-" = not scored
yet, drafts only). The default rubric is Value, Feasibility, Effort (inverted), Strategic
fit, Risk (inverted); Sustainability's is Carbon impact, Feasibility, Cost (inverted),
Engagement.
"""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from types import MappingProxyType
from typing import Final

from app.models.enums import (
    GroupSyncMode,
    IdeaStatus,
    ProjectRole,
    ProjectVisibility,
    Recommendation,
    Resolution,
)

__all__ = [
    "GROUPS",
    "IDEAS",
    "PEOPLE",
    "PROJECTS",
    "CriterionSeed",
    "GroupSeed",
    "IdeaSeed",
    "Person",
    "ProjectSeed",
    "Remark",
    "Review",
]

ADMIN, MEMBER, VIEWER = ProjectRole.ADMIN, ProjectRole.MEMBER, ProjectRole.VIEWER
GO, MAYBE, NO = Recommendation.GO, Recommendation.MAYBE, Recommendation.NO
NEW, EVALUATING, SHORTLISTED, PROPOSAL, CLOSED = (
    IdeaStatus.NEW,
    IdeaStatus.EVALUATING,
    IdeaStatus.SHORTLISTED,
    IdeaStatus.PROPOSAL,
    IdeaStatus.CLOSED,
)
ACCEPTED, REJECTED, PARKED = Resolution.ACCEPTED, Resolution.REJECTED, Resolution.PARKED


def md(text: str) -> str:
    """Markdown written indented in this file, without the indentation."""
    return dedent(text).strip()


# --- People --------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Person:
    username: str
    name: str
    platform_admin: bool = False
    joined_days_ago: float = 90
    # External ID of kind ``employee_no`` (the dev Keycloak realm's claim), so SSO
    # sign-ins link these accounts by external ID (contract-phase2 section 3.3).
    employee_no: str | None = None

    @property
    def email(self) -> str:
        return f"{self.username}@example.com"


PEOPLE: Final[tuple[Person, ...]] = (
    # The first five match the dev Keycloak realm (dev/README.md), so SSO sign-ins in
    # Phase 2 land on the same accounts.
    Person("alice", "Alice Anders", platform_admin=True, joined_days_ago=120, employee_no="E1001"),
    Person("bob", "Bob Brown", joined_days_ago=110, employee_no="E1002"),
    Person("carol", "Carol Chen", joined_days_ago=105, employee_no="E1003"),
    Person("dave", "Dave Davies", joined_days_ago=100),
    Person("erin", "Erin Evans", joined_days_ago=95),
    Person("farah", "Farah Haddad"),
    Person("kenji", "Kenji Watanabe"),
    Person("amara", "Amara Okafor"),
    Person("mateo", "Mateo Rodríguez", joined_days_ago=80),
    Person("priya", "Priya Raman", joined_days_ago=85),
    Person("sven", "Sven Lindqvist", joined_days_ago=75),
    Person("zanele", "Zanele Dlamini", joined_days_ago=70),
)


# --- Projects ------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CriterionSeed:
    name: str
    description: str
    weight: float = 1.0
    inverted: bool = False
    guidance: MappingProxyType[str, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ProjectSeed:
    key: str
    slug: str
    name: str
    description: str
    visibility: ProjectVisibility
    created_days_ago: float
    # Created by the platform admin (alice) with this first admin, who adds the rest.
    admin: str
    members: tuple[tuple[str, ProjectRole], ...]
    # None: keep the default rubric. Otherwise the complete replacement, in order;
    # "Feasibility" keeps the default criterion (same id), the others are new.
    rubric: tuple[CriterionSeed, ...] | None = None
    status_labels: MappingProxyType[str, str] = MappingProxyType({})
    default_evaluation_days: int = 7


PROJECTS: Final[tuple[ProjectSeed, ...]] = (
    ProjectSeed(
        key="CUST",
        slug="customer-innovation",
        name="Customer Innovation",
        description=(
            "Ideas that make buying from us, and getting help, easier. Anyone can "
            "follow along; members submit and evaluate."
        ),
        visibility=ProjectVisibility.INTERNAL,
        created_days_ago=60,
        admin="alice",
        members=(
            ("priya", ADMIN),
            ("bob", MEMBER),
            ("carol", MEMBER),
            ("farah", MEMBER),
            ("kenji", MEMBER),
            ("amara", MEMBER),
            ("mateo", MEMBER),
            ("zanele", MEMBER),
            ("erin", VIEWER),
            ("sven", VIEWER),
        ),
    ),
    ProjectSeed(
        key="TOOLS",
        slug="internal-tools",
        name="Internal Tools",
        description="Developer experience, internal platforms and the tools we build ourselves.",
        visibility=ProjectVisibility.PRIVATE,
        created_days_ago=55,
        admin="dave",
        members=(
            ("alice", MEMBER),
            ("carol", MEMBER),
            ("kenji", MEMBER),
            ("sven", MEMBER),
            ("mateo", MEMBER),
            ("priya", MEMBER),
            ("zanele", VIEWER),
        ),
        status_labels=MappingProxyType({"shortlisted": "Next up"}),
    ),
    ProjectSeed(
        key="GREEN",
        slug="sustainability",
        name="Sustainability",
        description=(
            "Cutting our carbon footprint in offices, warehouses, travel and the cloud. "
            "Scored on carbon impact first."
        ),
        visibility=ProjectVisibility.INTERNAL,
        created_days_ago=50,
        admin="amara",
        members=(
            ("alice", MEMBER),
            ("zanele", MEMBER),
            ("sven", MEMBER),
            ("farah", MEMBER),
            ("bob", MEMBER),
            ("priya", MEMBER),
            ("kenji", MEMBER),
            ("carol", VIEWER),
            ("erin", VIEWER),
        ),
        rubric=(
            CriterionSeed(
                "Carbon impact",
                "Expected cut in emissions (scope 1-3) once running.",
                weight=2.0,
                guidance=MappingProxyType(
                    {
                        "1": "Negligible or hard to measure.",
                        "3": "A measurable cut for one site or team.",
                        "5": "A major cut across the company.",
                    }
                ),
            ),
            CriterionSeed(
                "Feasibility",
                "How confident we are that we could build and run it.",
                guidance=MappingProxyType(
                    {
                        "1": "Unproven, with major unknowns or dependencies.",
                        "3": "Achievable, with some unknowns to resolve first.",
                        "5": "Straightforward with the skills and technology we have.",
                    }
                ),
            ),
            CriterionSeed(
                "Cost",
                "Up-front and running cost (higher = more expensive).",
                inverted=True,
                guidance=MappingProxyType(
                    {
                        "1": "Within a team budget.",
                        "3": "Needs a budget line this year.",
                        "5": "A capital project needing board approval.",
                    }
                ),
            ),
            CriterionSeed(
                "Engagement",
                "How much colleagues and customers would notice it and join in.",
                weight=0.5,
            ),
        ),
        default_evaluation_days=14,
    ),
)


# --- Groups ------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class GroupSeed:
    """A group, its IdP mapping, the project roles granted to it and its manual members.

    Created by the platform admin (alice); each grant is made by that project's admin.
    The mappings are the dev Keycloak realm's groups (dev/README.md), so SSO sign-ins
    sync memberships. Manual members already hold at least the granted role directly,
    so the groups explain access without changing who can see what with the dev login.
    """

    name: str
    description: str
    created_days_ago: float
    idp_values: tuple[str, ...] = ()
    sync_mode: GroupSyncMode = GroupSyncMode.MANAGED
    grants: tuple[tuple[str, ProjectRole], ...] = ()
    members: tuple[str, ...] = ()


GROUPS: Final[tuple[GroupSeed, ...]] = (
    GroupSeed(
        "Innovation admins",
        "Run the Customer Innovation board.",
        created_days_ago=46,
        idp_values=("/innovation/admins",),
        grants=(("CUST", ADMIN),),
        members=("alice", "priya"),
    ),
    GroupSeed(
        "Innovation members",
        "Submit and evaluate customer ideas. Filled from the IdP at sign-in.",
        created_days_ago=46,
        idp_values=("/innovation/members",),
        grants=(("CUST", MEMBER),),
    ),
    GroupSeed(
        "Tools team",
        "Everyone who builds and runs our internal tools.",
        created_days_ago=45,
        idp_values=("/tools/members",),
        grants=(("TOOLS", MEMBER),),
        members=("kenji", "mateo"),
    ),
    GroupSeed(
        "Viewers",
        "Read-only access to the sustainability work. Additive: sign-in only adds.",
        created_days_ago=44,
        idp_values=("/viewers",),
        sync_mode=GroupSyncMode.ADDITIVE,
        grants=(("GREEN", VIEWER),),
        members=("erin",),
    ),
    GroupSeed(
        "Sustainability champions",
        "Not mapped to the IdP: an admin adds members by hand.",
        created_days_ago=43,
        grants=(("GREEN", MEMBER),),
        members=("farah", "sven", "zanele"),
    ),
)


# --- Ideas ---------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Review:
    """An invited evaluator and what they did.

    ``scores`` empty: invited, nothing saved. ``draft``: saved, not submitted.
    ``after``: days after the invitation that they saved or submitted (default:
    staggered). ``revised``: scores saved again ``revised_after`` days later.
    """

    evaluator: str
    scores: str = ""
    recommendation: Recommendation | None = None
    comment: str = ""
    after: float | None = None
    draft: bool = False
    revised: str | None = None
    revised_after: float = 1.0


@dataclass(frozen=True, slots=True)
class Remark:
    """A comment ``after`` days after the idea was submitted."""

    author: str
    after: float
    body: str


@dataclass(frozen=True, slots=True)
class IdeaSeed:
    """One idea's story. Status changes follow the lifecycle up to ``status``:
    evaluating when evaluators are invited, then shortlisted (the owner closes evaluation
    first), proposal and closed. Rejected ideas close straight from evaluating, parked
    ones after the shortlist."""

    project: str
    title: str
    summary: str
    description: str
    submitter: str
    age: float  # submitted this many days ago
    tags: tuple[str, ...] = ()
    owner: str | None = None
    owner_after: float = 0.4
    volunteered: bool = False
    reviews: tuple[Review, ...] = ()
    invite_after: float = 1.0
    dropped: tuple[str, ...] = ()  # invited with the others, removed a day later
    # (days after the invitation, new window in days from the invitation)
    due_extension: tuple[float, int] | None = None
    status: IdeaStatus = NEW
    resolution: Resolution | None = None
    remarks: tuple[Remark, ...] = ()
    voters: tuple[str, ...] = ()


IDEAS: Final[tuple[IdeaSeed, ...]] = (
    # --- Customer Innovation --------------------------------------------------------------
    IdeaSeed(
        project="CUST",
        title="Self-service returns portal",
        summary=(
            "Let customers start a return, print a label and track the refund without "
            "contacting support."
        ),
        description=md(
            """
            ### Problem
            Returns are 18% of support tickets. Every one needs an agent to check the
            order, email a label and chase the warehouse for the refund.

            ### Proposal
            A returns page in the customer account:

            - pick the order lines and a reason
            - print a prepaid label or choose a drop-off point
            - see the refund status as the warehouse processes the parcel

            ### Out of scope
            Exchanges and returns of made-to-order items (still handled by support).
            """
        ),
        submitter="bob",
        age=44,
        tags=("returns", "self-service", "support"),
        owner="priya",
        reviews=(
            Review("carol", "54243", GO, "Clear win for support volume. Warehouse API exists."),
            Review("farah", "54232", GO, "Customers ask for this every week."),
            Review("alice", "44243", GO, "Worth doing; watch label costs for bulky items."),
        ),
        status=CLOSED,
        resolution=ACCEPTED,
        remarks=(
            Remark(
                "carol",
                2,
                "The warehouse team confirmed their API can send refund events, so the "
                "tracking part is cheap.",
            ),
            Remark("priya", 12, "Approved for Q3. Kick-off with the warehouse team next week."),
        ),
        voters=("carol", "farah", "kenji", "mateo", "zanele", "amara"),
    ),
    IdeaSeed(
        project="CUST",
        title="Proactive delivery delay notifications",
        summary=(
            "Tell customers about a late delivery before they notice, with a new date and "
            "an option to cancel."
        ),
        description=md(
            """
            When a carrier reports a delay we find out hours before the customer does, but
            we only react once they call us.

            **Proposal:** send an email and SMS as soon as a delay is reported, with the
            new estimate and a one-click cancel for orders that have not shipped.

            Expected effect: fewer "where is my order" contacts (about 1,200 a month) and
            better reviews in peak season.
            """
        ),
        submitter="carol",
        age=41,
        tags=("delivery", "notifications"),
        owner="alice",
        reviews=(
            Review("bob", "44233", GO, "Low effort, the carrier webhooks are already there."),
            Review("kenji", "53232", GO),
            Review("farah", "44243", MAYBE, "Good, but SMS costs need a budget."),
        ),
        status=CLOSED,
        resolution=ACCEPTED,
        remarks=(
            Remark(
                "farah",
                3,
                "Could we start with email only and add SMS once we see the numbers?",
            ),
            Remark("alice", 4, "Yes, email first. SMS is a follow-up if contacts drop."),
        ),
        voters=("bob", "farah", "kenji", "zanele", "mateo"),
    ),
    IdeaSeed(
        project="CUST",
        title="Loyalty points for product reviews",
        summary="Reward customers with loyalty points when they review a product they bought.",
        description=md(
            """
            Only 3% of orders get a review. Offering 50 points (about 50p) per review
            could lift that to 10% and give new customers more to go on.

            - points only for verified purchases
            - one review per product
            - points added after moderation
            """
        ),
        submitter="farah",
        age=38,
        tags=("loyalty", "reviews"),
        owner="priya",
        reviews=(
            Review("mateo", "33334", MAYBE),
            Review(
                "zanele",
                "32343",
                NO,
                "Paid reviews break the marketplace rules in two of our markets.",
            ),
            Review("kenji", "23334", NO, "Incentivised reviews are worth less to shoppers."),
        ),
        status=CLOSED,
        resolution=REJECTED,
        remarks=(
            Remark(
                "priya",
                6.9,
                "Closing this: incentivised reviews would have to be labelled in the EU and "
                "UK, which undoes most of the benefit. Thanks everyone.",
            ),
        ),
        voters=("farah", "bob"),
    ),
    IdeaSeed(
        project="CUST",
        title="Live chat on the pricing page",
        summary="Offer live chat with a sales rep to visitors who linger on the pricing page.",
        description=md(
            """
            Visitors who spend more than a minute on the pricing page convert at twice the
            average rate when they talk to someone. Today they have to find the contact
            form.

            Proposal: a chat bubble on `/pricing` during office hours, routed to the
            inside sales team.
            """
        ),
        submitter="kenji",
        age=36,
        tags=("sales", "chat"),
        owner="bob",
        reviews=(
            Review("amara", "43334", MAYBE, "Depends on sales having people free."),
            Review("carol", "42343", MAYBE, "The chat tool is being replaced by the new CRM."),
        ),
        status=CLOSED,
        resolution=PARKED,
        remarks=(
            Remark(
                "bob",
                6.6,
                "Parking this until the CRM migration is done in the autumn; the new CRM "
                "has chat built in.",
            ),
        ),
        voters=("kenji", "mateo", "amara"),
    ),
    IdeaSeed(
        project="CUST",
        title="Customer advisory board",
        summary=(
            "Meet twelve customers every quarter to test ideas early and hear what they "
            "struggle with."
        ),
        description=md(
            """
            ### Why
            Most of our product decisions rely on support tickets and surveys. Both tell
            us what went wrong, rarely what customers would pay for.

            ### How
            1. Invite twelve customers from different segments for a year.
            2. Meet quarterly (two hours, remote), plus a shared channel.
            3. Share early concepts from this board before we build them.

            ### Cost
            Mostly time: a product manager half a day a month, and a thank-you budget.
            """
        ),
        submitter="amara",
        age=33,
        tags=("research", "customers"),
        owner="priya",
        reviews=(
            Review("bob", "44244", GO),
            Review("alice", "54243", GO, "We should have done this years ago."),
            Review("zanele", "44233", GO),
            Review("mateo", "43243", GO, "Include at least two customers who left us."),
        ),
        status=PROPOSAL,
        remarks=(
            Remark("mateo", 6, "Happy to help recruit from the small-business segment."),
            Remark(
                "priya",
                14,
                "Drafting the proposal now: budget, selection criteria and the first "
                "agenda. Comments welcome.",
            ),
        ),
        voters=("bob", "carol", "zanele", "mateo", "farah", "kenji", "alice"),
    ),
    IdeaSeed(
        project="CUST",
        title="Usage-based pricing tier for small teams",
        summary=(
            "A pay-as-you-go plan for teams under ten people, billed monthly on actual usage."
        ),
        description=md(
            """
            Small teams churn in their first three months because the Starter plan's
            fixed price feels high for occasional use.

            | Plan | Today | Proposed |
            |---|---|---|
            | Starter | 49/month | 0 base + 0.40 per active user-day |
            | Team | 199/month | unchanged |

            Billing already records active user-days, so metering is mostly done.
            """
        ),
        submitter="mateo",
        age=30,
        tags=("pricing", "small-business"),
        owner="alice",
        reviews=(
            Review("bob", "53343", GO),
            Review("carol", "54332", GO, "Metering exists; invoices need work."),
            Review("farah", "44343", GO),
            Review("zanele", "53333", MAYBE, "Model the revenue impact before we commit."),
        ),
        status=PROPOSAL,
        remarks=(
            Remark(
                "zanele",
                5,
                "Finance would like a revenue model with three adoption scenarios.",
            ),
            Remark(
                "alice",
                8,
                "Added the scenarios to the proposal draft. Worst case is flat revenue in "
                "year one.",
            ),
        ),
        voters=("mateo", "bob", "farah", "kenji"),
    ),
    IdeaSeed(
        project="CUST",
        title="In-app onboarding checklist",
        summary="A short checklist that walks new accounts through their first five tasks.",
        description=md(
            """
            New accounts that complete three key tasks in week one keep using the product
            at twice the rate. Most never find task two.

            Proposal: a dismissible checklist in the sidebar for the first 30 days, with
            progress saved per account.
            """
        ),
        submitter="zanele",
        age=27,
        tags=("onboarding", "activation"),
        owner="carol",
        reviews=(
            Review("kenji", "44243", GO),
            Review("amara", "54232", GO, "Cheap to try, and easy to measure."),
            Review("priya", "44242", GO),
        ),
        status=SHORTLISTED,
        remarks=(Remark("carol", 7, "Shortlisted. Design has a first sketch for the sidebar."),),
        voters=("zanele", "kenji", "amara", "bob"),
    ),
    IdeaSeed(
        project="CUST",
        title="Replace the NPS survey with in-context feedback",
        summary=(
            "Drop the quarterly NPS email and ask one question in the product right after "
            "key tasks."
        ),
        description=md(
            """
            The NPS email gets a 4% response rate and tells us little about *why*.

            Instead, ask a single question right after a task (for example "How easy was
            it to export your report?") and route answers to the team that owns the
            feature.

            **Open question:** leadership reports on NPS. We would need to keep a
            comparable number for at least two quarters.
            """
        ),
        submitter="priya",
        age=24,
        tags=("feedback", "research"),
        owner="alice",
        reviews=(
            Review("bob", "52343", GO, "Much better signal than NPS."),
            Review(
                "kenji",
                "24343",
                NO,
                "Leadership needs NPS for the board pack; this does not replace it.",
            ),
            Review("carol", "44333", MAYBE),
        ),
        status=SHORTLISTED,
        remarks=(
            Remark(
                "alice",
                8,
                "Big disagreement on value here. Kenji and Bob, can we talk it through "
                "before this becomes a proposal?",
            ),
            Remark(
                "kenji",
                9,
                "Happy to. If we keep a quarterly NPS sample alongside it, I'm much more positive.",
            ),
        ),
        voters=("priya", "bob"),
    ),
    IdeaSeed(
        project="CUST",
        title="Partner referral programme",
        summary="Pay agencies and consultants a commission for customers they refer to us.",
        description=md(
            """
            Several agencies already recommend us informally. A referral programme with a
            12-month revenue share would turn that into a channel we can track.

            - partner sign-up page and unique links
            - 15% of first-year revenue
            - quarterly payouts through the existing billing provider
            """
        ),
        submitter="bob",
        age=21,
        tags=("partners", "growth"),
        owner="mateo",
        reviews=(
            Review("farah", "44232", GO),
            Review(
                "amara",
                "43333",
                MAYBE,
                "Who supports the partners?",
                revised="44333",
                revised_after=1.5,
            ),
            Review("zanele", "44233", GO),
        ),
        status=SHORTLISTED,
        remarks=(
            Remark(
                "mateo",
                4,
                "Partner support would sit with the account managers for the first year.",
            ),
        ),
        voters=("bob", "farah", "mateo"),
    ),
    IdeaSeed(
        project="CUST",
        title="Customer health score for account managers",
        summary=(
            "Combine usage, support tickets and billing into one score that flags accounts at risk."
        ),
        description=md(
            """
            Account managers find out an account is unhappy when it cancels. The signals
            were there: usage dropping, more tickets, late payments.

            Proposal: a daily health score (0-100) per account, shown in the CRM, with the
            three biggest contributing factors.
            """
        ),
        submitter="carol",
        age=18,
        tags=("retention", "analytics"),
        owner="priya",
        reviews=(
            Review("alice"),
            Review("bob", "43343", GO),
            Review("mateo", "44333", MAYBE, "Needs the data team; they are booked until March."),
        ),
        status=EVALUATING,
        remarks=(
            Remark(
                "priya",
                9,
                "Alice, could you add your evaluation this week? I'd like to decide on Friday.",
            ),
        ),
        voters=("carol", "bob", "amara"),
    ),
    IdeaSeed(
        project="CUST",
        title="WhatsApp order updates",
        summary="Order confirmations and delivery updates over WhatsApp, for customers who opt in.",
        description=md(
            """
            In several markets customers read WhatsApp messages within minutes but ignore
            email. Order updates are the obvious first use.

            - opt-in at checkout
            - order confirmed, shipped, out for delivery, delivered
            - replies go to the support inbox
            """
        ),
        submitter="farah",
        age=14,
        tags=("notifications", "messaging"),
        owner="bob",
        reviews=(
            Review("alice"),
            Review("kenji", "52232", GO, "Customers in Spain and Brazil would love this."),
            Review(
                "zanele",
                "23254",
                NO,
                "Big privacy review and a new vendor; the benefit outside two markets is small.",
            ),
            Review("amara"),
        ),
        status=EVALUATING,
        remarks=(
            Remark("kenji", 3, "Our Brazilian distributor already does this and swears by it."),
            Remark(
                "zanele",
                5,
                "Legal will need a data processing agreement with Meta before any pilot.",
            ),
        ),
        voters=("farah", "kenji", "mateo", "carol"),
    ),
    IdeaSeed(
        project="CUST",
        title="Accessibility audit of the checkout",
        summary="An external audit of the checkout against WCAG 2.2 AA, then fix what it finds.",
        description=md(
            """
            We have never tested the checkout with a screen reader. The European
            Accessibility Act applies to us from June.

            1. External audit (two weeks)
            2. Fix blocking issues before June
            3. Add automated checks to the pipeline so we stay compliant
            """
        ),
        submitter="amara",
        age=11,
        tags=("accessibility", "checkout", "compliance"),
        owner="alice",
        reviews=(
            Review("bob", "44253", GO, "This is a legal requirement, not a nice-to-have."),
            Review("carol", "45242", GO),
            Review("farah", "44---", draft=True, after=3),
            Review("mateo"),
        ),
        status=EVALUATING,
        remarks=(
            Remark("alice", 2, "Invited four evaluators; we need this decided by month end."),
        ),
        voters=("amara", "bob", "carol", "zanele", "priya"),
    ),
    IdeaSeed(
        project="CUST",
        title="Gift cards for business customers",
        summary="Let companies buy gift cards in bulk for staff rewards and client gifts.",
        description=md(
            """
            Three large customers asked for bulk gift cards last quarter. We sell
            consumer gift cards already; business customers need invoices, bulk codes and
            a CSV of recipients.
            """
        ),
        submitter="kenji",
        age=9,
        tags=("b2b", "gift-cards"),
        owner="priya",
        reviews=(
            Review("carol", "33322", MAYBE, "Finance must sign off on the liability."),
            Review("zanele"),
            Review("mateo"),
        ),
        status=EVALUATING,
        voters=("kenji",),
    ),
    IdeaSeed(
        project="CUST",
        title="Status page for order and API incidents",
        summary="A public status page so customers can see incidents before they contact us.",
        description=md(
            """
            During the last outage support received 900 tickets in two hours, mostly
            asking whether something was wrong.

            A public status page (orders, payments, API, website) updated by the on-call
            engineer, with email subscriptions.
            """
        ),
        submitter="mateo",
        age=6,
        tags=("support", "reliability"),
        owner="carol",
        reviews=(
            Review("alice"),
            Review("bob", "44233", GO, "Cheap and it pays for itself in the next outage."),
            Review("amara"),
        ),
        status=EVALUATING,
        remarks=(Remark("bob", 3.2, "Platform already has a private status page we can expose."),),
        voters=("mateo", "bob", "farah"),
    ),
    IdeaSeed(
        project="CUST",
        title="Photo-based product search",
        summary="Let shoppers search the catalogue by taking a photo of an item.",
        description=md(
            """
            Customers often know what a part looks like but not what it is called. A
            camera button in the search bar could match photos against our catalogue
            images.

            Needs a vendor evaluation: three offer visual search as a service.
            """
        ),
        submitter="zanele",
        age=5,
        tags=("search", "mobile"),
        owner="kenji",
        volunteered=True,
        reviews=(Review("farah", "43454", MAYBE, "Exciting, but the vendor costs are unclear."),),
        status=EVALUATING,
        remarks=(
            Remark(
                "kenji",
                1.2,
                "I'll own this: I looked into visual search vendors last year. Could use a "
                "couple more evaluators.",
            ),
        ),
        voters=("zanele", "mateo"),
    ),
    IdeaSeed(
        project="CUST",
        title="Saved carts that sync across devices",
        summary="Keep a signed-in customer's cart the same on phone, tablet and laptop.",
        description=md(
            """
            Many customers browse on their phone and buy on a laptop, and find an empty
            cart. Store carts server-side for signed-in customers.
            """
        ),
        submitter="bob",
        age=4,
        tags=("checkout", "mobile"),
        voters=("carol", "farah", "kenji", "amara"),
    ),
    IdeaSeed(
        project="CUST",
        title="Help-centre answers in the chat widget",
        summary=(
            "Suggest matching help-centre articles in the chat widget before a customer "
            "starts a chat."
        ),
        description=md(
            """
            A third of chats are answered by an existing help-centre article. Show the
            three best matches as the customer types their question, and measure how
            many chats that saves.
            """
        ),
        submitter="carol",
        age=3,
        tags=("support", "self-service"),
        owner="alice",
        voters=("bob",),
    ),
    IdeaSeed(
        project="CUST",
        title="Pause a subscription instead of cancelling",
        summary="Offer a one-to-three month pause to customers who try to cancel.",
        description=md(
            """
            Exit surveys say "not needed right now" is the top reason for cancelling.
            A pause keeps the account and the data, and many would come back.
            """
        ),
        submitter="farah",
        age=2,
        tags=("retention", "billing"),
        voters=("mateo", "zanele"),
    ),
    IdeaSeed(
        project="CUST",
        title="Localised invoices for EU customers",
        summary="Issue invoices in the customer's language with local VAT wording.",
        description=md(
            """
            French and German customers regularly ask for invoices in their language, and
            some accounting departments reject English ones.
            """
        ),
        submitter="kenji",
        age=1.2,
        tags=("billing", "localisation"),
    ),
    IdeaSeed(
        project="CUST",
        title="Birthday discount emails",
        summary="Send customers a 10% discount code on their birthday.",
        description="We would need to start asking for dates of birth at sign-up.",
        submitter="mateo",
        age=0.3,
        tags=("marketing",),
    ),
    # --- Internal Tools --------------------------------------------------------------------
    IdeaSeed(
        project="TOOLS",
        title="Single sign-on for the staging environments",
        summary="Put every staging app behind company SSO instead of shared passwords.",
        description=md(
            """
            Staging apps use a shared basic-auth password that has not changed in two
            years and is in several wikis.

            Put them behind the identity-aware proxy we already run for production
            dashboards.
            """
        ),
        submitter="kenji",
        age=45,
        tags=("security", "staging"),
        owner="dave",
        reviews=(
            Review("carol", "54243", GO, "Overdue. The proxy supports it already."),
            Review("sven", "44242", GO),
            Review("priya", "54233", GO),
        ),
        status=CLOSED,
        resolution=ACCEPTED,
        remarks=(Remark("dave", 13, "Done: all staging apps are behind SSO since Monday."),),
        voters=("carol", "sven", "priya", "mateo"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Replace the wiki with docs-as-code",
        summary="Move engineering documentation from the wiki into Markdown in each repository.",
        description=md(
            """
            The wiki is out of date because it lives away from the code. Docs in the
            repository get reviewed with the change that makes them stale.

            Migration: 2,400 pages, of which maybe 600 are still useful.
            """
        ),
        submitter="sven",
        age=39,
        tags=("documentation",),
        owner="carol",
        reviews=(
            Review("kenji", "54433", GO, "Best thing we could do for onboarding."),
            Review("mateo", "32544", NO, "The migration is a huge job for unclear benefit."),
            Review("dave", "24534", NO, "Non-engineers use the wiki too. This splits the docs."),
        ),
        status=CLOSED,
        resolution=REJECTED,
        remarks=(
            Remark(
                "carol",
                7,
                "Rejecting the full migration. New service docs can start in their "
                "repositories; nobody needs to move old pages.",
            ),
            Remark("sven", 7.5, "Fair. I'll write up the convention for new services."),
        ),
        voters=("sven", "kenji"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Self-service test data generator",
        summary="Generate realistic, anonymised test accounts and orders on demand.",
        description=md(
            """
            Teams copy production data into staging to get realistic tests, which is a
            privacy risk. A generator could create customers, orders and invoices with
            the right shapes and edge cases.

            ```sh
            testdata create --customers 50 --orders-per-customer 3 --env staging
            ```
            """
        ),
        submitter="mateo",
        age=35,
        tags=("testing", "privacy"),
        owner="kenji",
        reviews=(
            Review("alice", "44343", GO),
            Review("priya", "54332", GO, "Removes our biggest privacy finding from the audit."),
            Review("sven", "43342", GO),
        ),
        status=PROPOSAL,
        remarks=(
            Remark("kenji", 16, "The proposal draft is on the team page: about two sprints."),
        ),
        voters=("mateo", "priya", "sven", "alice", "carol"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Automated quarterly access reviews",
        summary=(
            "Send each manager a list of their team's system access every quarter to "
            "confirm or revoke."
        ),
        description=md(
            """
            Access reviews are a spreadsheet exercise that takes security two weeks per
            quarter. The auditors accept an automated workflow if it keeps evidence.
            """
        ),
        submitter="priya",
        age=31,
        tags=("security", "compliance"),
        owner="dave",
        reviews=(
            Review("alice", "44252", GO),
            Review("carol", "43242", GO),
            Review("kenji", "44242", GO),
        ),
        status=SHORTLISTED,
        voters=("priya", "alice"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="On-call handover checklist bot",
        summary="A chat bot that runs the on-call handover checklist at the end of each shift.",
        description=md(
            """
            Handovers are skipped when the shift was quiet, and then the next person
            misses an open incident. A bot could post the checklist and collect answers.
            """
        ),
        submitter="carol",
        age=26,
        tags=("on-call", "chatops"),
        owner="sven",
        reviews=(
            Review("mateo", "33233", MAYBE),
            Review("dave", "34223", MAYBE, "Nice, but the incident tool is changing next year."),
        ),
        status=CLOSED,
        resolution=PARKED,
        remarks=(Remark("sven", 6.6, "Parked until the new incident tool is chosen."),),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Cloud cost dashboard per team",
        summary="Show each team what its services cost in the cloud, updated daily.",
        description=md(
            """
            Our cloud bill grew 40% last year and nobody can say which services drove it.
            Tag every resource with a team and publish a daily cost dashboard.
            """
        ),
        submitter="dave",
        age=22,
        tags=("cloud", "cost"),
        owner="mateo",
        reviews=(
            Review("priya", "43342", GO),
            Review("kenji", "44333", GO),
            Review("sven", "43343", MAYBE, "Tagging old resources is the hard part."),
            Review("alice", "44343", GO),
        ),
        status=EVALUATING,
        remarks=(
            Remark(
                "mateo",
                10,
                "All four evaluations are in. I'll bring it to the tooling review on Thursday.",
            ),
        ),
        voters=("dave", "alice", "priya"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Laptop setup in one script",
        summary="One command that installs and configures everything a new engineer needs.",
        description=md(
            """
            New engineers spend two to three days setting up their laptop from a wiki
            page. A script (idempotent, re-runnable) would take that to an hour.
            """
        ),
        submitter="sven",
        age=19,
        tags=("onboarding", "developer-experience"),
        owner="kenji",
        reviews=(
            Review("carol", "44122", GO),
            Review("dave", "45132", GO, "Tiny effort, big goodwill."),
        ),
        status=SHORTLISTED,
        voters=("sven", "carol", "mateo", "priya", "alice"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Meeting-free Wednesday calendar guard",
        summary="Decline meeting invitations on Wednesdays automatically, with an override.",
        description=md(
            """
            We agreed on meeting-free Wednesdays, but invitations keep appearing. A
            calendar add-on could decline them with a friendly note unless the organiser
            marks the meeting as urgent.
            """
        ),
        submitter="priya",
        age=15,
        tags=("focus-time", "calendar"),
        owner="dave",
        reviews=(
            Review("carol", "32232", MAYBE),
            Review("sven", "33222", MAYBE, "A policy reminder might do the same."),
            Review("kenji", "32232", MAYBE),
        ),
        status=EVALUATING,
        voters=("priya", "mateo"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Feature-flag clean-up reminders",
        summary="Remind owners of feature flags that have been fully rolled out for 30 days.",
        description=md(
            """
            We have 310 feature flags; about 200 are fully on and just add branches to
            the code. A weekly reminder to each flag's owner, with a link to remove it.
            """
        ),
        submitter="kenji",
        age=12,
        tags=("developer-experience", "tech-debt"),
        owner="carol",
        reviews=(
            Review("dave", "43242", GO),
            Review("alice", "43---", draft=True, after=9),
            Review("sven", "44232", GO),
        ),
        due_extension=(6, 14),
        status=EVALUATING,
        remarks=(
            Remark(
                "carol",
                7.1,
                "Extended the due date by a week: half the team is at the conference.",
            ),
        ),
        voters=("kenji", "dave"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Shared staging database snapshots",
        summary="Nightly anonymised snapshots of the staging database that any team can restore.",
        description=md(
            """
            Teams break staging data and then wait a day for someone to fix it. Nightly
            snapshots with a one-command restore per team schema would stop that.
            """
        ),
        submitter="mateo",
        age=7,
        tags=("staging", "testing"),
        owner="dave",
        reviews=(
            Review("priya", "43343", GO),
            Review("sven"),
            Review("kenji"),
        ),
        status=EVALUATING,
        voters=("mateo",),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Internal status page for developer tooling",
        summary="One page showing whether CI, the artifact registry and staging are healthy.",
        description="Half the questions in the platform channel are 'is CI down?'.",
        submitter="carol",
        age=4,
        tags=("reliability",),
        voters=("kenji", "sven"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Chat command to request system access",
        summary="Request access to a system from chat; the owner approves with one click.",
        description=md(
            """
            Access requests today go through a form nobody can find. A chat command would
            create the ticket and ping the system owner.
            """
        ),
        submitter="sven",
        age=2,
        tags=("chatops", "security"),
    ),
    IdeaSeed(
        project="TOOLS",
        title="Retire the legacy build server",
        summary="Move the last six jobs off the old build server and switch it off.",
        description="It costs about 900 a month and nobody wants to patch it.",
        submitter="dave",
        age=0.5,
        tags=("ci", "cost"),
    ),
    # --- Sustainability --------------------------------------------------------------------
    IdeaSeed(
        project="GREEN",
        title="LED lighting retrofit for the Leeds warehouse",
        summary=(
            "Replace the warehouse's sodium lamps with LEDs and motion sensors; payback in "
            "under three years."
        ),
        description=md(
            """
            The Leeds warehouse still runs 400 high-pressure sodium lamps, on all night.

            - LEDs with motion sensors in the aisles
            - estimated 60% less lighting energy (about 90 t CO2e a year)
            - payback 2.5 years at current prices
            """
        ),
        submitter="zanele",
        age=43,
        tags=("energy", "warehouse"),
        owner="amara",
        reviews=(
            Review("sven", "4423", GO),
            Review("farah", "4522", GO, "Proven technology, quick payback."),
            Review("bob", "3423", GO),
        ),
        status=CLOSED,
        resolution=ACCEPTED,
        remarks=(Remark("amara", 16, "Approved; installation is booked for the summer shutdown."),),
        voters=("sven", "farah", "bob", "priya", "kenji"),
    ),
    IdeaSeed(
        project="GREEN",
        title="Cycle-to-work scheme",
        summary="Offer staff tax-free bikes through salary sacrifice, plus secure bike parking.",
        description=md(
            """
            A salary-sacrifice scheme costs us almost nothing and 30% of staff live within
            eight kilometres of an office. The Bristol office needs covered bike parking
            first.
            """
        ),
        submitter="sven",
        age=37,
        tags=("commuting", "wellbeing"),
        owner="farah",
        reviews=(
            Review("zanele", "3515", GO),
            Review("priya", "2415", GO, "Small carbon effect, but staff love it."),
            Review("kenji", "3515", GO),
        ),
        status=CLOSED,
        resolution=ACCEPTED,
        voters=("zanele", "priya", "kenji", "bob", "alice", "farah"),
    ),
    IdeaSeed(
        project="GREEN",
        title="Carbon offsets for all business travel",
        summary="Buy certified offsets for every flight and train journey booked through travel.",
        description=md(
            """
            Business travel is 30% of our reported footprint. Offsetting all of it would
            cost about 40,000 a year.
            """
        ),
        submitter="bob",
        age=34,
        tags=("travel", "offsets"),
        owner="amara",
        reviews=(
            Review("sven", "2532", NO, "Offsets don't reduce anything; fly less instead."),
            Review("zanele", "1433", NO),
            Review("farah", "2542", MAYBE),
        ),
        status=CLOSED,
        resolution=REJECTED,
        remarks=(
            Remark(
                "amara",
                6.9,
                "Rejected in favour of a travel policy change (rail for trips under five "
                "hours). Offsets may come back for the remainder.",
            ),
        ),
        voters=("bob",),
    ),
    IdeaSeed(
        project="GREEN",
        title="Reusable packaging for B2B deliveries",
        summary="Deliver to business customers in returnable crates instead of cardboard.",
        description=md(
            """
            Business customers receive several boxes a week from us. Returnable crates,
            collected on the next delivery, would remove about 70 tonnes of cardboard a
            year.

            A pilot with five large customers in the north-west is the first step.
            """
        ),
        submitter="farah",
        age=29,
        tags=("packaging", "logistics"),
        owner="zanele",
        reviews=(
            Review("bob", "4334", GO),
            Review("kenji", "4434", GO),
            Review("alice", "5334", GO, "Customers will see this, which matters too."),
            Review("sven", "4344", GO),
        ),
        status=PROPOSAL,
        remarks=(Remark("zanele", 12, "Two of the five pilot customers have said yes already."),),
        voters=("farah", "bob", "alice", "priya", "sven"),
    ),
    IdeaSeed(
        project="GREEN",
        title="Move cloud workloads to a low-carbon region",
        summary="Run batch and analytics workloads in the cloud region with the cleanest grid.",
        description=md(
            """
            Our batch jobs are not latency-sensitive. Moving them to a region with a
            mostly renewable grid cuts their emissions by about 80% at no extra cost.
            """
        ),
        submitter="kenji",
        age=25,
        tags=("cloud", "energy"),
        owner="sven",
        reviews=(
            Review("priya", "4423", GO),
            Review("zanele", "3423", GO),
            Review("bob", "4412", GO, "Almost free to do."),
        ),
        status=SHORTLISTED,
        voters=("kenji", "priya"),
    ),
    IdeaSeed(
        project="GREEN",
        title="Heat pumps for the Bristol office",
        summary="Replace the Bristol office's gas boilers with air-source heat pumps.",
        description=md(
            """
            The boilers are 19 years old and due for replacement anyway. Heat pumps would
            remove most of the office's scope 1 emissions.

            - grant funding may cover up to 25%
            - the landlord must agree to the outdoor units
            """
        ),
        submitter="priya",
        age=20,
        tags=("energy", "offices"),
        owner="amara",
        reviews=(
            Review("sven", "5253", GO),
            Review("farah", "4254", MAYBE, "Cost is the issue, not the carbon case."),
            Review("zanele", "5353", GO),
            Review("kenji", "3232", NO, "Our lease ends in three years; we may not stay."),
        ),
        status=SHORTLISTED,
        remarks=(
            Remark(
                "amara",
                9,
                "Shortlisted, but the lease question needs an answer from facilities first.",
            ),
        ),
        voters=("priya", "sven", "zanele"),
    ),
    IdeaSeed(
        project="GREEN",
        title="Paperless invoicing by default",
        summary="Email invoices by default and charge for paper invoices on request.",
        description=md(
            """
            We still post 11,000 paper invoices a month. Most customers never asked for
            paper; it is simply the old default.
            """
        ),
        submitter="alice",
        age=16,
        tags=("billing", "paper"),
        owner="alice",
        reviews=(
            Review("zanele", "2514", GO),
            Review("bob", "3524", GO),
            Review("priya"),
        ),
        status=EVALUATING,
        voters=("zanele", "bob", "farah"),
    ),
    IdeaSeed(
        project="GREEN",
        title="Supplier sustainability questionnaire",
        summary="Ask our top 50 suppliers for their emissions data and targets every year.",
        description=md(
            """
            Scope 3 is most of our footprint and we have no supplier data. A yearly
            questionnaire is the standard first step, and customers are starting to ask
            us the same questions.
            """
        ),
        submitter="amara",
        age=12,
        tags=("suppliers", "reporting"),
        owner="zanele",
        reviews=(
            Review("alice"),
            Review("farah", "3333", MAYBE),
            Review("sven"),
        ),
        status=EVALUATING,
        voters=("amara",),
    ),
    IdeaSeed(
        project="GREEN",
        title="Meat-free Mondays in the canteen",
        summary="Serve only vegetarian dishes in the head office canteen on Mondays.",
        description=md(
            """
            Food is a large part of the canteen's footprint. Other companies report a
            small, steady effect and mostly positive feedback after the first month.
            """
        ),
        submitter="farah",
        age=9,
        tags=("food", "offices"),
        remarks=(
            Remark("bob", 1, "Love it. Can we start with one week a month?"),
            Remark(
                "kenji",
                2,
                "I'd rather see a better vegetarian option every day than a rule.",
            ),
            Remark("zanele", 3, "The canteen supplier says either is easy for them."),
        ),
        voters=("farah", "bob", "zanele", "priya", "sven", "amara"),
    ),
    IdeaSeed(
        project="GREEN",
        title="Solar panels on the Leeds warehouse roof",
        summary="Install rooftop solar on the Leeds warehouse to cover daytime demand.",
        description=md(
            """
            The warehouse roof is 6,000 m2, flat and ours. A structural survey is needed
            before quotes.
            """
        ),
        submitter="sven",
        age=6,
        tags=("energy", "warehouse"),
        owner="amara",
        reviews=(
            Review("kenji", "54--", draft=True, after=2),
            Review("bob"),
        ),
        dropped=("farah",),
        status=EVALUATING,
        remarks=(Remark("amara", 2.1, "Farah is away this month, so I took her off the list."),),
        voters=("sven", "zanele", "alice"),
    ),
    IdeaSeed(
        project="GREEN",
        title="Repair café for staff electronics",
        summary="A monthly lunchtime session where volunteers help colleagues repair gadgets.",
        description="Keeps devices out of landfill and it is a nice way to meet people.",
        submitter="zanele",
        age=3,
        tags=("community", "waste"),
        voters=("sven",),
    ),
    IdeaSeed(
        project="GREEN",
        title="Measure the carbon cost of our CI pipelines",
        summary="Estimate the emissions of every CI run and show them next to the build time.",
        description="Might nudge teams to cache more and run fewer redundant jobs.",
        submitter="kenji",
        age=1,
        tags=("cloud", "measurement"),
    ),
)
