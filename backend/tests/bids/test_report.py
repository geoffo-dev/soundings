"""The bid evaluation report (contract-phase10 section 13): Markdown and PDF, for call
managers only; the worked example's numbers before and after the award; a manager who owes
an assessment gets no ranks and that bid's scores hidden; what people and bidders wrote is
escaped; at the maximum size (50 bids, 20 must-haves, 8 sections of 15 questions) the PDF
renders within the 5,000-box bound."""

from __future__ import annotations

import io
import time
import warnings
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from PIL import ImageFile
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule
from app.bids import access
from app.bids.report import HIDDEN, NONE, report_document
from app.domain.principal import Principal
from app.proposals.document import build_html
from app.proposals.markdown import TOO_LONG, render_html
from tests.api_keys.helpers import key_client, make_key
from tests.bids.conftest import (
    API,
    AsUser,
    Crew,
    add_bid,
    assert_problem,
    assign,
    call_url,
    ok,
    open_call,
    qualify,
    sections_by_title,
    start,
    submit,
    to_assessing,
)
from tests.bids.test_scoring import worked_example
from tests.factories import set_researcher

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        from app.proposals import pdf_child
    except (ImportError, OSError):  # pragma: no cover - a host without Pango
        pdf_child = None  # type: ignore[assignment]
ImageFile.LOAD_TRUNCATED_IMAGES = False

needs_pdf = pytest.mark.skipif(pdf_child is None, reason="WeasyPrint can't load here")


def row(*cells: str) -> str:
    """A Markdown table row; ``"-"`` stands for an empty cell (an en dash)."""
    return "| " + " | ".join(NONE if cell == "-" else cell for cell in cells) + " |"


def report_url(crew: Crew, kind: str) -> str:
    return call_url(crew, f"/report/{kind}")


# --- The worked example (contract section 8.1) ---------------------------------------------
async def test_the_markdown_report(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    case = await worked_example(crew, api, db_session)
    owner = case["owner"]

    response = await owner.get(report_url(crew, "markdown"))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{crew.key}-bid-evaluation.md"'
    )
    text = response.text
    assert "# Data platform build" in text
    assert "- Status: Being assessed" in text
    assert "- Bids: 3 received, 1 rejected" in text
    assert "- Assessed: 10 of 10 (complete)" in text
    header = (
        "| Rank | Bidder | Status | Technical (40 %) | Commercial (40 %) | Delivery (20 %) "
        "| Price | Price score | Total | AI | Assessed |"
    )
    assert header in text
    a_cells = ("86.7", "80.0", "90.0", "GBP 120,000.00", "4.00", "84.7", "-", "5 of 5")
    assert row("1", "A Ltd", "Qualified", *a_cells) in text
    # B's first question disagrees (4 and 2): its Technical score is flagged.
    b_cells = ("60.0 ‡", "90.0", "70.0", "GBP 96,000.00", "5.00", "74.0", "-", "5 of 5")
    assert row("2", "B Ltd", "Qualified", *b_cells) in text
    c_cells = ("-", "-", "-", "GBP 80,000.00", "-", "-", "-", "0 of 5")
    assert row("-", "C Ltd", "Rejected", *c_cells) in text
    # Must-haves: counts and the failing items by name.
    assert row("A Ltd", "1", "0", "0", "0", "-") in text
    assert "| C Ltd | 0 | 0 | 1 | 0 | Insurance certificate (missing) |" in text
    assert "- **C Ltd**, rejected " in text
    assert "by Kenji Owner: No insurance." in text
    assert "- **Technical** (40 %): Carol Tech (2 of 2), Mateo Tech (2 of 2)" in text
    assert "- **Commercial** (40 %): Priya Commercial (2 of 2)" in text
    assert "_Not awarded yet._" in text

    # The award changes the statuses and the award line, not the numbers or ranks.
    ok(
        await owner.post(
            call_url(crew, "/award"), {"bid_id": case["a"]["id"], "reason": "Best value."}
        )
    )
    after = (await owner.get(report_url(crew, "markdown"))).text
    assert row("1", "A Ltd", "Awarded", *a_cells) in after
    assert "| 2 | B Ltd | Unsuccessful | 60.0 ‡ |" in after
    assert "Awarded to **A Ltd** on " in after
    assert "by Kenji Owner." in after
    assert "Reason: Best value." in after


async def test_only_call_managers_get_the_report(
    app: FastAPI, crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    case = await worked_example(crew, api, db_session)
    del case
    for user in (crew.admin, crew.platform):
        assert (await (await api(user)).get(report_url(crew, "markdown"))).status_code == 200
    # Section assessors (also the price section's), members and viewers: 403.
    for user in (crew.tech1, crew.commercial, crew.member, crew.viewer):
        for kind in ("markdown", "pdf"):
            response = await (await api(user)).get(report_url(crew, kind))
            assert_problem(response, 403, "forbidden")
    # Someone without a role in the private project, also as the idea's researcher: 404.
    await set_researcher(db_session, crew.idea, crew.outsider)
    response = await (await api(crew.outsider)).get(report_url(crew, "markdown"))
    assert_problem(response, 404, "not_found")
    # A key: read is enough (an export is a read); without read, 403 insufficient_scope.
    for scopes, status in ((["read"], 200), (["mcp"], 403)):
        secret = await make_key(db_session, crew.owner, scopes=scopes)
        async with key_client(app, secret) as client:
            response = await client.get(API + report_url(crew, "markdown"))
        assert response.status_code == status, response.text


async def test_a_manager_who_owes_an_assessment_gets_no_ranks(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    a = await add_bid(owner, crew, "A Ltd", price="100.00")
    b = await add_bid(owner, crew, "B Ltd", price="100.00")
    for bid in (a, b):
        await qualify(db_session, bid["id"], crew.owner)
    view = await assign(
        owner,
        crew,
        view,
        {
            "Technical": [crew.tech1, crew.owner],
            "Commercial": [crew.commercial],
            "Delivery": [crew.delivery],
        },
    )
    await to_assessing(owner, crew)
    sections = sections_by_title(view)
    for user, title in (
        (crew.tech1, "Technical"),
        (crew.commercial, "Commercial"),
        (crew.delivery, "Delivery"),
    ):
        who = await api(user)
        for bid in (a, b):
            await submit(who, crew, bid["id"], sections[title], 4)
    await submit(owner, crew, a["id"], sections["Technical"], 3)  # B still owed

    text = (await owner.get(report_url(crew, "markdown"))).text

    assert "the ranking shows once you have submitted yours" in text
    assert "_No ranks while you owe assessments._" in text
    rows = [line for line in text.splitlines() if line.startswith(f"| {NONE} | ")]
    assert len(rows) == 2  # no rank for any bid
    b_row = next(line for line in rows if "| B Ltd |" in line)
    assert f"| {HIDDEN} |" in b_row  # B's Technical score and total
    assert b_row.count(HIDDEN) == 2
    a_row = next(line for line in rows if "| A Ltd |" in line)
    assert HIDDEN not in a_row
    # The admin (not assessing) sees the ranking.
    admin_text = (await (await api(crew.admin)).get(report_url(crew, "markdown"))).text
    assert "| 1= | " in admin_text or "| 1 | " in admin_text


async def test_what_people_wrote_is_escaped(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew, title="Build | *bold* [x](http://evil.example) <b>hi</b>")
    await open_call(owner, crew)
    bid = await add_bid(
        owner, crew, "**Evil** | Ltd [click](javascript:alert(1)) <img src=x> # h", price="5.00"
    )
    ok(
        await owner.put(
            call_url(crew, f"/bids/{bid['id']}/rejection"),
            {"reason": "Nope _really_ ![i](http://x/y.png) | col"},
        )
    )

    text = (await owner.get(report_url(crew, "markdown"))).text

    assert "\\*\\*Evil\\*\\* \\| Ltd \\[click\\](javascript:alert(1)) \\<img src=x\\> \\# h" in text
    assert "Nope \\_really\\_ !\\[i\\](http://x/y.png) \\| col" in text
    # Rendered the way the PDF renders each section (the front matter is YAML, not shown):
    # no markup came through.
    html = render_html(text.split("---\n", 2)[2])
    for tag in ("<strong>Evil", "<a ", "<img", "<em>really", "<b>hi"):
        assert tag not in html
    assert "**Evil**" in html.replace("&quot;", '"')


# --- The PDF -------------------------------------------------------------------------------
@needs_pdf
async def test_the_pdf_report(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    case = await worked_example(crew, api, db_session)

    response = await case["owner"].get(report_url(crew, "pdf"))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{crew.key}-bid-evaluation.pdf"'
    )
    reader = PdfReader(io.BytesIO(response.content))
    assert reader.metadata is not None
    assert reader.metadata.title == "Data platform build"
    text = " ".join(page.extract_text() for page in reader.pages)
    for expected in ("BID EVALUATION REPORT", "Ranking", "A Ltd", "84.7", "74.0", "No insurance."):
        assert expected in text


def _max_template() -> dict[str, Any]:
    weights = [12, 12, 12, 12, 13, 13, 13, 13]
    sections = []
    for index, weight in enumerate(weights):
        questions: list[dict[str, Any]] = [
            {
                "text": f"Question {index + 1}.{q + 1} on the bid's approach",
                "type": "score",
                "weight": 1,
            }
            for q in range(15)
        ]
        if index == 1:
            questions[0] = {"text": "Price", "type": "price", "weight": 1}
        sections.append(
            {
                "title": f"Section {index + 1} with a longer title",
                "weight": weight,
                "questions": questions,
            }
        )
    must_haves = [
        {"text": f"Must-have number {n + 1}: a required statement", "kind": "confirmation"}
        for n in range(20)
    ]
    return {"scale": ["0", "1", "2", "3", "4", "5"], "sections": sections, "must_haves": must_haves}


@needs_pdf
async def test_the_report_at_the_maximum_size(
    app: FastAPI, crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    admin = await api(crew.admin)
    ok(await admin.put(f"/projects/{crew.project.slug}/bid-template", _max_template()))
    owner = await api(crew.owner)
    await start(owner, crew, title="A very large call for bids " * 3)
    await open_call(owner, crew)
    for n in range(50):
        bid = await add_bid(
            owner, crew, f"Supplier number {n + 1} Holdings Limited", price="1000.00"
        )
        if n % 5 == 0:
            ok(
                await owner.put(
                    call_url(crew, f"/bids/{bid['id']}/rejection"),
                    {"reason": "Missing several required statements. " * 10},
                )
            )

    principal = Principal(user=crew.owner)
    loaded = await access.load_call(db_session, principal, crew.key, Rule.BID_VIEW_SCORES)
    document = await report_document(
        db_session, principal, loaded, app.state.settings, app, now=datetime.now(UTC)
    )
    html = build_html(document)
    assert TOO_LONG not in html  # every row fits the 5,000-box bound
    assert html.count("<tr") >= 2 * 51
    started = time.monotonic()
    assert pdf_child is not None
    pdf = pdf_child.render_document(document)
    assert time.monotonic() - started < 20  # the child's time limit
    pages = PdfReader(io.BytesIO(pdf)).pages
    assert len(pages) >= 2
    # Through the route too (the child process).
    response = await owner.get(report_url(crew, "pdf"))
    assert response.status_code == 200, response.text
