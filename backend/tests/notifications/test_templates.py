"""Email templates and messages (contract-phase3 section 3.11): every template renders
in HTML and text, HTML is mail-client safe and escapes everything, headers can't be
injected, and the preview command writes every email."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from markupsafe import escape

from app.cli import main
from app.email.message import build_message
from app.email.model import EmailContent, IdeaInfo, Links, clean_subject, subject_title
from app.email.preview import sample_contents
from app.email.render import TEMPLATE_DIR, TEMPLATES, render
from tests.conftest import make_settings

SAMPLES = sample_contents()


def test_every_template_has_html_text_and_a_sample() -> None:
    for name in TEMPLATES:
        assert (TEMPLATE_DIR / f"{name}.html").is_file()
        assert (TEMPLATE_DIR / f"{name}.txt").is_file()
    assert set(SAMPLES) == set(TEMPLATES)


@pytest.mark.parametrize("name", TEMPLATES)
def test_html_is_mail_client_safe(name: str) -> None:
    rendered = render(SAMPLES[name])
    html = rendered.html

    assert html.startswith("<!DOCTYPE html>")
    assert '<html lang="en"' in html
    assert '<meta name="color-scheme" content="light dark">' in html
    assert '<meta name="supported-color-schemes" content="light dark">' in html
    assert 'role="presentation"' in html
    assert "max-width:600px" in html
    # No images, scripts, stylesheets, fonts or tracking: nothing loads from anywhere.
    for forbidden in ("<img", "<script", "<link", "@import", "url(", "<iframe", "src="):
        assert forbidden not in html, forbidden
    # Every link is ours and absolute.
    for href in re.findall(r'href="([^"]+)"', html):
        assert href.startswith("http://localhost:8000"), href
    # The hidden preheader comes first in the body.
    assert html.index(str(escape(SAMPLES[name].preheader))) < html.index("<table")
    assert "{{" not in html
    assert "{%" not in html


@pytest.mark.parametrize("name", TEMPLATES)
def test_text_has_the_same_content_with_full_urls(name: str) -> None:
    content = SAMPLES[name]
    rendered = render(content)

    assert rendered.text.startswith("Soundings\n=========\n")
    if content.button is not None:
        assert f"{content.button.label}: {content.button.url}" in rendered.text
    if content.unsubscribe_url is not None:
        assert content.unsubscribe_url in rendered.text
    assert "&amp;" not in rendered.text
    assert "<" not in rendered.text.replace("<script>", "")  # no markup in the text part


def test_user_content_is_escaped_in_html() -> None:
    links = Links("http://localhost:8000")
    content = EmailContent(
        template="comment",
        subject='[CUST-1] Mallory commented on "<b>x</b>"',
        preheader="<img src=x onerror=alert(1)>",
        context={
            "actor": 'Mallory <a href="https://evil.test">',
            "idea": IdeaInfo(
                key="CUST-1",
                title="<script>alert(1)</script>",
                project="P & Q",
                status="New",
                url=links.idea("CUST-1"),
            ),
            "excerpt": "[click](javascript:alert(1)) <iframe>",
        },
    )

    html = render(content).html

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<iframe>" not in html
    assert 'href="https://evil.test"' not in html
    assert "P &amp; Q" in html
    assert "<img src=x" not in html


def test_subjects_have_no_line_breaks() -> None:
    assert clean_subject("Hello\r\nBcc: victim@example.com") == "Hello Bcc: victim@example.com"
    assert "\n" not in subject_title("A\nB" * 100)
    assert len(subject_title("x" * 300)) == 80


def test_the_message_has_one_recipient_and_safe_headers() -> None:
    settings = make_settings(
        environment="test",
        base_urls=["https://soundings.example.com"],
        smtp_host="smtp.example.com",
        smtp_from="soundings@example.com",
        smtp_from_name='Soundings "Team"',
        smtp_reply_to="help@example.com",
    )
    content = SAMPLES["comment"]
    rendered = render(content)
    message = build_message(
        rendered,
        content,
        settings=settings,
        to_address="olive@example.com",
        message_id="<abc@soundings.example.com>",
        now=datetime(2026, 10, 7, 8, 0, tzinfo=UTC),
    )

    assert message.get_all("To") == ["olive@example.com"]
    assert message["From"] == '"Soundings \\"Team\\"" <soundings@example.com>'
    assert message["Reply-To"] == "help@example.com"
    assert message["Message-ID"] == "<abc@soundings.example.com>"
    assert message["Date"] == "Wed, 07 Oct 2026 08:00:00 +0000"
    assert message.get("Cc") is None
    assert message.get("Bcc") is None


def test_the_preview_command_writes_every_email(tmp_path: Path) -> None:
    assert main(["email-preview", "--output", str(tmp_path)]) == 0

    names = {path.name for path in tmp_path.iterdir()}
    for name in TEMPLATES:
        assert f"{name}.html" in names
        assert f"{name}.txt" in names
    index = (tmp_path / "index.html").read_text()
    assert all(f'href="{name}.html"' in index for name in TEMPLATES)
