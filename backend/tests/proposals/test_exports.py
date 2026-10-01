"""Exports through the API (contract-phase4 3.4, 3.10; tests first): who may export, the
aggregate line only for people who may see scores, the project's effective branding in
the PDF, safe filenames, the per-user limit, the 20-second kill and what a hostile
proposal turns into."""

from __future__ import annotations

import hashlib
import io
import warnings
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from PIL import ImageFile
from pypdf import PdfReader
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branding import BrandAsset, BrandingProfile
from app.models.enums import BrandAssetKind, BrandFont, EvaluatorState, ProjectVisibility
from app.models.idea import Idea
from app.models.project import Project
from app.proposals import pdf
from app.proposals.pdf import Renderer
from app.services.scoring import recompute_aggregates
from tests.factories import add_evaluator, make_user
from tests.proposals import children
from tests.proposals.conftest import Api, AsUser, Team, assert_problem, ok, proposal_url, start

with warnings.catch_warnings():
    # WeasyPrint warns at import where HarfBuzz-Subset is missing (it uses fontTools).
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        from app.proposals import pdf_child  # noqa: F401 - the renderer must load
    except (ImportError, OSError) as missing:  # pragma: no cover - a host without Pango
        pytest.skip(f"WeasyPrint can't load: {missing}", allow_module_level=True)
# Importing WeasyPrint turns on Pillow's LOAD_TRUNCATED_IMAGES for the whole process. Only
# the PDF child imports it in production; here, keep the rest of the session's Pillow
# strict (the branding upload tests expect truncated PNGs to fail).
ImageFile.LOAD_TRUNCATED_IMAGES = False


def png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (160, 48), (11, 110, 79, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def resources(page: Any) -> dict[str, Any]:
    found: dict[str, Any] = page["/Resources"].get_object()
    return found


def pdf_text(data: bytes) -> list[str]:
    return [page.extract_text() for page in PdfReader(io.BytesIO(data)).pages]


async def save(client: Api, key: str, section: str, text: str) -> None:
    ok(
        await client.put(
            f"{proposal_url(key)}/sections/{section}", {"body_md": text, "base_version": 1}
        )
    )


@pytest.fixture
async def written(api: AsUser, team: Team, key: str) -> str:
    owner = await api(team.owner)
    await start(owner, key)
    await save(owner, key, "problem", "# Calls\n\nCustomers call us **4,000** times a month.")
    await save(owner, key, "risks", "Fraud: we cap refunds at £50.")
    return key


@pytest.fixture
async def scored(db_session: AsyncSession, team: Team, idea: Idea) -> Idea:
    """Two submitted evaluations (aggregate 3.0 from 2) and one pending evaluator."""
    for evaluator in team.evaluators[:2]:
        await add_evaluator(db_session, idea, evaluator, state=EvaluatorState.SUBMITTED)
    await add_evaluator(db_session, idea, team.evaluators[2], state=EvaluatorState.INVITED)
    await recompute_aggregates(db_session, idea_ids=[idea.id])
    await db_session.commit()
    return idea


@pytest.fixture
def warm_renderer(monkeypatch: pytest.MonkeyPatch) -> Iterator[Renderer]:
    renderer = Renderer()
    monkeypatch.setattr(pdf, "_renderer", renderer)
    yield renderer
    renderer.stop()


# --- Markdown -----------------------------------------------------------------------
async def test_the_markdown_export_is_a_download(api: AsUser, team: Team, written: str) -> None:
    response = await (await api(team.member)).get(f"{proposal_url(written)}/markdown")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{written}-proposal.md"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    text = response.content.decode("utf-8")
    assert text.startswith('---\ntitle: "Self-service refunds"\n')
    assert f'idea: "{written}"' in text
    assert 'owner: "Olive Owner"' in text
    assert "- Exported " in text
    assert " by Max Member\n" in text
    assert "## Problem\n\n### Calls\n\nCustomers call us **4,000** times a month.\n" in text
    assert "## Solution\n\n_Not written yet._" in text
    assert "\r" not in text


@pytest.mark.parametrize("who", ["viewer", "platform", "admin"])
async def test_everyone_who_can_view_the_idea_may_export(
    api: AsUser, team: Team, written: str, who: str
) -> None:
    response = await (await api(getattr(team, who))).get(f"{proposal_url(written)}/markdown")
    assert response.status_code == 200


async def test_internal_non_members_may_export_outsiders_may_not(
    api: AsUser, team: Team, written: str, db_session: AsyncSession
) -> None:
    outsider = await api(team.outsider)
    assert_problem(await outsider.get(f"{proposal_url(written)}/markdown"), 404, "not_found")
    await db_session.execute(
        update(Project)
        .where(Project.id == team.project.id)
        .values(visibility=ProjectVisibility.INTERNAL)
    )
    await db_session.commit()
    assert (await outsider.get(f"{proposal_url(written)}/markdown")).status_code == 200


async def test_no_proposal_no_export(api: AsUser, team: Team, key: str) -> None:
    member = await api(team.member)
    assert_problem(await member.get(f"{proposal_url(key)}/markdown"), 404, "not_found")
    assert_problem(await member.get(f"{proposal_url(key)}/pdf"), 404, "not_found")


async def test_the_aggregate_line_only_for_people_who_may_see_scores(
    api: AsUser, team: Team, written: str, scored: Idea
) -> None:
    for user in (team.member, team.viewer, team.evaluators[0], team.admin):
        text = (await (await api(user)).get(f"{proposal_url(written)}/markdown")).text
        assert "- Aggregate score 3.0 from 2 evaluations\n" in text, user.display_name
        assert "aggregate_score: 3.0" in text

    pending = (await (await api(team.evaluators[2])).get(f"{proposal_url(written)}/markdown")).text
    assert "score" not in pending.lower()
    assert "evaluations" not in pending


async def test_status_labels_are_the_projects(
    api: AsUser, team: Team, written: str, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project)
        .where(Project.id == team.project.id)
        .values(status_labels={"proposal": "Business case"})
    )
    await db_session.commit()
    text = (await (await api(team.member)).get(f"{proposal_url(written)}/markdown")).text
    assert 'status: "Business case"' in text


# --- PDF ----------------------------------------------------------------------------
@pytest.mark.usefixtures("warm_renderer")
async def test_the_pdf_export_is_a_branded_download(
    api: AsUser, team: Team, written: str, scored: Idea, db_session: AsyncSession
) -> None:
    data = png()
    logo = BrandAsset(
        id=uuid4(),
        project_id=team.project.id,
        kind=BrandAssetKind.LOGO,
        content_type="image/png",
        data=data,
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        width=160,
        height=48,
    )
    db_session.add(logo)
    await db_session.flush()
    db_session.add_all(
        [
            BrandingProfile(
                id=uuid4(),
                project_id=None,
                app_name="Acme Ideas",
                primary_color="#0b6e4f",
                font=BrandFont.IBM_PLEX_SANS,
            ),
            BrandingProfile(
                id=uuid4(),
                project_id=team.project.id,
                primary_color="#7c3aed",
                logo_asset_id=logo.id,
            ),
        ]
    )
    await db_session.commit()

    response = await (await api(team.admin)).get(f"{proposal_url(written)}/pdf")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{written}-proposal.pdf"'
    )
    reader = PdfReader(io.BytesIO(response.content))
    assert reader.metadata is not None
    assert reader.metadata.creator == "Acme Ideas"  # the global app name, inherited
    assert reader.metadata.title == "Self-service refunds"
    pages = [page.extract_text() for page in reader.pages]
    assert "Aggregate score 3.0 from 2 evaluations" in pages[0]
    assert "Exported" in pages[0]
    assert "by Ada Admin" in pages[0]
    assert "Customers call us 4,000 times a month." in "\n".join(pages)
    assert "Fraud: we cap refunds at £50." in "\n".join(pages)
    assert f"Page 2 of {len(pages)}" in pages[1]
    assert resources(reader.pages[0]).get("/XObject"), "the project's logo is on the cover"
    fonts = {
        str(font.get_object()["/BaseFont"]).split("+", 1)[-1]
        for page in reader.pages
        for font in resources(page).get("/Font", {}).values()
    }
    assert "Soundings-Brand" in fonts


@pytest.mark.usefixtures("warm_renderer")
async def test_a_pending_evaluators_pdf_has_no_score(
    api: AsUser, team: Team, written: str, scored: Idea
) -> None:
    response = await (await api(team.evaluators[2])).get(f"{proposal_url(written)}/pdf")
    assert response.status_code == 200
    text = "\n".join(pdf_text(response.content))
    assert "score" not in text.lower()


@pytest.mark.usefixtures("warm_renderer")
async def test_a_hostile_proposal_exports_safely(api: AsUser, team: Team, key: str) -> None:
    owner = await api(team.owner)
    await start(owner, key)
    hostile = (
        "a <b>x</b> c\n\n<script>alert(1)</script>\n\n"
        '<img src="http://169.254.169.254/latest/meta-data/">\n\n'
        "![metadata](http://169.254.169.254/latest/meta-data/) "
        "![passwd](file:///etc/passwd) [js](javascript:alert(1))\n\n"
        '<iframe src="file:///etc/passwd"></iframe>\n\n<style>body{color:red}</style>'
    )
    await save(owner, key, "problem", hostile)

    pdf_response = await owner.get(f"{proposal_url(key)}/pdf")
    md_response = await owner.get(f"{proposal_url(key)}/markdown")

    assert pdf_response.status_code == 200
    text = "\n".join(pdf_text(pdf_response.content))
    assert "a x c" in text
    assert "metadata passwd js" in text
    assert "alert" not in text
    assert "color:red" not in text
    # The Markdown export keeps the text as written: it's the user's own source.
    assert hostile in md_response.text


async def test_filenames_come_from_the_ascii_key(api: AsUser, team: Team, written: str) -> None:
    response = await (await api(team.member)).get(f"{proposal_url(written.lower())}/markdown")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{written}-proposal.md"'
    )


# --- Limits -------------------------------------------------------------------------
async def test_the_eleventh_export_in_a_minute_is_refused(
    api: AsUser, team: Team, written: str, db_session: AsyncSession
) -> None:
    member = await api(team.member)
    for _ in range(10):
        assert (await member.get(f"{proposal_url(written)}/markdown")).status_code == 200

    refused = await member.get(f"{proposal_url(written)}/pdf")
    body = assert_problem(refused, 429, "too_many_attempts")
    assert 1 <= int(refused.headers["retry-after"]) <= 60
    assert "detail" in body
    # Per user: someone else still may.
    other = await make_user(db_session, "Nia Other", platform_admin=True)
    assert (await (await api(other)).get(f"{proposal_url(written)}/markdown")).status_code == 200


async def test_refused_and_missing_exports_do_not_count(api: AsUser, team: Team, key: str) -> None:
    member = await api(team.member)
    for _ in range(12):
        assert_problem(await member.get(f"{proposal_url(key)}/markdown"), 404, "not_found")
    await start(await api(team.owner), key)
    assert (await member.get(f"{proposal_url(key)}/markdown")).status_code == 200


async def test_a_render_over_the_time_limit_is_503_and_the_next_export_works(
    api: AsUser, team: Team, written: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow = Renderer(target=children.sleep_forever)
    monkeypatch.setattr(pdf, "_renderer", slow)
    monkeypatch.setattr(pdf, "RENDER_TIMEOUT", 1.0)
    member = await api(team.member)

    refused = await member.get(f"{proposal_url(written)}/pdf")

    assert_problem(refused, 503, "export_busy")
    assert refused.headers["retry-after"] == "10"
    assert slow.pid is None  # killed

    working = Renderer()
    monkeypatch.setattr(pdf, "_renderer", working)
    monkeypatch.setattr(pdf, "RENDER_TIMEOUT", 20.0)
    try:
        response = await member.get(f"{proposal_url(written)}/pdf")
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF-")
    finally:
        working.stop()


async def test_a_failed_render_is_a_500_without_details(
    api: AsUser, team: Team, written: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pdf, "_renderer", Renderer(target=children.crash))
    response = await (await api(team.member)).get(f"{proposal_url(written)}/pdf")
    body: dict[str, Any] = assert_problem(response, 500, "internal_error")
    assert "Customers" not in str(body)
