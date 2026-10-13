"""The small pieces of Phase 10's bid evaluation that other schemas name (an idea's call
summary, a call, section or bid reference, progress counts), apart from
:mod:`app.schemas.bids` so that ``ideas``, ``notifications`` and ``activity`` can use them
without importing the AI schemas (which import ``ideas``). :mod:`app.schemas.bids`
re-exports them. None of them carries score data, prices, contacts or reasons."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.models.enums import BidCallStatus, BidStatus
from app.schemas.base import ResponseModel

__all__ = ["BidCallRef", "BidCallSummary", "BidProgress", "BidRef", "BidSectionRef"]


class BidProgress(ResponseModel):
    """Assessments submitted / expected (``n of m assessed``). Never scores."""

    submitted: int
    total: int


class BidCallRef(ResponseModel):
    """Enough to name and link a call (``/ideas/{key}?tab=bids``)."""

    id: UUID
    title: str
    status: BidCallStatus


class BidCallSummary(BidCallRef):
    """What everyone who can view the idea sees of its call (``bid.view_call``): that it
    exists, its title, status, deadline and number of bids. No bidders, documents, prices,
    scores or reasons. Null for a guest researcher (role matrix column R)."""

    deadline_at: datetime | None
    bid_count: int = Field(description="Bids entered (rejected ones included).")


class BidSectionRef(ResponseModel):
    id: UUID
    title: str


class BidRef(ResponseModel):
    id: UUID
    bidder: str = Field(description="The bidder organisation, as the team entered it.")
    status: BidStatus
