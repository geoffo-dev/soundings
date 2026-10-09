"""The demo story's Phase 8 parts (contract-phase8 section 3.14): proposal templates, the
research step and its answers, and the two proposals that show them, as plain data.

* **Internal Tools** runs the research step **before evaluation** with the default
  checklist and a custom template (Summary, Problem, Solution, Effort & rollout, Risks,
  The ask). Every idea that went on to evaluation passed through Research with its
  required items answered by its owner first; two ideas are in Research now, one with the
  checklist complete and one with a required item open. Its idea in Proposal has a
  proposal in the custom template.
* **Sustainability** runs it **before the proposal**, with a "Carbon impact" section added
  after Benefits / revenue. Its ideas that reached Proposal passed through Research; its
  idea in Proposal has a proposal with Carbon impact written; a Shortlisted idea carries
  a partly answered checklist.
* **Customer Innovation** keeps the defaults with the step off.

Answers are written as consultation records ("Legal (contracts team), 3 Oct: ..."): who
was asked and what they said, never a person picker. The runner plays them through the
same services as a person would (:mod:`app.seed.runner`): no gate bypass.

Phase 8b (contract-phase8b section 11, :data:`ASSIGNMENTS`): bob, who isn't a member of the
private Internal Tools, researches TOOLS-12 as its guest (asked by dave, the project's
admin: in a private project only admins name someone outside it); amara researches GREEN-6,
which she owns (asked by alice); alice's research of GREEN-5 is overdue.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.models.enums import ResearchStep
from app.schemas.proposals import DEFAULT_PROPOSAL_TEMPLATE
from app.seed.content import md

__all__ = [
    "ANSWERS",
    "ASSIGNMENTS",
    "PROPOSALS",
    "RESEARCH_STEPS",
    "TEMPLATES",
    "AssignmentSeed",
    "TemplateSeed",
]

TemplateSeed = tuple[str | None, str, str]
"""A template section: its key (``None``: a new section, keyed from its title), title, hint."""

_DEFAULTS: Final = {
    str(section.key): (str(section.key), section.title, section.prompt)
    for section in DEFAULT_PROPOSAL_TEMPLATE
}

TEMPLATES: Final[MappingProxyType[str, tuple[TemplateSeed, ...]]] = MappingProxyType(
    {
        # Keys summary, problem, solution, effort_rollout, risks, the_ask; the unused
        # defaults are deleted (nothing refers to them yet), so none is "removed".
        "TOOLS": (
            _DEFAULTS["summary"],
            _DEFAULTS["problem"],
            _DEFAULTS["solution"],
            (None, "Effort & rollout", "Who builds it, how long it takes and how we roll it out."),
            _DEFAULTS["risks"],
            (None, "The ask", "People, time or budget we need, and from whom."),
        ),
        # The default eight with "Carbon impact" (key carbon_impact) after Benefits.
        "GREEN": (
            *(
                _DEFAULTS[key]
                for key in ("summary", "problem", "solution", "market", "cost", "benefits")
            ),
            (None, "Carbon impact", "Tonnes of CO2e a year, how we measured it, and scope."),
            _DEFAULTS["risks"],
            _DEFAULTS["next_steps"],
        ),
    }
)

RESEARCH_STEPS: Final[MappingProxyType[str, ResearchStep]] = MappingProxyType(
    {"TOOLS": ResearchStep.BEFORE_EVALUATION, "GREEN": ResearchStep.BEFORE_PROPOSAL}
)
"""Projects with the research step on (the default checklist), from their first day."""

ANSWERS: Final[MappingProxyType[str, tuple[str | None, str | None, str | None]]] = MappingProxyType(
    {
        # --- Internal Tools: every idea that went on to evaluation ------------------
        "Single sign-on for the staging environments": (
            "Searched Soundings and the platform roadmap: nothing similar. Security "
            "had it on a wish list, not planned.",
            "Security (identity team): want staging behind SSO before the audit. IT "
            "service desk: fewer password resets.",
            "Only staff accounts; no customer data in staging.",
        ),
        "Replace the wiki with docs-as-code": (
            "The data team tried docs-as-code in 2024 for their own docs and kept it; "
            "nobody tried it company-wide.",
            "Support and HR edit the wiki daily and said they won't use Git. Data team: "
            "happy to share their setup.",
            None,
        ),
        "Self-service test data generator": (
            "QA has a script for orders only; the payments team copies production by "
            "hand. Nothing shared.",
            "QA (test automation), 2 Sep: will help with the order rules. Payments: "
            "need card numbers that pass Luhn but never charge.",
            "Data protection officer, 3 Sep: fine as long as nothing is copied from "
            "production; generated data only.",
        ),
        "Automated quarterly access reviews": (
            "Checked with the security team: the spreadsheet process is all there is.",
            "Security (GRC), 6 Sep: they want it before the next ISO audit. HR: can "
            "send leaver dates nightly.",
            "Reads names and group memberships only; access stays within security.",
        ),
        "On-call handover checklist bot": (
            "The SRE team has a checklist doc; no bot anywhere.",
            "SRE (on-call leads): like it, but the paging tool may add handovers next year.",
            None,
        ),
        "Cloud cost dashboard per team": (
            "Finance has a monthly cost report by department, not by team; nothing live.",
            "Finance (FP&A), 15 Sep: want it, can map cost centres to teams. Platform: "
            "tags are on 80% of resources.",
            None,
        ),
        "Laptop setup in one script": (
            "IT has an image for Windows laptops only; developers set up macOS by hand.",
            "IT service desk, 18 Sep: will review the script and host it. Security: "
            "must enable disk encryption first.",
            "No personal data involved.",
        ),
        "Meeting-free Wednesday calendar guard": (
            "HR ran a meeting-free Friday pilot in 2023, by policy only, no tooling.",
            "HR (people experience), 22 Sep: supportive if managers can override. "
            "Workplace team: no objections.",
            "Reads calendar free/busy only, through the existing calendar app.",
        ),
        "Feature-flag clean-up reminders": (
            "The web team cleans up flags in their sprint retro; nothing automated.",
            "Web and mobile leads, 25 Sep: yes, if reminders go to the flag's owner, "
            "not the whole team.",
            None,
        ),
        "Shared staging database snapshots": (
            "QA restores a nightly dump for their own tests; nobody else can use it.",
            "Platform (databases), 30 Sep: snapshots are cheap on the new cluster. "
            "QA: will share their restore script.",
            "Staging holds generated test data only; checked with the DPO.",
        ),
        # In Research now: one complete, one with a required item open.
        "Internal status page for developer tooling": (
            "Searched Soundings: the closest is the status page for order and API "
            "incidents in Customer Innovation, which is for customers. Nothing internal.",
            "SRE (on-call leads), 4 Oct: will feed CI and registry health checks. "
            "Platform channel moderators: would pin it.",
            "No personal data: service health only.",
        ),
        "Chat command to request system access": (
            "Security's access form is the only route today; the chat team has "
            "nothing similar planned.",
            None,
            None,
        ),
        # --- Sustainability: ideas that reached Proposal, and one Shortlisted ---------
        "LED lighting retrofit for the Leeds warehouse": (
            "Facilities did the Bristol office in 2023; no warehouse has done it.",
            "Facilities (estates), 10 Aug: happy to run it. Finance: payback under "
            "three years is fine.",
            None,
        ),
        "Cycle-to-work scheme": (
            "HR looked at a scheme in 2021 and stopped when the provider closed.",
            "HR (reward), 18 Aug: will choose a provider. Payroll: salary sacrifice "
            "is set up already.",
            "Payroll handles the salary sacrifice; we share names only with the "
            "provider, checked with the DPO.",
        ),
        "Reusable packaging for B2B deliveries": (
            "Searched Soundings and asked logistics: a crate trial ran in 2022 for "
            "one customer and stopped when its contract ended.",
            "Logistics (north-west depot), 20 Sep: crates fit the vans, collection "
            "on the next delivery works. Legal (contracts team), 22 Sep: fine if we "
            "keep the standard terms and add a deposit clause.",
            "Customer contact names only, already in the delivery system.",
        ),
        "Heat pumps for the Bristol office": (
            "Facilities quoted heat pumps for the Leeds office in 2024 but the landlord said no.",
            None,
            None,
        ),
    }
)
"""Per idea title: an answer per default checklist item (``None``: unanswered), written
by the idea's owner before the idea moved past Research."""

AssignmentSeed = tuple[str, str, str, float, float | None]
"""Phase 8b: (idea title, researcher, asked by, asked how many days ago, due in how many
days from now: negative = overdue, ``None`` = no due date)."""

ASSIGNMENTS: Final[tuple[AssignmentSeed, ...]] = (
    # TOOLS-12 (one required item open): bob, outside the private project, as its guest.
    ("Chat command to request system access", "bob", "dave", 1.0, 3.0),
    # GREEN-6 (Shortlisted, partly answered): its owner, asked explicitly by alice.
    ("Heat pumps for the Bristol office", "amara", "alice", 3.0, None),
    # GREEN-5 (Shortlisted, nothing answered): overdue, for My work's screenshot.
    ("Move cloud workloads to a low-carbon region", "alice", "sven", 6.0, -2.0),
)

PROPOSALS: Final[MappingProxyType[str, MappingProxyType[str, str]]] = MappingProxyType(
    {
        "Self-service test data generator": MappingProxyType(
            {
                "problem": md(
                    """
                    Every team builds its own test accounts. QA spends about a day a
                    sprint on it, and the payments team copies production data by hand,
                    which the DPO wants stopped.
                    """
                ),
                "solution": md(
                    """
                    A small service in the developer portal that generates **realistic,
                    anonymised** customers, orders and payment methods on demand:

                    - pick a scenario ("returning customer with a failed payment")
                    - get the accounts in staging within a minute
                    - everything generated is deleted after 30 days
                    """
                ),
                "effort_rollout": md(
                    """
                    Two developers for six weeks, then QA moves its scripts over. Roll
                    out to QA first, then payments, then everyone.
                    """
                ),
                "risks": md(
                    """
                    - Generated data drifts from real data: QA reviews the scenarios each
                      quarter.
                    - Teams keep copying production: we turn that access off once the
                      generator covers their cases.
                    """
                ),
            }
        ),
        "Reusable packaging for B2B deliveries": MappingProxyType(
            {
                "problem": md(
                    """
                    Business customers get several boxes a week from us: about 70 tonnes
                    of cardboard a year that they pay to dispose of.
                    """
                ),
                "solution": md(
                    """
                    Returnable crates, collected on the next delivery, starting with five
                    large customers served by the north-west depot.
                    """
                ),
                "cost": md(
                    """
                    About 2,400 crates at £18 each, plus washing at the depot. Crates last
                    five years.
                    """
                ),
                "benefits": md(
                    """
                    Cardboard and tape savings of roughly £40,000 a year at full rollout,
                    and a visible change customers asked for.
                    """
                ),
                "carbon_impact": md(
                    """
                    **About 95 t CO2e a year** at full rollout (scope 3: packaging), from
                    the supplier's cardboard footprint minus crate washing and the return
                    trips, which ride on existing deliveries.
                    """
                ),
                "risks": md(
                    """
                    Crates that don't come back: a deposit per crate, in the contract
                    (Legal agreed the clause).
                    """
                ),
            }
        ),
    }
)
"""Per idea title: the proposal its owner starts when the idea reaches Proposal, and the
sections they write (the Summary starts as the idea's summary)."""
