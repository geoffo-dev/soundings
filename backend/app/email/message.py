"""The MIME message: plain text plus an HTML alternative, and safe headers.

Addresses go through :class:`email.headerregistry.Address` (never string
concatenation); ``To`` is the one checked address and the SMTP envelope gets exactly
that address (:mod:`app.email.smtp`). Subjects have no line breaks (and the email
package refuses any that slip through). A subject that contains ``=?`` is sent
RFC 2047-encoded as a whole (:class:`EncodedHeader`): sent as typed, mail clients
would decode an encoded-word in an idea title and show text the app never accepted.

Both parts are quoted-printable (7-bit safe, lines <= 76). On the wire
(:func:`to_bytes`) headers may be up to 998 characters before folding, so a long
``List-Unsubscribe`` URL stays one ``<...>`` instead of being RFC 2047-encoded, which
mail clients can't use.
"""

from __future__ import annotations

import email.policy
from datetime import datetime
from email.header import Header
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import Policy
from email.utils import format_datetime

from app.config import Settings
from app.email.model import EmailContent
from app.email.render import RenderedEmail

__all__ = ["WIRE_POLICY", "EncodedHeader", "build_message", "subject_header", "to_bytes"]

WIRE_POLICY = email.policy.SMTP.clone(max_line_length=998)
"""CRLF line ends; headers fold only beyond RFC 5322's 998-character limit."""


class EncodedHeader(str):
    """A header value the email package keeps as is (it has a ``name``) and folds as
    UTF-8 encoded-words, whatever it contains. Reads back as the plain value."""

    name: str

    def __new__(cls, name: str, value: str) -> EncodedHeader:
        header = super().__new__(cls, value)
        header.name = name
        return header

    def fold(self, *, policy: Policy) -> str:
        encoded = Header(str(self), "utf-8", header_name=self.name).encode(linesep=policy.linesep)
        return f"{self.name}: {encoded}{policy.linesep}"


def subject_header(subject: str) -> str:
    """The ``Subject`` value: as typed, or :class:`EncodedHeader` when it contains
    ``=?`` (the start of an RFC 2047 encoded-word)."""
    return EncodedHeader("Subject", subject) if "=?" in subject else subject


def to_bytes(message: EmailMessage) -> bytes:
    """The message as sent (DATA)."""
    return message.as_bytes(policy=WIRE_POLICY)


def build_message(
    rendered: RenderedEmail,
    content: EmailContent,
    *,
    settings: Settings,
    to_address: str,
    message_id: str,
    now: datetime,
) -> EmailMessage:
    assert settings.smtp_from is not None  # noqa: S101 - only built when configured
    message = EmailMessage()
    message["From"] = Address(display_name=settings.smtp_from_name, addr_spec=settings.smtp_from)
    message["To"] = Address(addr_spec=to_address)
    if settings.smtp_reply_to:
        message["Reply-To"] = Address(addr_spec=settings.smtp_reply_to)
    message["Subject"] = subject_header(rendered.subject)
    message["Date"] = format_datetime(now)
    message["Message-ID"] = message_id
    message["Auto-Submitted"] = "auto-generated"
    message["X-Auto-Response-Suppress"] = "All"
    if content.list_unsubscribe_url:
        message["List-Unsubscribe"] = f"<{content.list_unsubscribe_url}>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if content.references:
        message["References"] = content.references
    message.set_content(rendered.text, cte="quoted-printable")
    message.add_alternative(rendered.html, subtype="html", cte="quoted-printable")
    return message
