"""Per-client-IP throttles for the public sign-in endpoints (contract-phase2 sections
3.2 and 3.8).

In-process sliding windows: simple, no table or job, and enough for what they guard.
``GET /auth/login`` (60 starts a minute; it stores nothing, but each start mints a
sealed cookie and an IdP redirect) and break-glass failures (5 per 15 minutes, against
16+ character passwords). With several API replicas the
limits multiply (contract section 6); a restart forgets them, which costs an attacker
nothing they couldn't get from a second IP address anyway.

The client IP is ``request.client``, which honours trusted proxies' ``X-Forwarded-For``
only as far as they appended to it (:func:`app.middleware.forwarded_client`), so a
client can't pick its own key. IPv6 addresses count per /64: one host usually owns a
whole /64. A client that isn't an IP address (a unix socket) shares one key.
"""

from __future__ import annotations

import ipaddress
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Final

from starlette.requests import Request

__all__ = ["BREAK_GLASS_THROTTLE", "LOGIN_THROTTLE", "Throttle", "client_key", "get_throttle"]

LOGIN_THROTTLE: Final = ("login", 60, 60.0)
"""``GET /auth/login``: 60 starts per client per minute."""

BREAK_GLASS_THROTTLE: Final = ("break_glass", 5, 15 * 60.0)
"""``POST /auth/break-glass``: 5 failed attempts per client per 15 minutes."""

MAX_KEYS: Final = 50_000
"""Clients tracked at once; beyond this the oldest are forgotten (bounded memory)."""


def client_key(request: Request) -> str:
    """The throttle key: the client IPv4 address, or its IPv6 /64; ``unknown`` for
    anything that isn't an IP address (never a value a client chose)."""
    host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "unknown"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


class Throttle:
    """At most ``limit`` hits per key in any ``window`` seconds."""

    def __init__(
        self,
        limit: int,
        window: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = MAX_KEYS,
    ) -> None:
        self.limit = limit
        self.window = window
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._refused_until: dict[str, float] = {}

    def _recent(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def retry_after(self, key: str) -> float | None:
        """Seconds until the oldest counted hit leaves the window, when the key is at
        its limit; ``None`` when another hit is allowed."""
        now = self._clock()
        hits = self._recent(key, now)
        if len(hits) < self.limit:
            return None
        return max(hits[0] + self.window - now, 0.0)

    def hit(self, key: str) -> None:
        now = self._clock()
        hits = self._recent(key, now)
        if key not in self._hits:
            if len(self._hits) >= self._max_keys:
                self._forget(now)
            self._hits[key] = hits
        hits.append(now)

    def first_refusal(self, key: str) -> bool:
        """True for the first refusal of a lockout (audit it), false for the rest of it."""
        now = self._clock()
        if self._refused_until.get(key, 0.0) > now:
            return False
        retry = self.retry_after(key) or 0.0
        if len(self._refused_until) >= self._max_keys:
            self._refused_until = {k: v for k, v in self._refused_until.items() if v > now}
        self._refused_until[key] = now + retry
        return True

    def _forget(self, now: float) -> None:
        for key in list(self._hits):
            self._recent(key, now)
        overflow = len(self._hits) - self._max_keys + 1
        for key in list(self._hits)[: max(overflow, 0)]:
            del self._hits[key]


def get_throttle(app: Any, spec: tuple[str, int, float]) -> Throttle:
    """The app's throttle for ``spec`` (created on first use, one per process)."""
    name, limit, window = spec
    throttles: dict[str, Throttle] | None = getattr(app.state, "throttles", None)
    if throttles is None:
        throttles = {}
        app.state.throttles = throttles
    if name not in throttles:
        throttles[name] = Throttle(limit, window)
    return throttles[name]
