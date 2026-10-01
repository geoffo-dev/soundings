"""Who the client is behind proxies (review M1): ``X-Forwarded-For`` is believed only
from a trusted proxy, and only as far as ``SOUNDINGS_TRUSTED_PROXY_HOPS`` proxies
appended to it, counted from the right. A client can always prepend entries of its
own, so the leftmost entry is never used just because every entry looks private."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware import ProxyHeadersMiddleware, TrustedProxies, forwarded_client
from tests.conftest import make_settings
from tests.identity.helpers import audit_entries

PRIVATE = TrustedProxies(["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"])
INGRESS = "10.42.0.7"  # the ingress controller's pod


@pytest.mark.parametrize(
    ("peer", "forwarded_for", "hops", "client"),
    [
        # Not from a trusted proxy: the header is the client's own claim.
        ("203.0.113.9", ["198.51.100.1"], 1, "203.0.113.9"),
        # From the ingress: the entry it appended (the rightmost).
        (INGRESS, ["198.51.100.1"], 1, "198.51.100.1"),
        (INGRESS, ["198.51.100.66, 198.51.100.1"], 1, "198.51.100.1"),
        # A client on a private network prepends whatever it likes: ignored.
        (INGRESS, ["10.99.0.1, 10.20.30.40"], 1, "10.20.30.40"),
        (INGRESS, ["pwn-123, 10.20.30.40"], 1, "10.20.30.40"),
        (INGRESS, ["203.0.113.1", "10.20.30.40"], 1, "10.20.30.40"),  # two header lines
        # Not an address: the proxy itself stays the client (no made-up throttle keys).
        (INGRESS, ["pwn-123"], 1, INGRESS),
        (INGRESS, ["198.51.100.1, "], 1, INGRESS),
        (INGRESS, [], 1, INGRESS),
        # Ports and IPv6.
        (INGRESS, ["198.51.100.1:4711"], 1, "198.51.100.1"),
        (INGRESS, ["[2001:db8::1]:443"], 1, "2001:db8::1"),
        (INGRESS, ["2001:db8::1"], 1, "2001:db8::1"),
        (INGRESS, ["::ffff:198.51.100.1"], 1, "198.51.100.1"),
        ("::ffff:10.42.0.7", ["198.51.100.1"], 1, "198.51.100.1"),
        # Two proxies (a load balancer in front of the ingress): two entries count...
        (INGRESS, ["203.0.113.66, 198.51.100.1, 10.1.0.9"], 2, "198.51.100.1"),
        # ...but an entry that isn't a trusted proxy added nothing to its left.
        (INGRESS, ["10.99.0.1, 198.51.100.1"], 2, "198.51.100.1"),
        # Fewer entries than hops: the leftmost of them.
        (INGRESS, ["10.1.0.9"], 2, "10.1.0.9"),
        # The peer isn't an IP address (a test client, a unix socket): unchanged.
        ("testclient", ["198.51.100.1"], 1, "testclient"),
    ],
)
def test_forwarded_client(peer: str, forwarded_for: list[str], hops: int, client: str) -> None:
    assert forwarded_client(peer, forwarded_for, PRIVATE, hops) == client


def test_everyone_trusted() -> None:
    everyone = TrustedProxies(["*"])

    assert forwarded_client("203.0.113.9", ["198.51.100.1"], everyone, 1) == "198.51.100.1"
    assert forwarded_client("203.0.113.9", ["x, 198.51.100.1"], everyone, 1) == "198.51.100.1"


@pytest.mark.parametrize("value", [["10.0.0.0/8", "nonsense"], ["unix:/tmp/sock"], ["10.0.0.0/33"]])
def test_trusted_proxies_must_be_addresses_or_networks(value: list[str]) -> None:
    with pytest.raises(ValidationError):
        make_settings(trusted_proxies=value)


def test_trusted_proxy_hops_setting() -> None:
    assert make_settings().trusted_proxy_hops == 1
    assert make_settings(trusted_proxy_hops=2).trusted_proxy_hops == 2
    with pytest.raises(ValidationError):
        make_settings(trusted_proxy_hops=0)


async def _seen(peer: str, headers: dict[str, str], *, scope_type: str = "http") -> tuple[Any, str]:
    seen: dict[str, Any] = {}

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.update(client=scope.get("client"), scheme=scope.get("scheme"))

    middleware = ProxyHeadersMiddleware(app, trusted_proxies=["10.0.0.0/8"], hops=1)
    scope = {
        "type": scope_type,
        "scheme": "ws" if scope_type == "websocket" else "http",
        "client": (peer, 5000),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }

    async def receive() -> Any:
        raise AssertionError("not read")

    async def send(message: Any) -> None:
        raise AssertionError("not sent")

    await middleware(scope, receive, send)
    return seen["client"], seen["scheme"]


async def test_middleware_sets_client_and_scheme_from_a_trusted_proxy() -> None:
    headers = {"X-Forwarded-For": "1.2.3.4, 198.51.100.1", "X-Forwarded-Proto": "https"}

    assert await _seen(INGRESS, headers) == (("198.51.100.1", 0), "https")
    assert await _seen("203.0.113.9", headers) == (("203.0.113.9", 5000), "http")
    assert await _seen(INGRESS, {"X-Forwarded-Proto": "gopher"}) == ((INGRESS, 5000), "http")
    assert await _seen(INGRESS, {"X-Forwarded-Proto": "http, https"}) == (
        (INGRESS, 5000),
        "https",
    )
    assert await _seen(INGRESS, {"X-Forwarded-Proto": "https"}, scope_type="websocket") == (
        (INGRESS, 5000),
        "wss",
    )


@pytest.mark.settings(
    trusted_proxies=["10.0.0.0/8"],
    oidc_issuer=None,
    break_glass_enabled=True,
    break_glass_username="admin",
    break_glass_password="correct horse battery staple",
)
async def test_a_client_behind_the_ingress_cannot_dodge_the_break_glass_throttle(
    app: FastAPI, db_session: AsyncSession
) -> None:
    """The review's proof: rotating X-Forwarded-For from a private-range client gave
    unlimited break-glass attempts (and audit rows) behind the default Helm values."""
    transport = httpx.ASGITransport(app=app, client=(INGRESS, 1234))

    async def post(forwarded_for: str, password: str) -> int:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            response = await http.post(
                "/api/v1/auth/break-glass",
                json={"username": "admin", "password": password},
                headers={"X-Forwarded-For": forwarded_for},
            )
            return response.status_code

    statuses = [await post(f"10.66.0.{n}, 10.1.2.3", "wrong") for n in range(8)]
    other_client = await post("10.66.0.99, 10.1.2.4", "correct horse battery staple")

    assert statuses == [401] * 5 + [429] * 3
    assert other_client == 200  # someone else behind the same ingress
    reasons = [
        e.details["reason"] for e in await audit_entries(db_session, "session.sign_in_denied")
    ]
    assert reasons == ["invalid_credentials"] * 5 + ["too_many_attempts"]
