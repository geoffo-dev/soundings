"""Phase 11 schemas and authorisation entries (contract-phase11): messages between the team
and a public submitter (plain text), the tracking page's conversation, the tracking-link
email, "The submitter replied", the rule ``public.message_submitter`` (session only, c31) and
its key and guest rows. The table-driven policy tests are tests/authz/test_policy_matrix.py;
the behaviour tests come with the services (the builders' tests listed in
contract-phase11 section 13)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from app.authz import (
    POLICY,
    IdeaFacts,
    ProjectFacts,
    Resource,
    Rule,
    authorize,
    is_named_person,
)
from app.authz.guest import RESEARCH_GUEST_ACCESS, GuestAccess
from app.authz.keys import ROUTE_KEY_ACCESS, KeyAccess
from app.authz.policy import NAMED_PEOPLE_ONLY
from app.authz.rules import PUBLIC_RULES, RULE_SCOPES, SESSION_ONLY_RULES
from app.domain.principal import Principal
from app.models.enums import (
    SUBMITTER_EMAIL_TYPES,
    EmailType,
    HoldReason,
    IdeaStatus,
    MessageDirection,
    NotificationType,
    ProjectRole,
    ProjectVisibility,
)
from app.models.public import SUBMISSION_MESSAGE_MAX_LENGTH
from app.models.user import User
from app.schemas.audit import AuditAction
from app.schemas.notifications import (
    BID_NOTIFICATION_TYPES,
    DEFAULT_MODES,
    RESEARCH_GUEST_NOTIFICATION_TYPES,
    SUBMITTER_NOTIFICATION_TYPES,
    SUBMITTER_REPLIED_EMAIL_INTERVAL,
    NotificationMode,
    NotificationPreferencesUpdate,
    SubmitterRepliedNotification,
    UnsubscribeScope,
)
from app.schemas.public import (
    CONVERSATION_MAX_MESSAGES,
    SUBMITTER_MESSAGES_PER_ADDRESS_PER_HOUR,
    SUBMITTER_MESSAGES_PER_SUBMISSION_PER_DAY,
    SUBMITTER_MESSAGES_SINCE_TEAM_MESSAGE,
    TEAM_MESSAGES_PER_PERSON_PER_HOUR,
    TEAM_MESSAGES_PER_SUBMISSION_PER_DAY,
    EmailVerified,
    IdeaSubmission,
    ReplyBlocked,
    SendBlocked,
    SubmissionMessage,
    SubmissionMessageCreate,
    SubmissionMessagesSummary,
    TrackedMessage,
    TrackedSubmission,
    TrackingReplyRequest,
)

TOKEN = "Zq3v9Xb2Lk7Wm4Np8Rt6Yc1Hd5Gf0Js_Ua-Ee2Oo4Ii"
OPERATIONS = ("list_submission_messages", "send_submission_message")
PUBLIC_OPERATIONS = ("send_tracking_reply", "forget_submission_email")


# --- The text --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("sent", "stored"),
    [
        ("Thanks!", "Thanks!"),
        ("  padded  ", "padded"),
        ("one\r\ntwo\rthree\nfour", "one\ntwo\nthree\nfour"),
        # The Unicode line and paragraph separators are line breaks too (review C8).
        ("one\u2028two\u2029three", "one\ntwo\nthree"),
        # A mention-shaped token is plain text, kept as typed (review S5: no mentions here).
        ("Ask @[Priya Raman](user:3f0c) about it", "Ask @[Priya Raman](user:3f0c) about it"),
        ("zero\u200bwidth and \u202ebidi\u202c", "zerowidth and bidi"),
        ("<b>not html</b> **not markdown**", "<b>not html</b> **not markdown**"),
        ("x" * SUBMISSION_MESSAGE_MAX_LENGTH, "x" * SUBMISSION_MESSAGE_MAX_LENGTH),
    ],
)
def test_a_message_is_plain_visible_text(sent: str, stored: str) -> None:
    assert SubmissionMessageCreate(body=sent).body == stored
    assert TrackingReplyRequest(token=TOKEN, body=sent).body == stored


@pytest.mark.parametrize(
    "sent",
    [
        "",
        "   ",
        "\n\n",
        "\u200b\u2060",
        "\u2800",  # the braille blank shows nothing
        "nul\x00",
        "tag \U000e0041",
        "x" * (SUBMISSION_MESSAGE_MAX_LENGTH + 1),
    ],
)
def test_empty_hidden_or_long_messages_are_refused(sent: str) -> None:
    with pytest.raises(ValidationError):
        SubmissionMessageCreate(body=sent)
    with pytest.raises(ValidationError):
        TrackingReplyRequest(token=TOKEN, body=sent)


def test_requests_take_only_their_fields() -> None:
    with pytest.raises(ValidationError):
        SubmissionMessageCreate.model_validate({"body": "Hi", "author_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        TrackingReplyRequest.model_validate({"token": TOKEN, "body": "Hi", "direction": "team"})
    with pytest.raises(ValidationError):
        TrackingReplyRequest.model_validate({"token": "short", "body": "Hi"})


def test_the_limits_are_the_product_owners() -> None:
    assert SUBMISSION_MESSAGE_MAX_LENGTH == 4_000
    assert CONVERSATION_MAX_MESSAGES == 100  # one cap, all shown (review C1)
    assert TEAM_MESSAGES_PER_SUBMISSION_PER_DAY == 20
    assert TEAM_MESSAGES_PER_PERSON_PER_HOUR == 30
    assert SUBMITTER_MESSAGES_PER_SUBMISSION_PER_DAY == 10
    assert SUBMITTER_MESSAGES_SINCE_TEAM_MESSAGE == 10  # review S6
    assert SUBMITTER_MESSAGES_PER_ADDRESS_PER_HOUR == 30
    assert SUBMITTER_REPLIED_EMAIL_INTERVAL.total_seconds() == 3_600


# --- What each audience sees --------------------------------------------------------------
def _fields(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields)


_PERSON = re.compile(r"author|actor|user|name|address|owner|person", re.IGNORECASE)


def test_public_pages_show_no_people() -> None:
    """The tracking page's messages have a direction, never an author (public pages and
    submitter emails show no people: "The <project> team")."""
    assert _fields(TrackedMessage) == {"id", "direction", "body", "created_at"}
    added = {
        "can_remove_email",
        "messages",
        "team_messages_emailed",
        "can_reply",
        "reply_blocked",
    }
    assert added <= _fields(TrackedSubmission)
    assert "message_count" not in _fields(TrackedSubmission)  # review C1: all are shown
    assert not {name for name in added if _PERSON.search(name)}
    assert "tracking_link_emailed" in _fields(EmailVerified)


def test_the_team_sees_who_wrote_and_whether_it_was_emailed() -> None:
    assert _fields(SubmissionMessage) == {
        "id",
        "direction",
        "body",
        "created_at",
        "author",
        "emailed",
    }
    # The summary says where a message goes, never the address or why (contact details are
    # public.erase_submitter's).
    summary = _fields(SubmissionMessagesSummary)
    assert summary == {"count", "last_message_at", "last_direction", "delivery", "blocked"}
    # Until the panel's builders fill it: nothing (null for every non-holder anyway).
    assert IdeaSubmission.model_fields["messages"].default is None


def test_the_reply_notification_carries_no_public_text() -> None:
    assert _fields(SubmitterRepliedNotification) == {
        "id",
        "created_at",
        "read_at",
        "idea",
        "actor",
        "type",
    }


def test_a_message_round_trips() -> None:
    message = SubmissionMessage.model_validate(
        {
            "id": str(uuid.uuid4()),
            "direction": "submitter",
            "body": "All of them.",
            "created_at": datetime.now(UTC).isoformat(),
            "author": None,
            "emailed": False,
        }
    )

    assert message.direction is MessageDirection.SUBMITTER


# --- Notifications, emails and the audit log ----------------------------------------------
def test_the_reply_notification_type() -> None:
    assert list(NotificationType)[-1] is NotificationType.SUBMITTER_REPLIED
    assert {NotificationType.SUBMITTER_REPLIED} == SUBMITTER_NOTIFICATION_TYPES
    assert DEFAULT_MODES[NotificationType.SUBMITTER_REPLIED] is NotificationMode.IMMEDIATE
    # Only rule holders hold one: never a guest researcher, never a bid type.
    assert not SUBMITTER_NOTIFICATION_TYPES & RESEARCH_GUEST_NOTIFICATION_TYPES
    assert not SUBMITTER_NOTIFICATION_TYPES & BID_NOTIFICATION_TYPES
    assert "submitter_replied" in NotificationPreferencesUpdate.model_fields
    assert UnsubscribeScope("submitter_replied")
    assert EmailType("submitter_replied")


def test_one_list_of_submitter_emails() -> None:
    assert SUBMITTER_EMAIL_TYPES == (
        EmailType.SUBMISSION_RECEIVED,
        EmailType.SUBMISSION_STATUS_CHANGED,
        EmailType.SUBMISSION_LINK,
        EmailType.SUBMISSION_MESSAGE,
    )
    assert not {t.value for t in SUBMITTER_EMAIL_TYPES} & {t.value for t in NotificationType}
    assert not {t.value for t in SUBMITTER_EMAIL_TYPES} & {t.value for t in UnsubscribeScope}


def test_the_audit_action() -> None:
    assert AuditAction("submission.message") is AuditAction.SUBMISSION_MESSAGE


# --- The rule -----------------------------------------------------------------------------
def test_the_rule_is_session_only_and_idea_scoped() -> None:
    rule = Rule.PUBLIC_MESSAGE_SUBMITTER

    assert rule == "public.message_submitter"
    assert rule not in RULE_SCOPES
    assert rule in SESSION_ONLY_RULES
    assert rule not in PUBLIC_RULES
    assert POLICY[rule].scope == "idea"
    # Not an idea write: reading works in an archived project; sending's refusals are the
    # service's 409s. Not frozen while held for moderation (c19 doesn't apply).
    assert not POLICY[rule].idea_write
    assert not POLICY[rule].frozen_while_held
    assert rule in NAMED_PEOPLE_ONLY


def test_keys_and_guests_never_reach_the_conversation() -> None:
    for operation in OPERATIONS:
        assert ROUTE_KEY_ACCESS[operation] is KeyAccess.SESSION
        assert RESEARCH_GUEST_ACCESS[operation] is GuestAccess.HIDDEN
    for operation in PUBLIC_OPERATIONS:
        assert ROUTE_KEY_ACCESS[operation] is KeyAccess.PUBLIC
        assert operation not in RESEARCH_GUEST_ACCESS  # not an idea route
    # No MCP tool reads or writes it (guest rows exist for every tool).
    assert not [name for name in RESEARCH_GUEST_ACCESS if "message" in name and "mcp." in name]


def _who(*, admin: bool = False, agent: bool = False, break_glass: bool = False) -> Principal:
    user = User(
        id=uuid.uuid4(),
        email="x@example.com",
        display_name="X",
        is_platform_admin=admin,
        is_service_account=agent,
        is_break_glass=break_glass,
        is_active=True,
    )
    return Principal(user=user)


def test_c31_a_named_person_only() -> None:
    """The break-glass account is a platform admin (column PA) and an agent might hold an
    admin-like column through a mistake: both are refused by c31, not by the cells."""
    resource = Resource(
        project=ProjectFacts(id=uuid.uuid4(), visibility=ProjectVisibility.PRIVATE),
        idea=IdeaFacts(id=uuid.uuid4(), status=IdeaStatus.NEW),
    )
    admin = authorize(_who(admin=True), Rule.PUBLIC_MESSAGE_SUBMITTER, resource)
    glass = authorize(_who(admin=True, break_glass=True), Rule.PUBLIC_MESSAGE_SUBMITTER, resource)
    agent = authorize(
        _who(agent=True),
        Rule.PUBLIC_MESSAGE_SUBMITTER,
        resource.replace(role=ProjectRole.ADMIN),
    )

    assert admin.allowed
    assert (glass.allowed, glass.status, glass.code, glass.condition) == (
        False,
        403,
        "forbidden",
        "c31",
    )
    assert (agent.allowed, agent.status, agent.condition) == (False, 403, "c31")
    assert is_named_person(_who())
    assert is_named_person(_who(admin=True))
    assert not is_named_person(_who(agent=True))
    assert not is_named_person(_who(admin=True, break_glass=True))
    assert not is_named_person(None)


@pytest.mark.parametrize(
    ("held", "status", "allowed"),
    [
        (None, IdeaStatus.CLOSED, True),
        (HoldReason.MODERATION, IdeaStatus.NEW, True),
        (HoldReason.EMAIL_VERIFICATION, IdeaStatus.NEW, False),
    ],
)
def test_admins_may_message_on_closed_and_held_for_moderation_ideas(
    held: HoldReason | None, status: IdeaStatus, allowed: bool
) -> None:
    resource = Resource(
        project=ProjectFacts(id=uuid.uuid4(), visibility=ProjectVisibility.PRIVATE),
        role=ProjectRole.ADMIN,
        idea=IdeaFacts(id=uuid.uuid4(), status=status, held_for=held),
    )

    decision = authorize(_who(), Rule.PUBLIC_MESSAGE_SUBMITTER, resource)

    assert decision.allowed is allowed
    if not allowed:
        assert decision.status == 404  # held for email confirmation: nobody sees it (c12)


def test_new_response_fields_default_to_nothing() -> None:
    """Additive fields on Phase 4's models default to "no conversation, no link email", which
    is exactly what the built routes answer until Phase 11's services fill them."""
    assert SubmissionMessagesSummary.model_fields["blocked"].is_required()  # a new model
    defaults = {
        name: TrackedSubmission.model_fields[name].get_default(call_default_factory=True)
        for name in ("can_remove_email", "messages", "team_messages_emailed", "can_reply")
    }
    assert defaults == {
        "can_remove_email": False,
        "messages": [],
        "team_messages_emailed": False,
        "can_reply": False,
    }
    assert TrackedSubmission.model_fields["reply_blocked"].default == "awaiting_team"
    assert EmailVerified.model_fields["tracking_link_emailed"].default is False


def test_refusals_are_listed_in_the_order_they_are_checked() -> None:
    """The archived project leads the 409s, as everywhere (review C6); the instance switch
    blocks the team too, since no tracking link opens then (review C4)."""
    assert [value.value for value in SendBlocked] == [
        "project_archived",
        "submitter_erased",
        "public_submission_off",
        "conversation_full",
        "daily_limit",
    ]
    assert [value.value for value in ReplyBlocked] == [
        "project_archived",
        "awaiting_team",
        "conversation_full",
        "daily_limit",
    ]
