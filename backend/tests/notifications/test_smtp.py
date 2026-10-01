"""The SMTP transport against a local fake server, and error classification
(contract-phase3 section 3.9: transient vs permanent, sanitised ``last_error``)."""

from __future__ import annotations

import ssl
from dataclasses import replace
from datetime import UTC, datetime
from email.message import EmailMessage

import aiosmtplib
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.email.message import build_message
from app.email.preview import sample_contents
from app.email.render import render
from app.email.smtp import SmtpTransport, classify
from tests.conftest import make_settings
from tests.notifications.smtp_server import FakeSmtpServer


def smtp_settings(port: int, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "smtp_host": "127.0.0.1",
        "smtp_port": port,
        "smtp_security": "none",
        "smtp_from": "soundings@example.com",
        "smtp_timeout": 2,
    }
    values.update(overrides)
    return make_settings(**values)


def message(to: str = "olive@example.com") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "soundings@example.com"
    msg["To"] = to
    msg["Subject"] = "Hello"
    msg.set_content("Hi")
    return msg


async def test_plain_smtp_sends_to_exactly_one_recipient() -> None:
    async with FakeSmtpServer() as server:
        transport = SmtpTransport(smtp_settings(server.port))
        # Even if the headers named more people, the envelope has the one address.
        msg = message("olive@example.com, mallory@example.com")
        msg["Cc"] = "eve@example.com"

        await transport.send(msg, sender="soundings@example.com", recipient="olive@example.com")

    [received] = server.messages
    assert received.sender == "soundings@example.com"
    assert received.recipients == ["olive@example.com"]


async def test_auth_with_the_configured_credentials() -> None:
    async with FakeSmtpServer(username="relay", password="s3cret") as server:
        good = smtp_settings(
            server.port, smtp_username=SecretStr("relay"), smtp_password=SecretStr("s3cret")
        )
        await SmtpTransport(good).send(message(), sender="s@example.com", recipient="o@example.com")
        bad = smtp_settings(
            server.port, smtp_username=SecretStr("relay"), smtp_password=SecretStr("wrong")
        )
        with pytest.raises(aiosmtplib.SMTPAuthenticationError) as raised:
            await SmtpTransport(bad).send(
                message(), sender="s@example.com", recipient="o@example.com"
            )

    assert len(server.messages) == 1
    failure = classify(raised.value)
    assert (failure.transient, failure.last_error) == (True, "SMTP 535: authentication failed")


@pytest.mark.parametrize(
    ("command", "reply", "transient", "last_error"),
    [
        ("RCPT", "450 4.2.1 Mailbox busy: olive@example.com", True, "SMTP 450: recipient refused"),
        ("RCPT", "550 5.1.1 No such user olive@example.com", False, "SMTP 550: recipient refused"),
        ("MAIL", "451 4.3.0 Try again later", True, "SMTP 451: sender refused"),
        ("MAIL", "530 5.7.0 Authentication required", True, "SMTP 530: authentication failed"),
        ("MAIL", "553 5.1.8 Sender rejected", False, "SMTP 553: sender refused"),
        ("DATA", "554 5.6.0 Message refused", False, "SMTP 554: message refused"),
        ("EHLO", "421 4.3.2 Too busy", True, "SMTP 421: server busy"),
    ],
)
async def test_server_replies_are_classified(
    command: str, reply: str, transient: bool, last_error: str
) -> None:
    async with FakeSmtpServer() as server:
        server.fail_next(command, reply)
        if command == "EHLO":
            server.fail_next("HELO", reply)
        with pytest.raises((aiosmtplib.SMTPException, OSError)) as raised:
            await SmtpTransport(smtp_settings(server.port)).send(
                message(), sender="soundings@example.com", recipient="olive@example.com"
            )

    failure = classify(raised.value)
    assert (failure.transient, failure.last_error) == (transient, last_error)
    assert "olive" not in failure.last_error
    assert "@" not in failure.last_error


async def test_starttls_against_a_server_without_it_is_transient() -> None:
    async with FakeSmtpServer() as server:
        with pytest.raises(aiosmtplib.SMTPException) as raised:
            await SmtpTransport(smtp_settings(server.port, smtp_security="starttls")).send(
                message(), sender="soundings@example.com", recipient="olive@example.com"
            )

    failure = classify(raised.value)
    assert failure.transient
    assert failure.last_error == "server doesn't support STARTTLS or AUTH"


async def test_connection_refused_is_transient() -> None:
    async with FakeSmtpServer() as server:
        port = server.port  # closed when the block ends
    with pytest.raises((aiosmtplib.SMTPException, OSError)) as raised:
        await SmtpTransport(smtp_settings(port)).send(
            message(), sender="soundings@example.com", recipient="olive@example.com"
        )

    failure = classify(raised.value)
    assert (failure.transient, failure.last_error) == (True, "connection refused")


@pytest.mark.parametrize(
    ("error", "transient", "last_error"),
    [
        (aiosmtplib.SMTPConnectTimeoutError("t"), True, "connection timed out"),
        (aiosmtplib.SMTPReadTimeoutError("t"), True, "timed out"),
        (aiosmtplib.SMTPServerDisconnected("gone"), True, "server disconnected"),
        (aiosmtplib.SMTPNotSupported("no AUTH"), True, "server doesn't support STARTTLS or AUTH"),
        (aiosmtplib.SMTPException("odd"), True, "SMTP error"),
        (aiosmtplib.SMTPResponseException(452, "4.3.1 full"), True, "SMTP 452: server busy"),
        (aiosmtplib.SMTPResponseException(500, "5.5.1 what"), False, "SMTP 500: server error"),
        (
            aiosmtplib.SMTPAuthenticationError(534, "5.7.9 x"),
            True,
            "SMTP 534: authentication failed",
        ),
        (ssl.SSLCertVerificationError("bad cert"), True, "TLS certificate not trusted"),
        (ssl.SSLError("handshake"), True, "TLS handshake failed"),
        (ConnectionRefusedError(), True, "connection refused"),
        (TimeoutError(), True, "timed out"),
        (OSError("Name or service not known: smtp.example.com"), True, "connection failed"),
        (ValueError("olive@example.com"), False, "Internal error"),
    ],
)
def test_classification(error: BaseException, transient: bool, last_error: str) -> None:
    failure = classify(error)

    assert (failure.transient, failure.last_error) == (transient, last_error)
    assert len(failure.last_error) <= 200


def test_a_tls_error_wrapped_in_a_connect_error_names_tls() -> None:
    cause = ssl.SSLCertVerificationError("certificate verify failed")
    error = aiosmtplib.SMTPConnectError("Error connecting: certificate verify failed")
    error.__cause__ = cause

    assert classify(error).last_error == "TLS certificate not trusted"


async def test_a_long_list_unsubscribe_header_stays_usable_on_the_wire() -> None:
    """Folding at 78 would turn the URL into RFC 2047 encoded words; on the wire the
    header is one ``<url>`` line (bodies are quoted-printable, lines <= 998)."""
    long_url = "http://localhost:8000/api/v1/unsubscribe?token=" + "A" * 180
    content = replace(sample_contents()["evaluator_invited"], list_unsubscribe_url=long_url)
    async with FakeSmtpServer() as server:
        settings = smtp_settings(server.port)
        msg = build_message(
            render(content),
            content,
            settings=settings,
            to_address="olive@example.com",
            message_id="<m@localhost>",
            now=datetime.now(UTC),
        )
        await SmtpTransport(settings).send(
            msg, sender="soundings@example.com", recipient="olive@example.com"
        )

    raw = server.messages[0].data
    headers = raw.split(b"\r\n\r\n", 1)[0].decode("ascii")
    assert f"\r\nList-Unsubscribe: <{long_url}>\r\n" in headers
    parsed = server.messages[0].message
    assert parsed["List-Unsubscribe"] == f"<{long_url}>"
    assert [part["Content-Transfer-Encoding"] for part in parsed.iter_parts()] == [
        "quoted-printable",
        "quoted-printable",
    ]
    assert max(len(line) for line in raw.split(b"\r\n")) <= 998
