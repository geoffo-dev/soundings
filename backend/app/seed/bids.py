"""The demo story's Phase 10 part (contract-phase10 section 17, L12): a call for bids on
**TOOLS-3** ("Self-service test data generator", kenji's idea in Proposal in the private
Internal Tools; a private project shows that assessors need a role there).

* The call "Data platform build" is **being assessed**: its deadline has passed and the
  assessments are due in a few days. No AI assessor is named (the demo runs without AI).
* Sections (the project's default template): Technical (carol, mateo), Commercial with the
  price (priya), Delivery (sven, alice). All five are members of Internal Tools; dave is its
  admin, kenji the idea's owner (both call managers); zanele, a viewer there, sees the
  call's summary only.
* Three fictional suppliers, each with a form of tender (PDF), a pricing schedule (PDF, a
  **pricing document**: carol, mateo, sven and alice see "present (restricted)", priya
  opens it) and a technical proposal (Word):

  - **Northwind Data Ltd**: complete and strong, 120,000 GBP;
  - **Tessellate Software**: complete, cheaper (96,000 GBP), weaker technically; carol and
    mateo disagree on its first Technical question (4 and 2); an AI assessment of it is
    stored and **left out** of the totals;
  - **Quillfield Systems**: no insurance certificate, so that must-have is flagged missing
    and kenji rejected it: "No insurance certificate provided."

* Everyone has submitted but **alice, who owes both Delivery assessments** (her My work and
  the sidebar badge), so her comparison is fully hidden (no ranks): walk the comparison as
  kenji or dave.

The documents are the small files in ``app/seed/bids/`` (built by
``tests/bids/seed_documents.py``), uploaded and **extracted at seed time** with the worker's
own child process (:func:`app.bids.extraction.extract_in_session`). The runner plays every
step through the bid services, as the person named (:func:`schedule`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import select

from app.authz import Rule, require
from app.bids import access, assess, documents, service
from app.bids.data import load_call_data
from app.bids.extraction import extract_in_session
from app.config import Settings
from app.domain.principal import Principal
from app.models.ai import AiAgent, AiAgentProject
from app.models.bid import Bid, BidCallMustHave, BidCallQuestion
from app.models.enums import (
    AiAgentProtocol,
    AiMustHaveFinding,
    AiRunKind,
    BidCallStatus,
    BidQuestionType,
    MustHaveResult,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.ai import service_account_email
from app.schemas.bids import (
    BidAnswerIn,
    BidAssessorsUpdate,
    BidCallCreate,
    BidCallUpdate,
    BidIn,
    BidSectionAssessorsIn,
    MustHaveDecisionIn,
    MyBidAssessmentIn,
)
from app.schemas.mcp import McpBidEvidenceIn, McpBidFindingIn, McpBidScoreIn

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "AI_AGENT_NAME",
    "BIDS",
    "CALL_TITLE",
    "DOCUMENT_DIR",
    "IDEA_TITLE",
    "SECTION_ASSESSORS",
    "schedule",
]

DOCUMENT_DIR: Final = Path(__file__).resolve().parent / "bids"
IDEA_TITLE: Final = "Self-service test data generator"
"""TOOLS-3."""
CALL_TITLE: Final = "Data platform build"
CALL_DESCRIPTION: Final = (
    "We're looking for a partner to build the self-service test data generator in the "
    "proposal: a service in the developer portal, delivered within four months."
)
AI_AGENT_NAME: Final = "demo-bid-assessor"
"""The demo's AI assessor (namespace ``soundings``): **disabled**, so nothing runs without
kagent; it holds the one AI assessment of the story."""

SECTION_ASSESSORS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {"Technical": ("carol", "mateo"), "Commercial": ("priya",), "Delivery": ("sven", "alice")}
)

# Must-have texts of the default template (app.schemas.bids.DEFAULT_BID_TEMPLATE).
TENDER: Final = "Signed form of tender"
PRICING: Final = "Pricing schedule"
INSURANCE: Final = "Insurance certificate"
TERMS: Final = "Accepts our standard terms"


@dataclass(frozen=True, slots=True)
class BidSeed:
    bidder: str
    price: str
    contact_name: str
    contact_email: str
    received_days_ago: float
    documents: tuple[tuple[str, str | None], ...]
    """(file in DOCUMENT_DIR, the must-have it is linked to)."""
    notes: str = ""
    scores: Mapping[str, Mapping[str, tuple[int, ...]]] = field(default_factory=dict)
    """Section title -> assessor -> one score per score question, in order."""
    comments: Mapping[str, str] = field(default_factory=dict)
    """Technical assessor -> their comment on the risks question."""
    rejection: str | None = None


BIDS: Final[tuple[BidSeed, ...]] = (
    BidSeed(
        bidder="Northwind Data Ltd",
        price="120000.00",
        contact_name="Hannah Wright",
        contact_email="bids@northwind-data.example",
        received_days_ago=9.2,
        documents=(
            ("northwind-form-of-tender.pdf", TENDER),
            ("northwind-pricing-schedule.pdf", PRICING),
            ("northwind-insurance-certificate.pdf", INSURANCE),
            ("northwind-technical-proposal.docx", None),
        ),
        notes="Came in through the procurement portal; the prototype demo is offered.",
        scores={
            "Technical": {"carol": (5, 4), "mateo": (4, 4)},
            "Commercial": {"priya": (4, 4)},
            "Delivery": {"sven": (4, 5)},
        },
        comments={
            "carol": "Solid design. Ask how scenario recipes are reviewed before they run.",
            "mateo": "Runs in our cluster, so no new data processor to approve.",
        },
    ),
    BidSeed(
        bidder="Tessellate Software",
        price="96000.00",
        contact_name="Ravi Mehta",
        contact_email="ravi.mehta@tessellate.example",
        received_days_ago=8.1,
        documents=(
            ("tessellate-form-of-tender.pdf", TENDER),
            ("tessellate-pricing-schedule.pdf", PRICING),
            ("tessellate-insurance-certificate.pdf", INSURANCE),
            ("tessellate-technical-proposal.docx", None),
        ),
        scores={
            "Technical": {"carol": (4, 3), "mateo": (2, 3)},
            "Commercial": {"priya": (4, 3)},
            "Delivery": {"sven": (3, 3)},
        },
        comments={
            "carol": "A product, not a build: quick to start, but payment methods cost extra.",
            "mateo": "Hosted outside our cloud and no SSO yet: the DPO will have questions.",
        },
    ),
    BidSeed(
        bidder="Quillfield Systems",
        price="84000.00",
        contact_name="Owen Price",
        contact_email="owen@quillfield.example",
        received_days_ago=6.3,
        documents=(
            ("quillfield-form-of-tender.pdf", TENDER),
            ("quillfield-pricing-schedule.pdf", PRICING),
            ("quillfield-technical-proposal.docx", None),
        ),
        rejection="No insurance certificate provided.",
    ),
)

_AI_SCORES: Final[tuple[tuple[int, str, str, str], ...]] = (
    # One per score question of the call, in order: (score, rationale, document, quote).
    (
        3,
        "Meets most requirements out of the box; payment methods and invoices need custom "
        "templates priced separately.",
        "tessellate-technical-proposal.docx",
        "TestForge meets 11 of the 14 requirements out of the box",
    ),
    (
        2,
        "Generated data is stored in the supplier's cloud and single sign-on isn't available yet.",
        "tessellate-technical-proposal.docx",
        "generated data is stored in our cloud region in Ireland",
    ),
    (
        3,
        "The form of tender points to a fixed total in the pricing schedule (which the AI "
        "doesn't read).",
        "tessellate-form-of-tender.pdf",
        "for the total price set out in our pricing schedule",
    ),
    (
        4,
        "Accepts the standard terms without amendment.",
        "tessellate-form-of-tender.pdf",
        "We accept the buyer's standard terms and conditions without amendment.",
    ),
    (
        3,
        "A short configuration plan with a pilot, but no hand-over or support milestones.",
        "tessellate-technical-proposal.docx",
        "configuration in weeks 1-4 and a pilot with one team in week 5",
    ),
    (
        2,
        "No named team: a consultant and a support desk. (Paraphrased: the quote isn't in "
        "the document word for word.)",
        "tessellate-technical-proposal.docx",
        "a dedicated team of five senior engineers",
    ),
)


class Player(Protocol):
    """What the runner offers this story (:class:`app.seed.runner._Player`)."""

    db: AsyncSession
    now: datetime
    keys: dict[int, str]
    user_ids: dict[str, UUID]

    def days_ago(self, days: float) -> datetime: ...

    def add(self, at: datetime, label: str, action: Callable[[], Awaitable[None]]) -> None: ...

    async def principal(self, username: str) -> Principal: ...


_NO_SETTINGS: Final = cast(Settings, None)
"""``update_call`` reads settings only to check a newly named AI assessor; the demo names
none."""


def schedule(player: Player, idea_index: int) -> None:
    """Add the story's steps (TOOLS-3 is ``player.keys[idea_index]`` once submitted; its
    proposal exists well before the first step)."""
    story = _Story(player, idea_index)
    story.add_steps()


class _Story:
    def __init__(self, player: Player, index: int) -> None:
        self.player = player
        self.index = index
        self.bid_ids: dict[str, UUID] = {}
        self.document_ids: dict[str, UUID] = {}

    @property
    def db(self) -> AsyncSession:
        return self.player.db

    @property
    def key(self) -> str:
        return self.player.keys[self.index]

    async def call(self, username: str, rule: Rule) -> tuple[Principal, access.LoadedCall]:
        principal = await self.player.principal(username)
        loaded = await access.load_call(self.db, principal, self.key, rule, write=True)
        return principal, loaded

    def add_steps(self) -> None:
        player = self.player
        player.add(player.days_ago(12), "kenji starts the call for bids on TOOLS-3", self.start)
        player.add(
            player.days_ago(11.9), "kenji sets the deadline and opens the call", self.open_call
        )
        for seed in BIDS:
            entered = player.days_ago(seed.received_days_ago)
            player.add(entered, f"kenji enters {seed.bidder}'s bid", self._enter(seed))
            player.add(
                entered + timedelta(hours=1),
                f"kenji checks {seed.bidder}'s must-haves",
                self._check(seed),
            )
            if seed.rejection is not None:
                player.add(
                    entered + timedelta(hours=2), f"kenji rejects {seed.bidder}", self._reject(seed)
                )
        player.add(player.days_ago(4.6), "kenji assigns the section assessors", self.assign)
        player.add(player.days_ago(3.9), "kenji closes the call to new bids", self.assessing)
        for position, seed in enumerate(BIDS):
            for title, by_person in seed.scores.items():
                for person_position, username in enumerate(by_person):
                    at = player.days_ago(3.5 - 0.4 * position - 0.3 * person_position)
                    if title == "Technical":
                        at -= timedelta(hours=6)
                    player.add(
                        at,
                        f"{username} assesses {title} of {seed.bidder}",
                        self._assess(seed, title, username),
                    )
        player.add(player.days_ago(2.2), "the AI assesses Tessellate Software", self.ai_assessment)

    # --- The call --------------------------------------------------------------------------
    async def start(self) -> None:
        principal = await self.player.principal("kenji")
        loaded = await access.load_idea_for_call(self.db, principal, self.key, write=True)
        require(principal, Rule.BID_MANAGE, loaded.resource)
        await service.create_call(
            self.db,
            principal,
            loaded,
            BidCallCreate(title=CALL_TITLE, description=CALL_DESCRIPTION, currency="GBP"),
        )

    async def open_call(self) -> None:
        principal, loaded = await self.call("kenji", Rule.BID_MANAGE)
        body = BidCallUpdate(
            title=CALL_TITLE,
            description=CALL_DESCRIPTION,
            currency="GBP",
            # A past date (the deadline has passed, on the hour): never shifted by the
            # backdating.
            deadline_at=self.player.days_ago(4).replace(minute=0, second=0, microsecond=0),
            ai_assessor_id=None,
        )
        await service.update_call(self.db, principal, _NO_SETTINGS, loaded, body)
        principal, loaded = await self.call("kenji", Rule.BID_MANAGE)
        await service.change_status(self.db, principal, loaded, BidCallStatus.OPEN)

    async def assessing(self) -> None:
        principal, loaded = await self.call("kenji", Rule.BID_MANAGE)
        await service.change_status(self.db, principal, loaded, BidCallStatus.ASSESSING)

    async def assign(self) -> None:
        principal, loaded = await self.call("kenji", Rule.BID_MANAGE)
        data = await load_call_data(self.db, loaded.call)
        by_title = {section.title: section.id for section in data.sections}
        body = BidAssessorsUpdate(
            sections=[
                BidSectionAssessorsIn(
                    section_id=by_title[title],
                    user_ids=[self.player.user_ids[name] for name in people],
                )
                for title, people in SECTION_ASSESSORS.items()
            ],
            # A future date, 17:00 UTC in four days: the backdating leaves
            # bid_calls.assessment_due_at alone.
            due_at=datetime.combine(
                (self.player.now + timedelta(days=4)).date(), time(17), tzinfo=UTC
            ),
        )
        await service.set_assessors(self.db, principal, loaded, data, body)

    # --- Bids --------------------------------------------------------------------------------
    async def _must_haves(self, call_id: UUID) -> dict[str, BidCallMustHave]:
        rows = await self.db.scalars(
            select(BidCallMustHave).where(BidCallMustHave.call_id == call_id)
        )
        return {row.text: row for row in rows}

    def _enter(self, seed: BidSeed) -> Callable[[], Awaitable[None]]:
        async def enter() -> None:
            principal, loaded = await self.call("kenji", Rule.BID_MANAGE)
            bid = await service.create_bid(
                self.db,
                principal,
                loaded,
                BidIn(
                    bidder=seed.bidder,
                    contact_name=seed.contact_name,
                    contact_email=seed.contact_email,
                    price=Decimal(seed.price),
                    notes=seed.notes,
                ),
            )
            self.bid_ids[seed.bidder] = bid.id
            must_haves = await self._must_haves(loaded.call.id)
            for filename, must_have in seed.documents:
                data = (DOCUMENT_DIR / filename).read_bytes()
                inspected = await documents.inspect(data, filename)
                principal, loaded = await self.call("kenji", Rule.BID_UPLOAD_DOCUMENT)
                locked = await access.load_bid(self.db, principal, loaded, bid.id, for_update=True)
                document = await documents.add_document(
                    self.db,
                    principal,
                    loaded,
                    locked,
                    data=data,
                    inspected=inspected,
                    filename=filename,
                    must_have_id=must_haves[must_have].id if must_have else None,
                    pricing=None,
                )
                await extract_in_session(self.db, document, data)
                self.document_ids[filename] = document.id

        return enter

    def _check(self, seed: BidSeed) -> Callable[[], Awaitable[None]]:
        """The team confirms the standard terms (the form of tender says so)."""

        async def check() -> None:
            principal, loaded = await self.call("kenji", Rule.BID_MANAGE)
            bid = await access.load_bid(
                self.db, principal, loaded, self.bid_ids[seed.bidder], for_update=True
            )
            must_have = (await self._must_haves(loaded.call.id))[TERMS]
            await service.decide_must_have(
                self.db,
                principal,
                loaded,
                bid,
                must_have,
                MustHaveDecisionIn(
                    result=MustHaveResult.MET, note="Stated in the signed form of tender."
                ),
            )

        return check

    def _reject(self, seed: BidSeed) -> Callable[[], Awaitable[None]]:
        assert seed.rejection is not None  # noqa: S101 - only scheduled with one
        reason = seed.rejection

        async def reject() -> None:
            principal, loaded = await self.call("kenji", Rule.BID_DECIDE)
            bid = await access.load_bid(
                self.db, principal, loaded, self.bid_ids[seed.bidder], for_update=True
            )
            await service.reject_bid(self.db, principal, loaded, bid, reason)

        return reject

    # --- Assessments ---------------------------------------------------------------------
    def _assess(self, seed: BidSeed, title: str, username: str) -> Callable[[], Awaitable[None]]:
        async def assess_section() -> None:
            principal, loaded = await self.call(username, Rule.BID_VIEW_BIDS)
            bid = await access.load_bid(self.db, principal, loaded, self.bid_ids[seed.bidder])
            data = await load_call_data(self.db, loaded.call)
            section = next(s for s in data.sections if s.title == title)
            access.require_section_rule(principal, loaded, Rule.BID_ASSESS, section.id)
            questions = data.questions[section.id]
            scores = iter(seed.scores[title][username])
            answers = []
            for question in questions:
                if question.type is BidQuestionType.SCORE:
                    answers.append(BidAnswerIn(question_id=question.id, score=next(scores)))
                elif question.type is BidQuestionType.COMMENT and username in seed.comments:
                    answers.append(
                        BidAnswerIn(question_id=question.id, comment=seed.comments[username])
                    )
            await service.save_my_assessment(
                self.db,
                principal,
                loaded,
                bid,
                section.id,
                MyBidAssessmentIn(answers=answers, submit=True),
            )

        return assess_section

    async def ai_assessment(self) -> None:
        """The demo AI assessor's assessment of Tessellate (as its MCP tool records one,
        quotes checked against the extracted text: the last one isn't found), left out of
        the totals (nobody included it)."""
        agent = await self._agent()
        principal, loaded = await self.call("kenji", Rule.BID_MANAGE)
        bid = await self.db.get(Bid, self.bid_ids["Tessellate Software"])
        assert bid is not None  # noqa: S101 - entered by an earlier step
        questions = list(
            await self.db.scalars(
                select(BidCallQuestion)
                .where(
                    BidCallQuestion.call_id == loaded.call.id,
                    BidCallQuestion.type == BidQuestionType.SCORE,
                )
                .order_by(BidCallQuestion.position)
            )
        )
        sections = {s.id: s.position for s in (await load_call_data(self.db, loaded.call)).sections}
        questions.sort(key=lambda q: (sections[q.section_id], q.position))
        scores = [
            McpBidScoreIn(
                question_id=question.id,
                score=score,
                rationale=rationale,
                evidence=[McpBidEvidenceIn(document_id=self.document_ids[document], quote=quote)],
            )
            for question, (score, rationale, document, quote) in zip(
                questions, _AI_SCORES, strict=True
            )
        ]
        must_haves = await assess.assessable_must_haves(self.db, loaded.call.id)
        findings_by_text: dict[str, tuple[AiMustHaveFinding, str, str, str]] = {
            TENDER: (
                AiMustHaveFinding.MET,
                "The form of tender is signed by a director.",
                "tessellate-form-of-tender.pdf",
                "Signed: Ravi Mehta, Director, for and on behalf of Tessellate Software",
            ),
            INSURANCE: (
                AiMustHaveFinding.MET,
                "Professional indemnity is in force for the contract period.",
                "tessellate-insurance-certificate.pdf",
                "This certificate confirms that the policies above are in force.",
            ),
            TERMS: (
                AiMustHaveFinding.MET,
                "The form of tender accepts the standard terms.",
                "tessellate-form-of-tender.pdf",
                "We accept the buyer's standard terms and conditions without amendment.",
            ),
        }
        findings = []
        for must_have in must_haves:
            finding, rationale, document, quote = findings_by_text[must_have.text]
            findings.append(
                McpBidFindingIn(
                    must_have_id=must_have.id,
                    finding=finding,
                    rationale=rationale,
                    evidence=[
                        McpBidEvidenceIn(document_id=self.document_ids[document], quote=quote)
                    ],
                )
            )
        await assess.record_assessment(
            self.db,
            idea=loaded.idea,
            project=loaded.project,
            call=loaded.call,
            bid=bid,
            agent_id=agent.id,
            scores=scores,
            findings=findings,
        )
        del principal

    async def _agent(self) -> AiAgent:
        """The demo AI assessor: a disabled agent of Internal Tools with its service
        account (no key: it never calls Soundings)."""
        agent_id = uuid4()
        account = User(
            id=uuid4(),
            email=service_account_email(agent_id),
            display_name="Bid assessor (demo)",
            is_service_account=True,
            is_active=True,
            is_platform_admin=False,
        )
        self.db.add(account)
        await self.db.flush()
        agent = AiAgent(
            id=agent_id,
            display_name="Bid assessor (demo)",
            description="Checks must-haves and scores bids with quotes. Disabled in the demo.",
            namespace="soundings",
            name=AI_AGENT_NAME,
            protocol=AiAgentProtocol.KAGENT_V0_10,
            purposes=[AiRunKind.ASSESS_BID.value],
            service_account_id=account.id,
            enabled=False,
        )
        self.db.add(agent)
        await self.db.flush()
        project_id = await self.db.scalar(
            select(Project.id).where(Project.slug == "internal-tools")
        )
        self.db.add(AiAgentProject(agent_id=agent.id, project_id=project_id))
        await self.db.flush()
        return agent
