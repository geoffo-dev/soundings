"""Rules encoded in the Phase 3 schemas (contract-phase3): notification types and their
defaults, unsubscribe scopes, the @mention syntax and the admin email shapes."""

from __future__ import annotations

from typing import get_args
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.config import MAIL_ADDRESS_PATTERN, is_mail_address
from app.config import SmtpSecurity as SettingsSmtpSecurity
from app.models.enums import EmailType, NotificationMode, NotificationType
from app.schemas.comments import (
    MAX_MENTIONS,
    MENTION_PATTERN,
    mention_token,
    mentioned_user_ids,
)
from app.schemas.email import EmailTestRequest, OutboxEmail, SmtpSecurity
from app.schemas.notifications import (
    DEFAULT_MODES,
    NotificationItem,
    NotificationPreferencesUpdate,
    NotificationSummary,
    UnsubscribeScope,
)

ADA = UUID("5f0e8a52-3c1d-4b8e-9a6f-2d7c4e1b9a03")
BOB = UUID("8c2d6f14-9e3b-4a7d-b1c5-6e0f2a8d4b17")


def test_every_type_has_a_default_email_mode() -> None:
    assert set(DEFAULT_MODES) == set(NotificationType)
    # What you must act on arrives now; what you follow arrives in the digest.
    assert DEFAULT_MODES[NotificationType.EVALUATOR_INVITED] is NotificationMode.IMMEDIATE
    assert DEFAULT_MODES[NotificationType.MENTION] is NotificationMode.IMMEDIATE
    assert DEFAULT_MODES[NotificationType.COMMENT] is NotificationMode.DIGEST
    assert DEFAULT_MODES[NotificationType.STATUS_CHANGED] is NotificationMode.DIGEST


def test_preferences_update_has_one_field_per_type() -> None:
    assert set(NotificationPreferencesUpdate.model_fields) == {t.value for t in NotificationType}


def test_unsubscribe_scopes_are_the_types_plus_digest_and_all() -> None:
    assert {scope.value for scope in UnsubscribeScope} == {t.value for t in NotificationType} | {
        "digest",
        "all",
    }


def test_every_notification_type_is_an_email_type() -> None:
    assert {t.value for t in NotificationType} <= {t.value for t in EmailType}


def test_the_inbox_union_covers_every_type() -> None:
    members = get_args(get_args(NotificationItem)[0])
    literals = {get_args(member.model_fields["type"].annotation)[0] for member in members}

    assert literals == {t.value for t in NotificationType}


def test_notification_payloads_have_no_score_fields() -> None:
    """Role matrix section 3, rule 8: nothing score-shaped in a notification."""
    members = get_args(get_args(NotificationItem)[0])
    fields = {name for member in members for name in member.model_fields}

    assert not {name for name in fields if "score" in name or "recommendation" in name}


def test_smtp_security_matches_the_settings() -> None:
    assert get_args(SmtpSecurity) == get_args(SettingsSmtpSecurity)


def test_preferences_update_rejects_unknown_types_and_modes() -> None:
    adapter = TypeAdapter(NotificationPreferencesUpdate)
    assert adapter.validate_python({"comment": "off"}).comment is NotificationMode.OFF
    for body in ({"comment": "weekly"}, {"comments": "off"}):
        with pytest.raises(ValidationError):
            adapter.validate_python(body)


@pytest.mark.parametrize(
    "to",
    [
        "root@soundings.invalid",
        "x@example.invalid.",
        "nope",
        "a b@c",
        # One address only: anything aiosmtplib could read as a second recipient.
        "victim@corp.com,postmaster",
        "victim@corp.com;postmaster@corp.com",
        "victim@corp.com postmaster@corp.com",
        "Ops <ops@example.com>",
        '"ops,postmaster"@example.com',
        "ops@[10.0.0.1]",
        "ops@example.com\r\nBcc: x@example.com",
        "\u00fcser@example.com",
        "ops..x@example.com",
        "ops@-example.com",
        "x" * 65 + "@example.com",
        "ops@" + "a" * 250 + ".com",
    ],
)
def test_test_email_rejects_bad_reserved_and_multiple_addresses(to: str) -> None:
    with pytest.raises(ValidationError):
        EmailTestRequest(to=to)


@pytest.mark.parametrize(
    "to", ["ops@example.com", "o.p+s@mail.example.co.uk", "ops@localhost", "x" * 64 + "@e.io"]
)
def test_test_email_accepts_one_plain_address(to: str) -> None:
    assert EmailTestRequest(to=f" {to} ").to == to


def test_test_email_defaults_to_yourself() -> None:
    assert EmailTestRequest().to is None


def test_the_test_email_address_rule_is_the_settings_rule() -> None:
    """From, Reply-To, the test email's to and (at send time) every recipient share one
    pattern (contract-phase3 section 3.11)."""
    schema = EmailTestRequest.model_json_schema()
    pattern = schema["properties"]["to"]["anyOf"][0]["pattern"]

    assert pattern == MAIL_ADDRESS_PATTERN
    assert is_mail_address("ops@example.com")
    assert not is_mail_address("victim@corp.com,postmaster")


def test_summary_tells_admins_about_failing_email_without_scores() -> None:
    assert set(NotificationSummary.model_fields) == {
        "unread_count",
        "email_available",
        "email_trouble",
    }


def test_outbox_emails_say_whether_they_can_be_retried() -> None:
    assert "retryable" in OutboxEmail.model_fields
    assert not {name for name in OutboxEmail.model_fields if name in {"subject", "body"}}


# --- @mentions ------------------------------------------------------------------------
def test_mentions_are_found_once_in_order() -> None:
    body = (
        f"Thanks @[Bob B](user:{BOB}) and @[Ada](user:{ADA})! "
        f"@[Bob again](user:{str(BOB).upper()}) see above."
    )

    assert mentioned_user_ids(body) == [BOB, ADA]


@pytest.mark.parametrize(
    "body",
    [
        f"@Ada (user:{ADA})",
        f"[Ada](user:{ADA})",  # no @
        f"@[](user:{ADA})",  # empty label
        f"@[Ada\nLovelace](user:{ADA})",  # line break in the label
        "@[Ada](user:not-a-uuid)",
        f"@[Ada](mailto:{ADA})",
        f"@[{'x' * 101}](user:{ADA})",
    ],
)
def test_malformed_mentions_are_plain_text(body: str) -> None:
    assert mentioned_user_ids(body) == []


def test_mention_tokens_round_trip_and_cannot_break_out_of_the_label() -> None:
    token = mention_token(ADA, "Ada [admin]\nLovelace")
    match = MENTION_PATTERN.fullmatch(token)

    assert match is not None
    assert match.group("label") == "Ada admin Lovelace"
    assert mentioned_user_ids(token) == [ADA]
    assert mention_token(ADA, "[]") == f"@[user](user:{ADA})"
    assert len(MENTION_PATTERN.fullmatch(mention_token(ADA, "A" * 300))["label"]) == 100  # type: ignore[index]


def test_mention_limit_is_documented_value() -> None:
    many = " ".join(mention_token(uuid4(), f"User {n}") for n in range(MAX_MENTIONS + 1))

    assert len(mentioned_user_ids(many)) == MAX_MENTIONS + 1  # the service refuses it (422)
