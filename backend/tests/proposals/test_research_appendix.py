"""The exports' "Research and consultation" appendix (contract-phase8 section 3.8): only
while the project's step is on and an item is answered; answered active items in checklist
order, as plain text (escaped Markdown with hard breaks; an escaped PDF paragraph with line
breaks), who answered and when; never unanswered or removed items; everyone who exports
gets it (no score data)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EvaluatorState, ResearchStep
from app.models.idea import Idea
from app.models.research import ResearchChecklistItem
from app.proposals.document import ExportResearchItem, build_html, build_markdown
from tests.factories import add_evaluator
from tests.proposals.conftest import AsUser, Team, proposal_url, start
from tests.proposals.test_document import document
from tests.research.conftest import answer, set_step

ANSWER = "Legal (contracts team), 3 Oct: fine if we keep the standard terms.\n- not a list\n# not a heading"  # noqa: E501
DAY = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


def _item(**overrides: object) -> ExportResearchItem:
    values: dict[str, object] = {
        "title": "Departments or teams consulted",
        "answer": ANSWER,
        "answered_by": "Olive Owner",
        "answered_at": DAY,
        "updated_by": "Olive Owner",
        "updated_at": DAY,
    }
    values.update(overrides)
    return ExportResearchItem(**values)  # type: ignore[arg-type]


# --- The document ------------------------------------------------------------------------
def test_the_markdown_appendix_reads_exactly_as_typed() -> None:
    markdown = build_markdown(document(research=(_item(),)))

    tail = markdown.split("## Research and consultation\n\n", 1)[1]
    assert tail == (
        "### Departments or teams consulted\n\n"
        "Legal (contracts team), 3 Oct: fine if we keep the standard terms.\\\n"
        "\\- not a list\\\n"
        "\\# not a heading\n\n"
        "_Answered by Olive Owner on 3 October 2026_\n"
    )


def test_no_appendix_without_answered_items() -> None:
    assert "Research and consultation" not in build_markdown(document())
    assert "appendix-research" not in build_html(document())


def test_the_byline_names_a_later_change() -> None:
    same_day = _item(updated_at=DAY.replace(hour=17))
    later = _item(updated_at=datetime(2026, 10, 5, tzinfo=UTC))
    someone_else = _item(updated_by="Ada Admin", updated_at=DAY.replace(hour=10))
    gone = _item(answered_by=None, updated_by=None)

    assert same_day.byline == "Answered by Olive Owner on 3 October 2026"
    assert later.byline == (
        "Answered by Olive Owner on 3 October 2026, updated by Olive Owner on 5 October 2026"
    )
    assert someone_else.byline == (
        "Answered by Olive Owner on 3 October 2026, updated by Ada Admin on 3 October 2026"
    )
    assert gone.byline == "Answered on 3 October 2026"


def test_the_pdf_appendix_is_escaped_plain_text_in_the_contents() -> None:
    html = build_html(document(research=(_item(answer="<b>bold?</b>\nnext line"),)))

    assert '<a href="#appendix-research">Research and consultation</a>' in html
    assert '<section class="section research" id="appendix-research">' in html
    assert "&lt;b&gt;bold?&lt;/b&gt;<br>\nnext line" in html
    assert "<b>bold?" not in html
    assert '<p class="byline">Answered by Olive Owner on 3 October 2026</p>' in html


def test_a_long_appendix_is_cut_at_the_box_budget() -> None:
    lines = "\n".join(f"line {n}" for n in range(2_000))
    html = build_html(
        document(research=tuple(_item(title=f"Item {n}", answer=lines) for n in range(10)))
    )

    assert "too-long" in html


# --- Through the API ---------------------------------------------------------------------
async def _markdown(api: AsUser, user: object, key: str) -> str:
    response = await (await api(user)).get(f"{proposal_url(key)}/markdown")  # type: ignore[arg-type]
    assert response.status_code == 200, response.text
    return response.text


async def test_the_export_ends_with_the_answered_items(
    api: AsUser, team: Team, key: str, idea: Idea, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    await answer(db_session, idea, items[1], team.owner, "Finance, 2 Oct: budget is there.")
    await answer(db_session, idea, items[0], team.owner, "Nothing similar in Soundings.")
    await start(await api(team.admin), key)  # Shortlisted -> Proposal: answered, so free
    evaluator = team.evaluators[0]
    await add_evaluator(db_session, idea, evaluator, state=EvaluatorState.INVITED)

    markdown = await _markdown(api, evaluator, key)  # a pending evaluator exports it too

    appendix = markdown.split("## Research and consultation\n\n", 1)[1]
    assert appendix.startswith("### Not already being done elsewhere\n\nNothing similar")
    assert "### Departments or teams consulted\n\nFinance, 2 Oct: budget is there." in appendix
    assert "Data protection considered" not in appendix  # unanswered
    assert "_Answered by Olive Owner on " in appendix


async def test_no_appendix_while_the_step_is_off_or_for_removed_items(
    api: AsUser, team: Team, key: str, idea: Idea, db_session: AsyncSession
) -> None:
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    await answer(db_session, idea, items[0], team.owner)
    await answer(db_session, idea, items[1], team.owner)
    await start(await api(team.owner), key)
    await db_session.execute(
        update(ResearchChecklistItem)
        .where(ResearchChecklistItem.id == items[1].id)
        .values(archived_at=DAY)
    )
    await db_session.commit()

    with_one = await _markdown(api, team.owner, key)
    await set_step(db_session, team.project, ResearchStep.OFF)
    without = await _markdown(api, team.owner, key)

    assert "### Not already being done elsewhere" in with_one
    assert "Departments or teams consulted" not in with_one
    assert "Research and consultation" not in without


async def test_the_pdf_has_the_appendix(
    api: AsUser, team: Team, key: str, idea: Idea, db_session: AsyncSession
) -> None:
    import warnings
    from io import BytesIO

    import pytest
    from PIL import ImageFile
    from pypdf import PdfReader

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            from app.proposals import pdf_child  # noqa: F401 - the renderer must load
        except (ImportError, OSError) as missing:  # pragma: no cover - no Pango here
            pytest.skip(f"WeasyPrint can't load: {missing}")
    ImageFile.LOAD_TRUNCATED_IMAGES = False  # as tests/proposals/test_exports.py
    items = await set_step(db_session, team.project, ResearchStep.BEFORE_PROPOSAL)
    await answer(db_session, idea, items[0], team.owner, "Nothing similar in Soundings.")
    await answer(db_session, idea, items[1], team.owner, "Legal, 3 Oct: fine.")
    await start(await api(team.owner), key)

    response = await (await api(team.owner)).get(f"{proposal_url(key)}/pdf")

    assert response.status_code == 200, response.text
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)
    assert "Research and consultation" in text
    assert "Legal, 3 Oct: fine." in text
