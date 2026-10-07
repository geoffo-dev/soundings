"""Email templates and messages (contract-phase3 section 3.11): every template renders
in HTML and text, HTML is mail-client safe and escapes everything, headers can't be
injected, and the preview command writes every email."""

from __future__ import annotations

import email.policy
import re
from datetime import UTC, datetime
from email.parser import BytesParser
from pathlib import Path

import pytest
from markupsafe import escape

from app.cli import main
from app.email.message import build_message, to_bytes
from app.email.model import Branding, EmailContent, IdeaInfo, Links, clean_subject, subject_title
from app.email.outbox import message_id_domain, new_message_id
from app.email.preview import sample_contents
from app.email.render import TEMPLATE_DIR, TEMPLATES, RenderedEmail, render
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
    # Accessibility audit P7: the message is one landmark named by its subject.
    label = f'aria-label="{escape(rendered.subject)}"'
    assert f'<div role="article" aria-roledescription="email" {label} lang="en">' in html
    assert html.index('role="article"') < html.index("<table")
    assert html.rstrip().endswith("</div>\n</body>\n</html>")
    assert "{{" not in html
    assert "{%" not in html


@pytest.mark.parametrize("name", TEMPLATES)
def test_text_has_the_same_content_with_full_urls(name: str) -> None:
    content = SAMPLES[name]
    rendered = render(content)

    assert rendered.text.startswith("Soundings\n=========\n")
    if content.button is not None:
        # The link stands on its own line, after a blank one.
        assert f"\n\n{content.button.label}: {content.button.url}\n" in rendered.text
    # The footer follows a blank line and a signature separator (RFC 3676: "-- ").
    body, footer = rendered.text.split("\n\n-- \n")
    assert body.strip()
    assert "-- " not in footer
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


FORGED = "Plan\u2028Evaluate now: http://evil.example/login\u2029\u0085\u000bEnd"


def _forged_content() -> EmailContent:
    links = Links("http://localhost:8000")
    return EmailContent(
        template="evaluator_invited",
        subject=f'[CUST-1] Please evaluate "{subject_title(FORGED)}"',
        preheader="Mallory\u2028asked you",
        context={
            "actor": "Mallory\u202eredlof\u202c",
            "idea": IdeaInfo(
                key="CUST-1",
                title=FORGED,
                project="P\u2066roject\u2069",
                status="New",
                url=links.idea("CUST-1"),
            ),
            "due": None,
        },
    )


def test_values_cannot_start_a_line_in_the_text_part() -> None:
    """Review L2: U+2028/U+2029 (and NEL, VT) in a title forged a line of its own."""
    rendered = render(_forged_content())

    lines = rendered.text.splitlines()
    assert not any(line.startswith("Evaluate now") for line in lines)
    assert "Plan Evaluate now: http://evil.example/login End" in rendered.text
    for part in (rendered.text, rendered.html, rendered.subject):
        for char in ("\u2028", "\u2029", "\u0085", "\u000b"):
            assert char not in part


def test_bidi_controls_are_removed_from_values() -> None:
    rendered = render(_forged_content())

    for part in (rendered.text, rendered.html):
        for char in ("\u202e", "\u202c", "\u2066", "\u2069"):
            assert char not in part
        assert "Mallory redlof" in part or "Malloryredlof" in part
    assert "\u202e" not in clean_subject("x\u202ey")


@pytest.mark.parametrize(
    "title",
    [
        '"=?utf-8?q?x?="',
        "=?utf-8?b?QURNSU4gQUNUSU9OIFJFUVVJUkVE?=",
        "Café =?iso-8859-1?q?=E9?= " + "long " * 30,
    ],
)
def test_encoded_words_in_a_subject_are_shown_as_typed(title: str) -> None:
    """Review L3: a title holding an RFC 2047 encoded-word was sent raw, so mail clients
    decoded it (showing text the app would reject)."""
    settings = make_settings(
        environment="test", smtp_host="smtp.example.com", smtp_from="soundings@example.com"
    )
    content = SAMPLES["comment"]
    rendered = render(content)
    subject = clean_subject(f'[CUST-1] Please evaluate "{title}"')
    rendered = RenderedEmail(subject=subject, html=rendered.html, text=rendered.text)
    message = build_message(
        rendered,
        content,
        settings=settings,
        to_address="olive@example.com",
        message_id="<abc@soundings.example.com>",
        now=datetime(2026, 10, 7, 8, 0, tzinfo=UTC),
    )

    wire = to_bytes(message)
    parsed = BytesParser(policy=email.policy.default).parsebytes(wire)
    assert str(parsed["Subject"]) == subject
    lines = wire.split(b"\r\n\r\n")[0].split(b"\r\n")
    start = next(n for n, line in enumerate(lines) if line.startswith(b"Subject: "))
    end = next(n for n in range(start + 1, len(lines)) if not lines[n].startswith(b" "))
    folded = lines[start:end]
    assert all(b"=?utf-8?q?x?=" not in line for line in folded)
    assert all(len(line) <= 78 for line in folded)


def test_plain_subjects_are_sent_as_typed() -> None:
    settings = make_settings(
        environment="test", smtp_host="smtp.example.com", smtp_from="soundings@example.com"
    )
    content = SAMPLES["comment"]
    rendered = render(content)
    subject = '[CUST-1] Bob commented on "Refunds = ?"'
    message = build_message(
        RenderedEmail(subject=subject, html=rendered.html, text=rendered.text),
        content,
        settings=settings,
        to_address="olive@example.com",
        message_id="<abc@soundings.example.com>",
        now=datetime(2026, 10, 7, 8, 0, tzinfo=UTC),
    )

    assert f"Subject: {subject}\r\n".encode() in to_bytes(message)


@pytest.mark.parametrize(
    ("base_url", "domain"),
    [
        ("https://soundings.example.com", "soundings.example.com"),
        ("http://10.0.0.5:8000", "[10.0.0.5]"),
        ("http://[2001:db8::1]:8000", "[IPv6:2001:db8::1]"),
    ],
)
def test_message_ids_use_a_domain_or_an_address_literal(base_url: str, domain: str) -> None:
    """Review nit: with an IP base URL the Message-ID's right side was a bare IP."""
    settings = make_settings(environment="test", base_urls=[base_url])

    message_id = new_message_id(settings)

    assert re.fullmatch(rf"<[0-9a-f]{{32}}@{re.escape(domain)}>", message_id)
    assert message_id_domain(settings) == domain


@pytest.mark.parametrize("colour", ["red", "#12345", "#1d5fa8;background:url(x)", "#GGGGGG"])
def test_branding_colours_must_be_hex(colour: str) -> None:
    """Review nit: colours go into inline CSS, which autoescaping does not protect."""
    with pytest.raises(ValueError, match="hex colour"):
        Branding(accent=colour)
    with pytest.raises(ValueError, match="hex colour"):
        Branding(accent_text=colour)


def test_branding_accepts_hex_colours() -> None:
    assert Branding(accent="#0A0b0C", accent_text="#fff").accent == "#0A0b0C"
