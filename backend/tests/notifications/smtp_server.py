"""A tiny in-process SMTP server for tests: enough of RFC 5321 for aiosmtplib (EHLO,
AUTH PLAIN, MAIL, RCPT, DATA, RSET, NOOP, QUIT), with scripted failures.

Usage::

    async with FakeSmtpServer() as server:
        server.fail_next("RCPT", "450 4.2.1 Mailbox busy")
        ... send to 127.0.0.1:server.port ...
        server.messages  # [Received(sender, recipients, data)]
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import EmailMessage
from types import TracebackType


@dataclass
class Received:
    sender: str
    recipients: list[str]
    data: bytes

    @property
    def message(self) -> EmailMessage:
        parsed = message_from_bytes(self.data, policy=policy.default)
        assert isinstance(parsed, EmailMessage)
        return parsed


@dataclass
class FakeSmtpServer:
    username: str | None = None
    password: str | None = None
    messages: list[Received] = field(default_factory=list)
    failures: dict[str, list[str]] = field(default_factory=dict)
    port: int = 0
    _server: asyncio.Server | None = None

    def fail_next(self, command: str, reply: str) -> None:
        """Answer the next ``command`` (EHLO, AUTH, MAIL, RCPT, DATA) with ``reply``."""
        self.failures.setdefault(command, []).append(reply)

    async def __aenter__(self) -> FakeSmtpServer:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    def _scripted(self, command: str) -> str | None:
        queue = self.failures.get(command)
        return queue.pop(0) if queue else None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def reply(line: str) -> None:
            writer.write(line.encode() + b"\r\n")
            await writer.drain()

        sender = ""
        recipients: list[str] = []
        await reply("220 fake.test ESMTP ready")
        try:
            while line := await reader.readline():
                text = line.decode().rstrip("\r\n")
                verb = text.split(" ", 1)[0].upper()
                failure = self._scripted(verb)
                if failure is not None:
                    await reply(failure)
                    if failure.startswith("421"):
                        break
                    continue
                if verb in ("EHLO", "HELO"):
                    writer.write(b"250-fake.test\r\n")
                    if self.username:
                        writer.write(b"250-AUTH PLAIN\r\n")
                    await reply("250 8BITMIME")
                elif verb == "AUTH":
                    parts = text.split(" ")
                    raw = parts[2] if len(parts) > 2 else ""
                    if not raw:
                        await reply("334 ")
                        raw = (await reader.readline()).decode().strip()
                    decoded = base64.b64decode(raw).split(b"\0")
                    user, pw = decoded[1].decode(), decoded[2].decode()
                    if (user, pw) == (self.username, self.password):
                        await reply("235 2.7.0 Authentication successful")
                    else:
                        await reply("535 5.7.8 Authentication credentials invalid")
                elif verb == "MAIL":
                    sender = text.split(":", 1)[1].split()[0].strip("<>")
                    recipients = []
                    await reply("250 OK")
                elif verb == "RCPT":
                    recipients.append(text.split(":", 1)[1].split()[0].strip("<>"))
                    await reply("250 OK")
                elif verb == "DATA":
                    await reply("354 End data with <CR><LF>.<CR><LF>")
                    chunks: list[bytes] = []
                    while (chunk := await reader.readline()) not in (b".\r\n", b""):
                        chunks.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                    self.messages.append(Received(sender, recipients, b"".join(chunks)))
                    await reply("250 OK queued")
                elif verb in ("RSET", "NOOP"):
                    await reply("250 OK")
                elif verb == "QUIT":
                    await reply("221 Bye")
                    break
                else:
                    await reply("502 Command not implemented")
        finally:
            writer.close()
