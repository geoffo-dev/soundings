"""The authenticated ``/mcp`` request, as the tools see it.

The ``/mcp`` guard authenticates every request with the API-key source (contract-phase5
section 3.5) and binds an :class:`McpRequest` for the rest of the request with
:func:`bound`; the SDK runs the handlers in tasks started from that request, which
inherit the binding (context variables are copied into new tasks), and the dispatcher
reads it with :func:`current_request`. Nothing else carries the principal: a handler
without a binding refuses to run.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from app.domain.principal import Principal

__all__ = ["McpRequest", "bound", "current_request"]


@dataclass(frozen=True, slots=True)
class McpRequest:
    """One authenticated ``/mcp`` request: the key's principal as the guard admitted it
    (its owner, narrowed by the key) and the FastAPI app (settings, session maker,
    throttles). The principal decides the request's rates and names the actor of
    refusals; a tool runs with the principal rebuilt in its own transaction
    (:mod:`app.mcp.dispatcher`), never with this snapshot."""

    app: Any
    principal: Principal


_REQUEST: ContextVar[McpRequest | None] = ContextVar("soundings_mcp_request", default=None)


@contextmanager
def bound(request: McpRequest) -> Iterator[McpRequest]:
    """Bind ``request`` for the code (and the tasks it starts) inside the block."""
    token = _REQUEST.set(request)
    try:
        yield request
    finally:
        _REQUEST.reset(token)


def current_request() -> McpRequest:
    """The request bound by the guard; ``RuntimeError`` outside one (never anonymous)."""
    request = _REQUEST.get()
    if request is None:
        raise RuntimeError("no authenticated /mcp request is bound")
    return request
