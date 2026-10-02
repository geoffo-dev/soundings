"""Phase 4 acceptance through the HTTP API (QA; docs/test-plans/phase-4.md, AC4-API-*).

SPEC section 13, Phase 4: *anonymous idea -> evaluated -> shortlisted -> exported
branded proposal* (contract-phase4 section 3.16).

Everything goes through the HTTP API, as the SPA and a visitor's browser would (dev
login and CSRF for staff; no session at all for the visitor), except the first platform
admin and a few read-only database checks of what must be gone. The visitor solves the
real ALTCHA proof of work with the Python ``altcha`` library, exactly as the widget
does. The worker's own code delivers the email: procrastinate runs the ``send_email``
jobs the requests deferred, through the real SMTP transport, to a real Mailpit
(the Phase 3 acceptance module's fixture: a container, or CI's service). The PDF is
rendered by the real WeasyPrint child process and read back with pypdf (text,
metadata, the embedded font's own name table, the cover's colours and logo).

* AC4-API-1: the whole story, step by step as in contract 3.16:
  1. branding (global name, colour, font, PNG logo, footer; the project's colour);
  2. the public form, a real ALTCHA, the receipt, the fixed-text confirmation email and
     the confirmation;
  3. held: in no list for anyone, 404 for members, read-only for the admin; approved;
  4. the owner edits the summary, three evaluators score it blind, Shortlisted: the
     submitter's status emails and tracking page show only what they sent;
  5. the proposal (Shortlisted -> Proposal, another email), sections, a margin thread
     on Problem resolved by the owner;
  6. Markdown and branded PDF exports, with the aggregate line; none for a pending
     evaluator;
  7. erasure: the link stops working, the idea and its proposal stay, no submitter
     email or personal data remains, the audit has no personal data.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import logging
import re
import uuid
import warnings
from collections.abc import Iterator
from typing import Any

import altcha
import pytest
from fastapi import FastAPI
from PIL import Image, ImageFile
from procrastinate import App
from pypdf import PdfReader
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.email.delivery import Runtime
from app.models.notification import OutboundEmail
from app.models.public import PublicSubmission
from app.proposals import pdf
from app.proposals.pdf import Renderer
from tests.acceptance.test_phase3_acceptance import (  # noqa: F401 - fixtures
    API,
    BASE,
    ZONE,
    Client,
    MailpitInbox,
    MailpitServer,
    Story,
    clock,
    inbox,
    jobs,
    mailpit,
    ok,
    run_worker_once,
    runtime,
    story,
    visible_text,
)
from tests.factories import make_user

with warnings.catch_warnings():
    # WeasyPrint warns at import where HarfBuzz-Subset is missing (it uses fontTools).
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        from app.proposals import pdf_child  # noqa: F401 - the renderer must load
    except (ImportError, OSError) as missing:  # pragma: no cover - a host without Pango
        pytest.skip(f"WeasyPrint can't load: {missing}", allow_module_level=True)
# Importing WeasyPrint turns on Pillow's LOAD_TRUNCATED_IMAGES for the whole process
# (tests/proposals/test_exports.py): keep the rest of the session strict.
ImageFile.LOAD_TRUNCATED_IMAGES = False

PUBLIC = f"{API}/public"
APP_NAME = "Acme Ideas"
GLOBAL_PRIMARY = "#7c3aed"
PROJECT_PRIMARY = "#0b6e4f"
FOOTER = "Acme Ideas Ltd\n1 Example Street, London EC1A 1AA"
PROJECT_NAME = "Customer Innovation"
# What the visitor sends: none of it may reach the confirmation email.
TITLE = "Recycle packaging at the till"
SUMMARY = "Let customers hand back packaging when they pay, so it gets recycled."
DESCRIPTION = "Bins by every till, emptied by the recycling partner on Fridays."
SUBMITTER = "Jo Public"
EDITED_SUMMARY = "Packaging take-back at the tills (internal: pilot in Leeds, ask Finance)."
SECTIONS = {
    "summary": "Customers hand back packaging at the till; we recycle it.",
    "problem": "Shoppers throw away **12 tonnes** of our packaging a month.",
    "solution": "A take-back bin at every till, emptied weekly.",
    "market": "Every store customer; 60% say they would use it.",
    "cost": "£40k for bins, £8k a year for collection.",
    "benefits": "Fewer complaints, a greener brand, a lower packaging levy.",
    "risks": "Contamination of the bins; staff time at busy tills.",
    "next_steps": "Approve a three-store pilot for one quarter.",
}
SECTION_TITLES = [
    "Summary",
    "Problem",
    "Solution",
    "Market & users",
    "Cost & effort",
    "Benefits / revenue",
    "Risks",
    "Next steps / the ask",
]
# Bob, Carol and Dan submit; Eve stays pending (blind: her exports carry no score).
SCORES = {"Bob": 4, "Carol": 5, "Dan": 3}
SCORE_WORDS = re.compile(r"\b(score|scores|aggregate|recommend\w*|evaluations?)\b", re.I)
SCORE_NUMBER = re.compile(r"\b[1-5]\.\d\b")


@pytest.fixture
def settings_overrides(mailpit: MailpitServer) -> dict[str, Any]:  # noqa: F811 - the fixture
    return {
        "smtp_host": mailpit.smtp_host,
        "smtp_port": mailpit.smtp_port,
        "smtp_security": "none",
        "smtp_from": "soundings@example.com",
        "smtp_from_name": "Soundings",
        "smtp_timeout": 3,
        "timezone": ZONE,
        "base_urls": [BASE],
        # The cheapest proof of work the settings allow (the widget's default is 5,000).
        "altcha_cost": 1_000,
    }


@pytest.fixture
def renderer(monkeypatch: pytest.MonkeyPatch) -> Iterator[Renderer]:
    """A PDF child process for this test only (stopped afterwards)."""
    child = Renderer()
    monkeypatch.setattr(pdf, "_renderer", child)
    yield child
    child.stop()


# --- Helpers ----------------------------------------------------------------------------
def png_logo() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (240, 64), (124, 58, 237, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def solve(challenge: dict[str, Any]) -> str:
    """The widget's payload for ``challenge``: solve it, base64 the JSON."""
    parsed = altcha.Challenge.from_dict(challenge)
    solution = altcha.solve_challenge(parsed)
    assert solution is not None
    return base64.b64encode(
        json.dumps(altcha.Payload(parsed, solution).to_dict()).encode()
    ).decode()


def links(message: dict[str, Any]) -> list[str]:
    return [href.replace("&amp;", "&") for href in re.findall(r'href="([^"]+)"', message["HTML"])]


def fragment(url: str, path: str) -> str:
    """The token after ``#`` of a ``<BASE><path>#<token>`` link."""
    assert url.startswith(f"{BASE}{path}#"), url
    return url.split("#", 1)[1]


def pdf_colours(reader: PdfReader, page: int) -> list[tuple[float, float, float]]:
    """Every RGB fill and stroke colour set on ``page`` (``r g b rg`` / ``RG``)."""
    data = reader.pages[page].get_contents()
    assert data is not None
    stream = data.get_data().decode("latin-1")
    number = r"(-?\d*\.?\d+)"
    return [
        (float(r), float(g), float(b))
        for r, g, b in re.findall(rf"{number}\s+{number}\s+{number}\s+(?:rg|RG)\b", stream)
    ]


def resources(page: Any) -> dict[str, Any]:
    found: dict[str, Any] = page["/Resources"].get_object()
    return found


def has_colour(colours: list[tuple[float, float, float]], hex_colour: str) -> bool:
    wanted = tuple(int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return any(all(abs(a - b) < 0.004 for a, b in zip(c, wanted, strict=True)) for c in colours)


def embedded_font_families(reader: PdfReader) -> set[str]:
    """The family names in the embedded font programs' own name tables (the PDF's
    ``/BaseFont`` is the stylesheet's alias, so this is where the real font shows)."""
    from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

    families: set[str] = set()
    for page in reader.pages:
        fonts = resources(page).get("/Font", {})
        for ref in fonts.values():
            font = ref.get_object()
            descendants = font.get("/DescendantFonts")
            if descendants:
                font = descendants[0].get_object()
            descriptor = font.get("/FontDescriptor")
            if descriptor is None:
                continue
            descriptor = descriptor.get_object()
            for key in ("/FontFile2", "/FontFile3", "/FontFile"):
                if key in descriptor:
                    program = descriptor[key].get_object().get_data()
                    with contextlib.suppress(Exception):
                        names = TTFont(io.BytesIO(program))["name"]
                        family = names.getDebugName(16) or names.getDebugName(1)
                        if family:
                            families.add(family)
    return families


def assert_no_score_data(label: str, *parts: str) -> None:
    for part in parts:
        assert not SCORE_WORDS.search(part), (label, SCORE_WORDS.search(part))
        assert not SCORE_NUMBER.search(part), (label, SCORE_NUMBER.search(part))


async def keys_in_lists(client: Client, slug: str, words: str) -> set[str]:
    """Every idea key the client finds anywhere a list shows ideas."""
    found: set[str] = set()
    page = await client.get(f"/projects/{slug}/ideas", limit=100)
    found |= {item["key"] for item in page["items"]}
    board = await client.get(f"/projects/{slug}/board")
    found |= {item["key"] for column in board["columns"] for item in column["items"]}
    search = await client.get("/search", q=words)
    found |= {item["key"] for item in search["ideas"]}
    work = await client.get("/me/work")
    found |= set(re.findall(r'"key":\s*"([A-Z0-9]+-\d+)"', json.dumps(work)))
    owned = await client.get("/me/owned-ideas")
    found |= {item["key"] for item in owned["items"]}
    return found


async def outbox_rows_for(db: AsyncSession, idea_id: str) -> list[OutboundEmail]:
    rows = await db.scalars(
        select(OutboundEmail)
        .where(OutboundEmail.idea_id == uuid.UUID(idea_id))
        .execution_options(populate_existing=True)
    )
    return list(rows)


# --- AC4-API-1 --------------------------------------------------------------------------
@pytest.mark.usefixtures("renderer")
async def test_an_anonymous_idea_becomes_an_exported_branded_proposal(
    story: Story,  # noqa: F811 - the fixture
    app: FastAPI,
    db_session: AsyncSession,
    jobs: App,  # noqa: F811 - the fixture
    runtime: Runtime,  # noqa: F811 - the fixture
    inbox: MailpitInbox,  # noqa: F811 - the fixture
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="soundings")
    caplog.set_level(logging.INFO)
    run = uuid.uuid4().hex[:6]
    root = await make_user(db_session, "Pat Platform", platform_admin=True)
    pat = await story.sign_in(str(root.id))
    people: dict[str, Client] = {}
    for name in (
        "Alice Anders",
        "Olive Owner",
        "Bob Brown",
        "Carol Chen",
        "Dan Dale",
        "Eve Eld",
        "Mia Member",
    ):
        first = name.split()[0].lower()
        created = await pat.send(
            "POST",
            "/admin/users",
            {"email": f"{first}.{run}@example.com", "display_name": name},
            201,
        )
        people[first] = await story.sign_in(created["id"])
    alice, olive, mia, eve = people["alice"], people["olive"], people["mia"], people["eve"]

    # --- 1. Branding: the platform admin's global profile, the project's colour ----------
    upload = await pat.http.post(
        f"{API}/admin/branding/assets",
        params={"kind": "logo"},
        content=png_logo(),
        headers={"Content-Type": "image/png"},
    )
    logo = ok(upload, 201)
    assert (logo["kind"], logo["content_type"], logo["width"], logo["height"]) == (
        "logo",
        "image/png",
        240,
        64,
    )
    branding = await pat.send(
        "PUT",
        "/admin/branding",
        {
            "app_name": APP_NAME,
            "primary_color": GLOBAL_PRIMARY,
            "accent_color": None,
            "font": "ibm_plex_sans",
            "email_footer": FOOTER,
            "logo_asset_id": logo["id"],
            "favicon_asset_id": None,
        },
    )
    assert branding["effective"]["app_name"] == APP_NAME
    assert branding["effective"]["font"] == "ibm_plex_sans"
    anonymous = story.browser()
    shell = ok(await anonymous.get(f"{API}/branding"))
    assert (shell["app_name"], shell["primary_color"], shell["font"]) == (
        APP_NAME,
        GLOBAL_PRIMARY,
        "ibm_plex_sans",
    )
    assert shell["logo_url"] == logo["url"]
    served = await anonymous.get(logo["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"

    project = await pat.send(
        "POST",
        "/projects",
        {
            "name": PROJECT_NAME,
            "slug": f"cust-{run}",
            "key": "CUST",
            "admin_user_id": alice.user["id"],
        },
        201,
    )
    slug = project["slug"]
    for first in ("olive", "bob", "carol", "dan", "eve", "mia"):
        await alice.send(
            "POST",
            f"/projects/{slug}/members",
            {"user_id": people[first].user["id"], "role": "member"},
            201,
        )
    form = await alice.send(
        "PATCH",
        f"/projects/{slug}/public-form",
        {
            "enabled": True,
            "moderation_required": True,
            "intro_md": "Tell us how to make shopping with us better.",
        },
    )
    assert (form["available"], form["enabled"], form["moderation_required"]) == (True, True, True)
    assert form["form_url"] == f"{BASE}/{slug}/submit"
    project_branding = await alice.send(
        "PUT",
        f"/projects/{slug}/branding",
        {
            "app_name": None,
            "primary_color": PROJECT_PRIMARY,
            "accent_color": None,
            "font": None,
            "email_footer": None,
            "logo_asset_id": None,
            "favicon_asset_id": None,
        },
    )
    assert project_branding["effective"]["primary_color"] == PROJECT_PRIMARY
    assert project_branding["effective"]["app_name"] == APP_NAME  # inherited
    # The signed-in app keeps the global branding (contract 3.10).
    assert ok(await anonymous.get(f"{API}/branding"))["primary_color"] == GLOBAL_PRIMARY

    # --- 2. The public form, signed out ------------------------------------------------
    visitor = story.browser()
    public = ok(await visitor.get(f"{PUBLIC}/projects/{slug}"))
    assert public == {
        "slug": slug,
        "name": PROJECT_NAME,
        "intro_md": "Tell us how to make shopping with us better.",
        "asks_for_email": True,
        "email_required": False,
        "moderated": True,
        "branding": {
            "app_name": APP_NAME,
            "primary_color": PROJECT_PRIMARY,
            "accent_color": "#1d5fa8",  # nobody set one: the built-in default
            "font": "ibm_plex_sans",
            "logo_url": logo["url"],
            "favicon_url": None,
        },
    }, public
    challenge = ok(await visitor.get(f"{PUBLIC}/projects/{slug}/altcha"))
    assert challenge["parameters"]["data"] == {"project": slug}
    payload = solve(challenge)
    response = await visitor.post(
        f"{PUBLIC}/projects/{slug}/submissions",
        json={
            "title": TITLE,
            "summary": SUMMARY,
            "description_md": DESCRIPTION,
            "name": SUBMITTER,
            "email": f"jo.{run}@example.com",
            "wants_updates": True,
            "altcha": payload,
            "website": "",
        },
    )
    receipt = ok(response, 201)
    token = receipt["tracking_token"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    assert receipt == {
        "tracking_token": token,
        "tracking_url": f"{BASE}/track#{token}",
        "held_for": "moderation",
        "email_sent": True,
    }
    # The same solution again: refused (replay), nothing more created.
    replay = await visitor.post(
        f"{PUBLIC}/projects/{slug}/submissions",
        json={"title": "Again", "summary": "Again.", "altcha": payload},
    )
    assert replay.status_code == 422
    assert replay.json()["code"] == "challenge_failed"
    submissions = await db_session.scalar(
        select(func.count())
        .select_from(PublicSubmission)
        .where(PublicSubmission.project_id == uuid.UUID(project["id"]))
    )
    assert submissions == 1

    # The confirmation email: fixed text, nothing the visitor typed, the confirmation
    # link and no tracking link (it would show a stranger what the visitor typed).
    await run_worker_once(jobs, runtime)
    jo = f"jo.{run}@example.com"
    [summary] = await inbox.wait_for(jo)
    confirmation = await inbox.message(summary["ID"])
    assert confirmation["Subject"] == f"Confirm your idea for {PROJECT_NAME}"
    html_text, plain = visible_text(confirmation["HTML"]), confirmation["Text"]
    for typed in (TITLE, SUMMARY, DESCRIPTION, SUBMITTER, "Recycle", "packaging"):
        assert typed not in confirmation["Subject"]
        assert typed not in html_text, typed
        assert typed not in plain, typed
    assert f"Someone sent an idea to {PROJECT_NAME}" in " ".join(html_text.split())
    assert APP_NAME in html_text  # the wordmark: the project's effective app name
    assert "Acme Ideas Ltd" in html_text  # the footer, inherited from the global profile
    assert PROJECT_PRIMARY in confirmation["HTML"].lower()  # the button in the project's colour
    assert "<img" not in confirmation["HTML"].lower()  # no images in email
    hrefs = links(confirmation)
    [verify_link] = [href for href in hrefs if href.startswith(f"{BASE}/verify#")]
    assert verify_link in plain
    assert not [href for href in hrefs if "/track" in href]
    assert token not in confirmation["HTML"]
    assert token not in plain
    headers = await inbox.headers(summary["ID"])
    assert "List-Unsubscribe" not in headers  # the tracking page is the opt-out
    assert headers["Auto-Submitted"] == ["auto-generated"]

    # Opening the link changes nothing (the page posts on the Confirm click only) ...
    tracked = ok(await visitor.post(f"{PUBLIC}/track", json={"token": token}))
    assert (tracked["email_verified"], tracked["held_for"]) == (False, "moderation")
    # ... the click confirms.
    verified = ok(
        await visitor.post(
            f"{PUBLIC}/verify-email", json={"token": fragment(verify_link, "/verify")}
        )
    )
    assert verified["project"] == {"slug": slug, "name": PROJECT_NAME}
    assert (verified["title"], verified["held_for"]) == (TITLE, "moderation")
    assert verified["branding"]["primary_color"] == PROJECT_PRIMARY
    tracked = ok(await visitor.post(f"{PUBLIC}/track", json={"token": token}))
    assert tracked["email_verified"] is True
    assert tracked["email_hint"] == "j•••@example.com"

    # --- 3. Held: nowhere for anyone; the admin's queue; approved ----------------------
    [queued] = (await alice.get(f"/projects/{slug}/moderation"))["items"]
    key = queued["key"]
    assert (await alice.get(f"/projects/{slug}/moderation"))["total"] == 1
    assert (queued["title"], queued["summary"]) == (TITLE, SUMMARY)
    assert queued["submission"]["name"] == SUBMITTER
    for who, client in (("platform", pat), ("project admin", alice), ("member", olive)):
        assert key not in await keys_in_lists(client, slug, "packaging till"), who
        assert (await client.get(f"/projects/{slug}"))["idea_count"] == 0, who
        notes = await client.get("/me/notifications", limit=100)
        assert key not in json.dumps(notes), who
    assert (await olive.http.get(f"{API}/ideas/{key}")).status_code == 404
    held = await alice.get(f"/ideas/{key}")
    assert (held["held_for"], held["via_public_form"], held["submitted_by"]) == (
        "moderation",
        True,
        None,
    )
    assert {flag for flag, value in held["permissions"].items() if value} == {"can_delete"}
    member_queue = await olive.http.get(f"{API}/projects/{slug}/moderation")
    assert member_queue.status_code == 403
    blocked = await alice.http.post(f"{API}/ideas/{key}/status", json={"status": "evaluating"})
    assert (blocked.status_code, blocked.json()["code"]) == (409, "awaiting_moderation")

    approved = await alice.send("POST", f"/ideas/{key}/submission/approve")
    assert approved["held_for"] is None
    assert (await alice.get(f"/projects/{slug}/moderation"))["total"] == 0
    new_column = {
        column["status"]: [item["key"] for item in column["items"]]
        for column in (await olive.get(f"/projects/{slug}/board"))["columns"]
    }["new"]
    assert new_column == [key]
    detail = await olive.get(f"/ideas/{key}")
    assert (detail["held_for"], detail["via_public_form"]) == (None, True)
    submission = await olive.get(f"/ideas/{key}/submission")
    assert submission["name"] == SUBMITTER
    assert submission["contact"] is None  # the address is for admins only

    # --- 4. Owner, blind evaluation, Shortlisted -------------------------------------
    await alice.send("PUT", f"/ideas/{key}/owner", {"user_id": olive.user["id"]})
    await olive.send("PATCH", f"/ideas/{key}", {"summary": EDITED_SUMMARY})
    await olive.send("POST", f"/ideas/{key}/status", {"status": "evaluating"})
    evaluators = ["bob", "carol", "dan", "eve"]
    await olive.send(
        "POST",
        f"/ideas/{key}/evaluators",
        {"user_ids": [people[first].user["id"] for first in evaluators]},
    )
    rubric = (await olive.get(f"/projects/{slug}"))["rubric"]
    for name, score in SCORES.items():
        client = people[name.lower()]
        mine = await client.get(f"/ideas/{key}")
        assert mine["score_hidden"] is True  # blind until their own submission
        saved = await client.send(
            "PUT",
            f"/ideas/{key}/evaluations/me",
            {
                "scores": [{"criterion_id": c["id"], "score": score} for c in rubric],
                "recommendation": "go",
                "comment": f"{name}: worth a pilot.",
                "submit": True,
            },
        )
        assert saved["state"] == "submitted"
    assert (await eve.get(f"/ideas/{key}"))["score_hidden"] is True
    aggregate = (await olive.get(f"/ideas/{key}"))["aggregate"]
    assert aggregate["count"] == 3
    await olive.send("POST", f"/ideas/{key}/status", {"status": "shortlisted"})

    await run_worker_once(jobs, runtime)
    mails = await inbox.wait_for(jo, count=3)
    subjects = sorted(message["Subject"] for message in mails)
    assert subjects == sorted(
        [
            f"Confirm your idea for {PROJECT_NAME}",
            f'Your idea "{TITLE}" is now Evaluating',
            f'Your idea "{TITLE}" is now Shortlisted',
        ]
    ), subjects
    [shortlisted_summary] = [m for m in mails if m["Subject"].endswith("now Shortlisted")]
    shortlisted = await inbox.message(shortlisted_summary["ID"])
    body = visible_text(shortlisted["HTML"]) + shortlisted["Text"]
    assert TITLE in body
    for internal in (EDITED_SUMMARY, "Olive", "Bob", "Carol", "worth a pilot", key):
        assert internal not in body, internal
    assert_no_score_data("status email", shortlisted["Subject"], visible_text(shortlisted["HTML"]))
    assert f"{BASE}/track#{token}" in links(shortlisted)

    tracked = ok(await visitor.post(f"{PUBLIC}/track", json={"token": token}))
    assert (tracked["title"], tracked["summary"]) == (TITLE, SUMMARY)  # as sent, not edited
    assert (tracked["status"], tracked["status_label"], tracked["held_for"]) == (
        "shortlisted",
        "Shortlisted",
        None,
    )
    assert [change["status_label"] for change in tracked["history"]] == [
        "Evaluating",
        "Shortlisted",
    ]
    assert set(tracked) == {
        "project",
        "title",
        "summary",
        "submitted_at",
        "held_for",
        "status",
        "resolution",
        "status_label",
        "history",
        "email_hint",
        "email_verified",
        "wants_updates",
        "can_resend_verification",
        "branding",
    }
    exposed = json.dumps(tracked)
    for internal in (key, EDITED_SUMMARY, "Olive", "Bob Brown", "worth a pilot", olive.user["id"]):
        assert internal not in exposed, internal
    assert_no_score_data("tracking", exposed)

    # --- 5. The proposal ---------------------------------------------------------------
    view = await olive.send("POST", f"/ideas/{key}/proposal", status=201)
    assert [s["key"] for s in view["proposal"]["sections"]] == list(SECTIONS)
    assert [s["title"] for s in view["proposal"]["sections"]] == SECTION_TITLES
    assert (await olive.get(f"/ideas/{key}"))["status"] == "proposal"
    for section in view["proposal"]["sections"]:
        saved = await olive.send(
            "PUT",
            f"/ideas/{key}/proposal/sections/{section['key']}",
            {"body_md": SECTIONS[section["key"]], "base_version": section["version"]},
        )
        assert saved["body_md"] == SECTIONS[section["key"]]
    thread = await mia.send(
        "POST",
        f"/ideas/{key}/proposal/threads",
        {"section_key": "problem", "body_md": "Where does the 12 tonnes figure come from?"},
        201,
    )
    resolved = await olive.send("PUT", f"/ideas/{key}/proposal/threads/{thread['id']}/resolved")
    assert resolved["resolved_by"]["id"] == olive.user["id"]
    [listed] = (await mia.get(f"/ideas/{key}/proposal/threads"))["items"]
    assert (listed["section_key"], bool(listed["resolved_at"])) == ("problem", True)

    await run_worker_once(jobs, runtime)
    mails = await inbox.wait_for(jo, count=4)
    assert f'Your idea "{TITLE}" is now Proposal' in [m["Subject"] for m in mails]

    # --- 6. Exports ---------------------------------------------------------------------
    markdown = await olive.http.get(f"{API}/ideas/{key}/proposal/markdown")
    assert markdown.status_code == 200, markdown.text
    assert markdown.headers["content-disposition"] == f'attachment; filename="{key}-proposal.md"'
    md = markdown.text
    assert md.startswith(f'---\ntitle: "{TITLE}"\n')
    assert f"- Project: {PROJECT_NAME}\n" in md
    assert "- Owner: Olive Owner\n" in md
    assert re.search(r"- Aggregate score \d\.\d from 3 evaluations\n", md), md
    for title, (section_key, body_md) in zip(SECTION_TITLES, SECTIONS.items(), strict=True):
        assert f"## {title}\n\n{body_md}\n" in md + "\n", section_key
    assert "Where does the 12 tonnes" not in md  # comments are never exported

    exported = await olive.http.get(f"{API}/ideas/{key}/proposal/pdf")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"] == "application/pdf"
    assert exported.headers["content-disposition"] == f'attachment; filename="{key}-proposal.pdf"'
    reader = PdfReader(io.BytesIO(exported.content))
    assert reader.metadata is not None
    assert (reader.metadata.title, reader.metadata.author, reader.metadata.creator) == (
        TITLE,
        "Olive Owner",
        APP_NAME,
    )
    pages = [page.extract_text() for page in reader.pages]
    document = "\n".join(pages)
    assert len(pages) >= 2
    assert TITLE in pages[0]
    assert PROJECT_NAME in pages[0]
    assert re.search(r"Aggregate score \d\.\d from 3 evaluations", pages[0]), pages[0]
    for title in SECTION_TITLES:
        assert title in document, title
    assert "Shoppers throw away 12 tonnes of our packaging a month." in document
    assert "Approve a three-store pilot for one quarter." in document
    for number, page_text in enumerate(pages[1:], start=2):
        assert f"Page {number} of {len(pages)}" in page_text, page_text
        assert APP_NAME in page_text  # the running header
        assert key in page_text
    # The project's effective branding: its colour on the cover, the global logo and font.
    assert has_colour(pdf_colours(reader, 0), PROJECT_PRIMARY), pdf_colours(reader, 0)
    assert not has_colour(pdf_colours(reader, 0), GLOBAL_PRIMARY)
    cover = resources(reader.pages[0])
    images = [x.get_object() for x in cover.get("/XObject", {}).values()]
    assert any(image.get("/Subtype") == "/Image" for image in images), "the logo on the cover"
    assert "IBM Plex Sans" in embedded_font_families(reader)

    # A pending evaluator's exports carry no score data.
    pending_md = (await eve.http.get(f"{API}/ideas/{key}/proposal/markdown")).text
    pending_pdf = await eve.http.get(f"{API}/ideas/{key}/proposal/pdf")
    assert pending_pdf.status_code == 200
    pending_text = "\n".join(
        page.extract_text() for page in PdfReader(io.BytesIO(pending_pdf.content)).pages
    )
    for label, text_ in (("markdown", pending_md), ("pdf", pending_text)):
        assert "score" not in text_.lower(), label
        assert "from 3 evaluations" not in text_, label

    # --- 7. Erasure ---------------------------------------------------------------------
    assert len(await outbox_rows_for(db_session, detail["id"])) == 4
    erased = await alice.send("POST", f"/ideas/{key}/submission/erase")
    assert erased["erased_at"]
    assert erased["name"] is None
    assert erased["contact"] == {"email": None, "email_verified": False, "wants_updates": False}
    assert erased["permissions"]["can_erase"] is False
    again = await alice.send("POST", f"/ideas/{key}/submission/erase")  # idempotent
    assert again["erased_at"] == erased["erased_at"]
    gone = await visitor.post(f"{PUBLIC}/track", json={"token": token})
    assert (gone.status_code, gone.json()["code"]) == (404, "not_found")
    unknown = await visitor.post(f"{PUBLIC}/track", json={"token": "A" * 43})
    # Erased and unknown read the same (apart from the request id).
    assert {**unknown.json(), "request_id": None} == {**gone.json(), "request_id": None}
    # The idea and its proposal stay with the team.
    kept = await olive.get(f"/ideas/{key}")
    assert (kept["title"], kept["status"], kept["via_public_form"]) == (TITLE, "proposal", True)
    assert (await olive.get(f"/ideas/{key}/proposal"))["proposal"]["sections"][1]["body_md"] == (
        SECTIONS["problem"]
    )
    # No personal data left: the row, its emails, the audit entry.
    row = await db_session.scalar(
        select(PublicSubmission)
        .where(PublicSubmission.idea_id == uuid.UUID(detail["id"]))
        .execution_options(populate_existing=True)
    )
    assert row is not None
    assert (row.name, row.email, row.email_verified_at, row.wants_updates) == (
        None,
        None,
        None,
        False,
    )
    assert (row.tracking_token_hash, row.tracking_token_sealed) == (None, None)
    assert (row.submitted_title, row.submitted_summary) == (None, None)
    assert row.erased_by_id == uuid.UUID(alice.user["id"])
    assert await outbox_rows_for(db_session, detail["id"]) == []
    leftovers = await db_session.scalar(
        text("SELECT count(*) FROM outbound_email WHERE lower(to_address) = :jo"), {"jo": jo}
    )
    assert leftovers == 0
    audit = await pat.get("/admin/audit", action="submission.erase")
    [entry] = [item for item in audit["items"] if item["target_id"] == detail["id"]]
    serialised = json.dumps(entry)
    for personal in (SUBMITTER, jo, "Jo", token):
        assert personal not in serialised, personal
    assert entry["actor_id"] == alice.user["id"]
    approvals = await pat.get("/admin/audit", action="submission.approve")
    assert any(item["target_id"] == detail["id"] for item in approvals["items"])
    branding_entries = await pat.get("/admin/audit", action="branding.update")
    assert APP_NAME not in json.dumps(branding_entries)  # field names only, never values

    # Nothing personal or secret reached the logs during the whole story (contract 3.9):
    # no token, address, name or idea text in any record, its arguments or extras.
    logged = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert "request" in logged  # the capture worked
    for secret in (token, fragment(verify_link, "/verify"), jo, SUBMITTER, TITLE, SUMMARY):
        assert secret not in logged, secret
