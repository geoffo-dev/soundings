"""The problems bid evaluation answers with (contract-phase10 section 15), one place for
their codes and wording. Details are shown to people: plain words, no internals."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from app.errors import ConflictProblem, ProblemError
from app.schemas.common import FieldError

__all__ = [
    "assessor_not_eligible",
    "conflict",
    "unknown_section",
    "unprocessable",
]

_DETAILS: dict[str, str] = {
    "bid_call_exists": "This idea already has a call for bids.",
    "bid_call_not_available": (
        "A call for bids starts from an idea in Proposal that has a proposal."
    ),
    "bid_call_finished": "The call is awarded or cancelled, so it is read-only.",
    "bid_call_not_open": "That can only be done while the call is a draft or open.",
    "bid_call_not_assessing": "That can only be done while the call is being assessed.",
    "bid_call_not_assessable": "The AI assesses bids while the call is open or being assessed.",
    "invalid_bid_call_transition": "The call can't move to that status from where it is.",
    "bid_call_template_locked": (
        "Someone has submitted an assessment, so the call's template can't change any more."
    ),
    "assessments_submitted": (
        "Assessments have been submitted, so the call can't be opened to new bids again."
    ),
    "bid_call_deadline_required": "An open call needs a deadline.",
    "bid_rejected": "The bid is rejected (reinstate it first).",
    "bid_not_qualified": "Only a bid that meets every must-have can be awarded.",
    "document_missing": "Upload and link the document before marking it met.",
    "price_not_asked": "This call has no price question, so bids take no price.",
    "too_many_bids": "A call holds at most 50 bids.",
    "assessment_incomplete": "Score every question before you submit.",
    "unknown_question": "That question isn't in this section of the call.",
    "not_assessable": "That question isn't scored by assessors.",
    "unknown_template_item": "That item isn't part of this call's template.",
    "assessor_has_submitted": (
        "They have submitted an assessment of that section, so they stay its assessor."
    ),
    "cannot_remove_self": (
        "You still owe assessments of that section: submit them, or ask another call "
        "manager to remove you."
    ),
    "not_section_assessor": "You don't assess that section of this call for bids.",
    # Documents (contract-phase10 section 6).
    "invalid_must_have": (
        "Link the file to a required-document must-have of this call; a pricing must-have's "
        "files stay pricing documents."
    ),
    "too_many_documents": "A bid holds at most 30 documents.",
    "call_storage_full": (
        "This call's documents (with their text) have reached 500 MiB: delete some first."
    ),
    "project_storage_full": (
        "This project's bid documents (with their text) have reached 5 GiB: delete some first."
    ),
    "duplicate_document": "This file is already on the bid.",
}


def conflict(code: str) -> ProblemError:
    """409 with ``code``'s wording."""
    return ConflictProblem(_DETAILS[code], code=code)


def unprocessable(code: str, *, loc: Sequence[str | int] | None = None) -> ProblemError:
    """422 with ``code``'s wording (and the field, when one is to blame)."""
    errors = None
    if loc is not None:
        errors = [FieldError(loc=list(loc), msg=_DETAILS[code], type=code)]
    return ProblemError(422, code, detail=_DETAILS[code], errors=errors)


def forbidden(code: str) -> ProblemError:
    """403 with ``code``'s wording."""
    return ProblemError(403, code, detail=_DETAILS[code])


def unknown_section(loc: Sequence[str | int]) -> ProblemError:
    """422 ``unknown_section``: a section of another call, or one left out."""
    detail = "Every section of the call, and only its sections, once each."
    return ProblemError(
        422,
        "unknown_section",
        detail=detail,
        errors=[FieldError(loc=list(loc), msg=detail, type="unknown_section")],
    )


def assessor_not_eligible(user_id: UUID, loc: Sequence[str | int]) -> ProblemError:
    """422 ``assessor_not_eligible`` naming the person (c28): an active person who can view
    the idea in their own right, never an AI agent or the break-glass account."""
    detail = (
        f"User {user_id} can't assess bids here: assessors are active people who can see "
        "the idea themselves (in a private project, add them as members first)."
    )
    return ProblemError(
        422,
        "assessor_not_eligible",
        detail=detail,
        errors=[FieldError(loc=list(loc), msg=detail, type="assessor_not_eligible")],
    )
