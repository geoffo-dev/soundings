"""Branded emails (contract-phase4 sections 3.8 and 3.10): staff emails use the global
branding, emails to a public submitter their project's: the app name as the wordmark,
the primary colour with a contrast-checked text colour, readable links, the chosen font
first in a system stack, and the footer line by line. No images, nothing loaded, and
no branding value can break out of the inline CSS."""

from __future__ import annotations

import html
import random
from email.message import EmailMessage
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.email import delivery
from app.email.delivery import Runtime
from app.email.model import Branding
from app.email.preview import sample_contents
from app.email.render import render
from app.models.base import utcnow
from app.models.enums import BrandFont, EmailType, HoldReason
from app.models.notification import OutboundEmail
from app.models.public import PublicSubmission
from app.public.emails import queue_confirmation
from app.services.branding import (
    AA_CONTRAST,
    EMAIL_FONT_STACKS,
    INK,
    WHITE,
    ResolvedBranding,
    contrast,
    readable_on,
    text_on,
)
from tests.branding.conftest import AsUser, Team, ok
from tests.notifications.conftest import SMTP, RecordingTransport, only
from tests.public.conftest import make_public_idea


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return dict(SMTP)


def parts(message: EmailMessage) -> tuple[str, str]:
    text = message.get_body(("plain",))
    markup = message.get_body(("html",))
    assert text is not None
    assert markup is not None
    return str(text.get_content()), str(markup.get_content())


def resolved(**values: Any) -> ResolvedBranding:
    base: dict[str, Any] = {
        "app_name": "Acme Ideas",
        "primary_color": "#0b6e4f",
        "accent_color": "#f59e0b",
        "font": BrandFont.IBM_PLEX_SANS,
        "email_footer": "Acme Ltd\n1 High Street, London",
        "logo_asset_id": None,
        "favicon_asset_id": None,
    }
    return ResolvedBranding(**{**base, **values})


# --- Derived colours ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("colour", "text"),
    [
        ("#1d5fa8", WHITE),
        ("#0b6e4f", WHITE),
        ("#ffd400", INK),
        ("#ffffff", INK),
        ("#000000", WHITE),
    ],
)
def test_text_on_a_brand_colour_reads(colour: str, text: str) -> None:
    assert text_on(colour) == text


def test_any_colour_gets_aa_text_and_links() -> None:
    rng = random.Random(4)  # noqa: S311 - test data, not secrets
    colours = [f"#{rng.randrange(0x1000000):06x}" for _ in range(2_000)]
    colours += ["#777777", "#767676", "#7f7f7f", "#808080", "#ff0000", "#00ff00", "#0000ff"]
    for colour in colours:
        assert contrast(text_on(colour), colour) >= AA_CONTRAST, colour
        assert contrast(readable_on(colour), WHITE) >= AA_CONTRAST, colour
    assert readable_on("#1d5fa8") == "#1d5fa8"  # already readable: unchanged


def test_the_email_branding_comes_from_the_profile() -> None:
    light = resolved(primary_color="#ffd400", font=BrandFont.SOURCE_SERIF_4).email()

    assert light.product_name == "Acme Ideas"
    assert light.accent == "#ffd400"
    assert light.accent_text == INK
    assert light.link is not None
    assert contrast(light.link, WHITE) >= AA_CONTRAST
    assert light.font_stack == EMAIL_FONT_STACKS[BrandFont.SOURCE_SERIF_4]
    assert light.footer_lines == ["Acme Ltd", "1 High Street, London"]


@pytest.mark.parametrize(
    "stack",
    ["Inter;background:url(https://evil.test/x)", 'Inter"', "Inter</style>", "a:b", "x(1)"],
)
def test_a_font_stack_can_not_break_out_of_the_css(stack: str) -> None:
    with pytest.raises(ValueError, match="font stack"):
        Branding(font_stack=stack)


def test_every_bundled_font_has_a_safe_stack() -> None:
    for font in BrandFont:
        Branding(font_stack=EMAIL_FONT_STACKS[font])
        assert EMAIL_FONT_STACKS[font].endswith(("sans-serif", "serif"))


# --- Rendering ---------------------------------------------------------------------------
def test_the_layout_shows_the_branding() -> None:
    content = sample_contents()["test"]

    rendered = render(content, resolved(app_name="Acme <Ideas>").email())

    markup = rendered.html
    assert "Acme &lt;Ideas&gt;" in markup  # the wordmark, escaped
    assert "background-color:#0b6e4f" in markup
    assert "color:#ffffff" in markup  # text on the primary colour
    assert "font-family:&#39;IBM Plex Sans&#39;,-apple-system" in markup
    assert "Acme Ltd<br>1 High Street, London" in markup
    for forbidden in ("<img", "url(", "@import", "<link", "src="):
        assert forbidden not in markup
    assert rendered.text.startswith("Acme <Ideas>\n============\n")
    assert rendered.text.rstrip().endswith("Acme Ltd\n1 High Street, London")


def test_without_a_footer_the_default_line_stays() -> None:
    content = sample_contents()["test"]

    rendered = render(content, resolved(email_footer=None).email())

    assert "Sent by Acme Ideas." in rendered.html
    assert rendered.text.rstrip().endswith("Sent by Acme Ideas.")


# --- Through the worker ------------------------------------------------------------------
async def test_staff_emails_use_the_global_branding_and_submitters_their_projects(
    api: AsUser,
    team: Team,
    db_session: AsyncSession,
    settings: Settings,
    runtime: Runtime,
    transport: RecordingTransport,
) -> None:
    platform = await api(team.platform)
    staff_branding = {
        "app_name": "Acme Ideas",
        "primary_color": "#0b6e4f",
        "email_footer": "Acme Ltd\n1 High Street",
    }
    ok(await platform.put("/admin/branding", staff_branding))
    project_branding = {
        "app_name": "Customer Lab",
        "primary_color": "#ffd400",
        "font": "atkinson_hyperlegible",
        "email_footer": "Customer Lab",
    }
    ok(await platform.put(f"/projects/{team.slug}/branding", project_branding))

    test_email = ok(await platform.post("/admin/email/test", {"to": "ops@example.com"}), 202)
    _, idea = await make_public_idea(
        db_session, settings, team, email="jo@example.org", held_for=HoldReason.MODERATION
    )
    submission = await db_session.scalar(
        select(PublicSubmission).where(PublicSubmission.idea_id == idea.id)
    )
    assert submission is not None
    assert await queue_confirmation(db_session, settings, submission, now=utcnow())
    await db_session.commit()
    confirmation = only(
        list(
            await db_session.scalars(
                select(OutboundEmail.id).where(OutboundEmail.type == EmailType.SUBMISSION_RECEIVED)
            )
        )
    )

    assert await delivery.send_email(runtime, test_email["id"]) == "sent"
    assert await delivery.send_email(runtime, confirmation) == "sent"

    staff_text, staff_html = parts(transport.messages[0])
    assert transport.messages[0]["Subject"] == "Acme Ideas test email"
    assert "background-color:#0b6e4f" in staff_html
    assert "Acme Ltd<br>1 High Street" in staff_html
    assert staff_text.startswith("Acme Ideas\n")
    assert "Customer Lab" not in staff_html

    submitter_text, submitter_html = parts(transport.messages[1])
    assert "Confirm your idea for Customer Innovation" in html.unescape(submitter_html)
    assert "background-color:#ffd400" in submitter_html
    assert f"color:{INK}" in submitter_html  # dark text on the light button
    assert "font-family:&#39;Atkinson Hyperlegible&#39;" in submitter_html
    assert submitter_text.startswith("Customer Lab\n")
    assert submitter_text.rstrip().endswith("Customer Lab")
    assert "Acme Ideas" not in submitter_html
