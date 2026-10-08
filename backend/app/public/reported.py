"""What a public submitter is told about their idea's status (Phase 8, contract-phase8
section 3.9).

Research is never shown: it is reported as the status before it in the project's
lifecycle (:func:`app.schemas.research.public_status`: New before evaluation, Shortlisted
before the proposal), so a move into or out of Research that changes nothing reported
adds no tracking-history row and sends no status email. Tracking and the submitter's
status emails both decide with :func:`reported_move`, with the step the move happened under
(recorded on the event since the code review's L3), so moving the step later never
rewrites the history.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.models.enums import IdeaStatus, ResearchStep, Resolution
from app.schemas.research import public_status

__all__ = ["Reported", "reported", "reported_move"]

Reported = tuple[IdeaStatus, Resolution | None]


def reported(step: ResearchStep, status: IdeaStatus, resolution: Resolution | None) -> Reported:
    """The status (and, for a closed idea, the resolution) the submitter sees."""
    return public_status(step, status), resolution if status is IdeaStatus.CLOSED else None


def _parse(status: object, resolution: object) -> Reported | None:
    try:
        return IdeaStatus(str(status)), Resolution(str(resolution)) if resolution else None
    except ValueError:
        return None


def _step_of(payload: Mapping[str, Any], current: ResearchStep) -> ResearchStep:
    """The research step the move happened under: recorded on moves into or out of
    Research (code review L3); else the project's current one (the step can't change
    while an idea is in Research, and a move without Research doesn't depend on it)."""
    try:
        return ResearchStep(str(payload["research_step"]))
    except (KeyError, ValueError):
        return current


def reported_move(step: ResearchStep, payload: Mapping[str, Any]) -> Reported | None:
    """For a ``status_changed`` payload: what the submitter is told it moved to, or
    ``None`` when the reported status and resolution don't change (or the payload can't
    be read). ``step`` is the project's current step, used only for moves that didn't
    record theirs."""
    step = _step_of(payload, step)
    before = _parse(payload.get("from_status"), payload.get("from_resolution"))
    after = _parse(payload.get("to_status"), payload.get("to_resolution"))
    if after is None:
        return None
    shown = reported(step, *after)
    if before is not None and reported(step, *before) == shown:
        return None
    return shown
