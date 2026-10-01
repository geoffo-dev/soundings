"""Rules encoded in the Phase 4 schemas (contract-phase4): the proposal template,
branding values that can reach CSS, the public form's body, tokens and slugs."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.models.branding import HEX_COLOR_PATTERN
from app.models.enums import BrandFont, HoldReason, ProposalSectionKey
from app.schemas.branding import (
    DEFAULT_BRANDING,
    BrandingUpdate,
    EffectiveBranding,
    normalise_hex_color,
)
from app.schemas.projects import RESERVED_SLUGS, ProjectCreate
from app.schemas.proposals import PROPOSAL_TEMPLATE, ProposalSectionUpdate
from app.schemas.public import (
    AltchaChallenge,
    PublicSubmissionCreate,
    TrackingRequest,
    VerificationRequest,
)

CHALLENGE = {
    "parameters": {
        "algorithm": "PBKDF2/SHA-256",
        "cost": 5000,
        "keyLength": 32,
        "keyPrefix": "00",
        "nonce": "a1" * 16,
        "salt": "b2" * 16,
        "expiresAt": 1_790_000_000,
        "data": {"project": "customer-innovation"},
    },
    "signature": "c3" * 32,
}


def test_the_template_is_the_specs_eight_sections_in_order() -> None:
    assert [section.key for section in PROPOSAL_TEMPLATE] == list(ProposalSectionKey)
    assert [section.title for section in PROPOSAL_TEMPLATE] == [
        "Summary",
        "Problem",
        "Solution",
        "Market & users",
        "Cost & effort",
        "Benefits / revenue",
        "Risks",
        "Next steps / the ask",
    ]
    assert all(section.prompt.endswith((".", "?")) for section in PROPOSAL_TEMPLATE)


def test_a_section_save_names_the_version_it_started_from() -> None:
    assert ProposalSectionUpdate(body_md="", base_version=1).body_md == ""
    with pytest.raises(ValidationError):
        ProposalSectionUpdate.model_validate({"body_md": "x"})


@pytest.mark.parametrize(
    "text",
    [
        "    an indented code block\n",  # leading spaces are Markdown, not padding
        "First paragraph.\n\n",  # autosave mid-typing: the new lines must survive
        "Ends with a space ",
        " \n\t\n",
    ],
)
def test_section_text_is_kept_verbatim(text: str) -> None:
    """Request strings are stripped everywhere else; a section's Markdown never is."""
    body = ProposalSectionUpdate.model_validate({"body_md": text, "base_version": 2})

    assert body.body_md == text


def test_section_text_still_refuses_nul_and_overlong_text() -> None:
    for text in ("a\x00b", "x" * 20_001):
        with pytest.raises(ValidationError):
            ProposalSectionUpdate.model_validate({"body_md": text, "base_version": 1})
    assert len(ProposalSectionUpdate(body_md=" " * 20_000, base_version=1).body_md) == 20_000


@pytest.mark.parametrize("value", ["#1D5FA8", "#1d5fa8", " #0b6e4f "])
def test_colours_are_normalised_hex(value: str) -> None:
    color = BrandingUpdate.model_validate({"primary_color": value}).primary_color

    assert color == value.strip().lower()
    assert color is not None
    assert normalise_hex_color(color) == color


@pytest.mark.parametrize(
    "value",
    [
        "red",
        "#abc",
        "#1d5fa8ff",
        "1d5fa8",
        "#1d5fa8;",
        "#1d5f;}",
        "rgb(29, 95, 168)",
        "var(--x)",
        "#\uff46\uff46\uff46\uff46\uff46\uff46",  # full-width letters are not hex
    ],
)
def test_anything_but_hex_colours_is_refused(value: str) -> None:
    """Colours reach CSS custom properties, PDFs and emails: only #rrggbb gets through
    (no CSS injection through branding)."""
    with pytest.raises(ValidationError):
        BrandingUpdate.model_validate({"primary_color": value})
    with pytest.raises(ValidationError):
        BrandingUpdate.model_validate({"accent_color": value})


def test_the_database_pattern_matches_the_normalised_api_value() -> None:
    assert HEX_COLOR_PATTERN == r"^#[0-9a-f]{6}$"


@pytest.mark.parametrize("font", ["Inter", "inter, serif", "inter;}", "Comic Sans MS"])
def test_fonts_are_bundled_keys_only(font: str) -> None:
    with pytest.raises(ValidationError):
        BrandingUpdate.model_validate({"font": font})


def test_fonts_and_defaults() -> None:
    assert {font.value for font in BrandFont} == {
        "inter",
        "ibm_plex_sans",
        "source_serif_4",
        "atkinson_hyperlegible",
    }
    assert DEFAULT_BRANDING.app_name == "Soundings"
    assert DEFAULT_BRANDING.primary_color == DEFAULT_BRANDING.accent_color == "#1d5fa8"
    assert DEFAULT_BRANDING.font is BrandFont.INTER


@pytest.mark.parametrize(
    ("footer", "ok"),
    [
        ("Acme Ltd\n1 High Street, London\nRegistered in England 01234567", True),
        ("Acme Ltd   \nLondon", True),
        ("1\n2\n3\n4\n5", True),
        ("1\n2\n3\n4\n5\n6", False),
        ("Acme\r\nLtd", False),
        ("Acme\tLtd", False),
        ("Acme \u202eLtd", False),
        ("x" * 501, False),
    ],
)
def test_the_email_footer_is_short_plain_text(footer: str, ok: bool) -> None:
    if ok:
        stored = BrandingUpdate.model_validate({"email_footer": footer}).email_footer
        assert stored is not None
        assert all(line == line.rstrip() for line in stored.split("\n"))
    else:
        with pytest.raises(ValidationError):
            BrandingUpdate.model_validate({"email_footer": footer})


def test_an_empty_branding_update_resets_every_field() -> None:
    assert BrandingUpdate().model_dump() == dict.fromkeys(BrandingUpdate.model_fields)


def test_effective_branding_always_has_every_value() -> None:
    fields = EffectiveBranding.model_json_schema(mode="serialization")["required"]
    assert set(fields) == set(EffectiveBranding.model_fields)


def _submission(**values: Any) -> dict[str, Any]:
    return {"title": "Print-free returns", "summary": "Show a QR code.", "altcha": "abc="} | values


def test_the_public_form_needs_only_a_title_summary_and_proof_of_work() -> None:
    body = PublicSubmissionCreate.model_validate(_submission(name=" ", email=""))

    assert (body.name, body.email, body.wants_updates, body.website) == (None, None, False, "")


@pytest.mark.parametrize("value", ["https://example.org", "x" * 5_000, "<a href=x>spam</a>"])
def test_the_other_field_accepts_anything(value: str) -> None:
    """The honeypot never gives itself away with a 422: any value, any length, is a
    valid body (the server then answers 201 without keeping anything)."""
    assert PublicSubmissionCreate.model_validate(_submission(website=value)).website == value


def test_the_other_field_is_described_neutrally() -> None:
    schema = PublicSubmissionCreate.model_json_schema()["properties"]["website"]

    assert "honeypot" not in str(schema).lower()
    assert "maxLength" not in schema


@pytest.mark.parametrize(
    "values",
    [
        {"wants_updates": True},
        {"email": "jo@example.org, eve@example.org"},
        {"email": "jo@soundings.invalid"},
        {"title": "One\ntwo"},
        {"name": "Jo\u202e"},
        {"altcha": ""},
        {"submitted_by_id": "5f0e8a52-3c1d-4b8e-9a6f-2d7c4e1b9a03"},
        {"held_for": None},
    ],
)
def test_the_public_form_refuses(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PublicSubmissionCreate.model_validate(_submission(**values))


def test_the_altcha_challenge_keeps_the_widgets_format() -> None:
    challenge = AltchaChallenge.model_validate(CHALLENGE)

    assert challenge.model_dump(mode="json") == CHALLENGE
    schema = AltchaChallenge.model_json_schema(mode="serialization")
    parameters = schema["$defs"]["AltchaParameters"]["properties"]
    assert {"keyLength", "keyPrefix", "expiresAt", "data"} <= set(parameters)


@pytest.mark.parametrize(
    "token", ["", "a" * 42, "a" * 44, "a" * 42 + "=", "a" * 42 + "/", "a" * 42 + "."]
)
def test_tracking_tokens_are_43_base64url_characters(token: str) -> None:
    with pytest.raises(ValidationError):
        TrackingRequest(token=token)
    assert TrackingRequest(token="A_-" + "b" * 40).token


@pytest.mark.parametrize("token", ["short", "a" * 513, "abc def" * 4, "abc%2F" * 4])
def test_verification_tokens_are_signed_compact_strings(token: str) -> None:
    with pytest.raises(ValidationError):
        VerificationRequest(token=token)


def test_hold_reasons() -> None:
    assert {reason.value for reason in HoldReason} == {"email_verification", "moderation"}


@pytest.mark.parametrize("slug", sorted(RESERVED_SLUGS))
def test_reserved_slugs_are_refused(slug: str) -> None:
    with pytest.raises(ValidationError):
        ProjectCreate.model_validate({"name": "X", "slug": slug, "key": "XX"})


def test_ordinary_slugs_still_work() -> None:
    assert ProjectCreate.model_validate({"name": "X", "slug": "trackers", "key": "XX"}).slug
