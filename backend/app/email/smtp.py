"""Talking to the SMTP server (aiosmtplib) and classifying what went wrong.

Security modes (contract-phase3 section 3.1): ``none`` (plain; ``start_tls=False``
explicitly, since aiosmtplib's default is opportunistic STARTTLS), ``starttls``
(upgrade, certificate and host name verified) and ``tls`` (implicit TLS). A custom CA
bundle replaces the system trust store. The envelope always has exactly one recipient,
passed explicitly, never derived from the headers.

:func:`classify` turns an exception into a :class:`Failure`: transient (retry with
backoff) or permanent, and a ``last_error`` phrase built by our code, never the
server's reply text or an exception message (they can echo addresses).
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Final, Protocol

import aiosmtplib

from app.config import Settings
from app.email.message import to_bytes

__all__ = [
    "AUTH_CODES",
    "Failure",
    "SmtpTransport",
    "Transport",
    "classify",
    "internal_failure",
]

AUTH_CODES: Final = frozenset({530, 534, 535, 538})
"""Authentication required / failed: transient (a password being rotated shouldn't fail
every queued email at once; after the last attempt they fail)."""


class Transport(Protocol):
    """Sends one message to one address; raises on failure."""

    async def send(self, message: EmailMessage, *, sender: str, recipient: str) -> None: ...


class SmtpTransport:
    """The real thing: one connection per message (simple, and nothing to keep alive)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _tls_context(self) -> ssl.SSLContext | None:
        if self.settings.smtp_security == "none":
            return None
        cafile = str(self.settings.smtp_ca_bundle) if self.settings.smtp_ca_bundle else None
        return ssl.create_default_context(cafile=cafile)

    async def send(self, message: EmailMessage, *, sender: str, recipient: str) -> None:
        settings = self.settings
        assert settings.smtp_host is not None  # noqa: S101 - only called when configured
        username = settings.smtp_username.get_secret_value() if settings.smtp_username else None
        password = settings.smtp_password.get_secret_value() if settings.smtp_password else None
        await aiosmtplib.send(
            to_bytes(message),
            sender=sender,
            recipients=[recipient],
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            use_tls=settings.smtp_security == "tls",
            start_tls=settings.smtp_security == "starttls",
            validate_certs=True,
            tls_context=self._tls_context(),
            username=username or None,
            password=password or None,
            timeout=settings.smtp_timeout,
        )


@dataclass(frozen=True, slots=True)
class Failure:
    """Why an attempt failed. ``error_class`` and ``code`` are safe to log."""

    transient: bool
    last_error: str
    error_class: str
    code: int | None = None


def internal_failure(exc: BaseException) -> Failure:
    """A non-SMTP exception after the claim (template, data or programming error)."""
    return Failure(transient=False, last_error="Internal error", error_class=type(exc).__name__)


def _reply(exc: BaseException, code: int, phrase: str) -> Failure:
    name = type(exc).__name__
    if code in AUTH_CODES:
        return Failure(True, f"SMTP {code}: authentication failed", name, code)
    if 400 <= code < 500:
        return Failure(True, f"SMTP {code}: {phrase}", name, code)
    if 500 <= code < 600:
        return Failure(False, f"SMTP {code}: {phrase}", name, code)
    return Failure(True, "SMTP error", name, code)


def _tls(exc: BaseException) -> Failure | None:
    cause: BaseException | None = exc
    seen = 0
    while cause is not None and seen < 5:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return Failure(True, "TLS certificate not trusted", type(exc).__name__)
        if isinstance(cause, ssl.SSLError):
            return Failure(True, "TLS handshake failed", type(exc).__name__)
        cause = cause.__cause__ or cause.__context__
        seen += 1
    return None


def classify(exc: BaseException) -> Failure:
    """Transient vs permanent (contract-phase3 section 3.9) and a fixed phrase."""
    name = type(exc).__name__
    if isinstance(exc, aiosmtplib.SMTPRecipientsRefused):
        codes = [refused.code for refused in exc.recipients]
        code = codes[0] if codes else 550
        return _reply(exc, code, "recipient refused")
    if isinstance(exc, aiosmtplib.SMTPAuthenticationError):
        return Failure(True, f"SMTP {exc.code}: authentication failed", name, exc.code)
    if isinstance(exc, aiosmtplib.SMTPRecipientRefused):
        return _reply(exc, exc.code, "recipient refused")
    if isinstance(exc, aiosmtplib.SMTPSenderRefused):
        return _reply(exc, exc.code, "sender refused")
    if isinstance(exc, aiosmtplib.SMTPDataError):
        return _reply(exc, exc.code, "message refused")
    if isinstance(exc, aiosmtplib.SMTPConnectTimeoutError):
        return Failure(True, "connection timed out", name)
    if isinstance(exc, aiosmtplib.SMTPConnectResponseError):
        return _reply(exc, exc.code, "server busy" if 400 <= exc.code < 500 else "server error")
    if isinstance(exc, aiosmtplib.SMTPConnectError):
        return _tls(exc) or Failure(True, "connection refused", name)
    if isinstance(exc, aiosmtplib.SMTPTimeoutError):
        return Failure(True, "timed out", name)
    if isinstance(exc, aiosmtplib.SMTPServerDisconnected):
        return _tls(exc) or Failure(True, "server disconnected", name)
    if isinstance(exc, aiosmtplib.SMTPNotSupported):
        return Failure(True, "server doesn't support STARTTLS or AUTH", name)
    if isinstance(exc, aiosmtplib.SMTPResponseException):
        return _reply(exc, exc.code, "server busy" if 400 <= exc.code < 500 else "server error")
    if isinstance(exc, aiosmtplib.SMTPException):
        # aiosmtplib reports a missing STARTTLS or AUTH as a plain SMTPException; its
        # message (ours to read, never to log) tells which.
        text = str(exc)
        if "not supported" in text or "No suitable authentication method" in text:
            return Failure(True, "server doesn't support STARTTLS or AUTH", name)
        return _tls(exc) or Failure(True, "SMTP error", name)
    if isinstance(exc, ssl.SSLError):
        return _tls(exc) or Failure(True, "TLS handshake failed", name)
    if isinstance(exc, ConnectionRefusedError):
        return Failure(True, "connection refused", name)
    if isinstance(exc, TimeoutError):
        return Failure(True, "timed out", name)
    if isinstance(exc, OSError):
        return Failure(True, "connection failed", name)
    return internal_failure(exc)
