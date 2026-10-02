"""Proposal suggestions: suggested text for a section, which the owner accepts or
discards in the proposal editor (SPEC section 9; contract-phase5 section 3.4).

Rules: ``proposal.view`` (list), ``proposal.suggest_section`` (create: members and
admins, c7), ``proposal.write`` (accept, discard: the owner and admins, c7). The MCP tool
``propose_proposal_section`` creates them too (``source`` ``mcp`` or ``ai``).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, status

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import PROBLEM_CONTENT_TYPE, NotImplementedProblem
from app.schemas.proposals import (
    AcceptedProposalSuggestion,
    ProposalSuggestion,
    ProposalSuggestionAccept,
    ProposalSuggestionCreate,
    ProposalSuggestionList,
)

router = APIRouter(prefix="/ideas/{idea}/proposal/suggestions", tags=["proposals"])

SuggestionId = Annotated[UUID, Path(description="A suggestion's id (on this proposal).")]

_ACCEPT_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {
        "description": (
            "Conflicts with the current state: proposal_conflict (with current: the "
            "section as saved now), suggestion_not_pending, proposal_not_available, "
            "project_archived, awaiting_moderation"
        ),
        "content": {
            PROBLEM_CONTENT_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProposalConflictProblem"}
            }
        },
    }
}


@router.get(
    "",
    operation_id="list_proposal_suggestions",
    summary="Pending suggestions",
    description=(
        "proposal.view: the proposal's pending suggestions in template-section order, then "
        "oldest first, with what you may do (suggest, decide). 404 when the idea has no "
        "proposal."
    ),
    responses=problems(401, 404),
)
async def list_proposal_suggestions(
    principal: PrincipalDep, idea: IdeaParam
) -> ProposalSuggestionList:
    raise NotImplementedProblem


@router.post(
    "",
    operation_id="create_proposal_suggestion",
    status_code=status.HTTP_201_CREATED,
    summary="Suggest text for a section",
    description=(
        "proposal.suggest_section (members and admins; c7: the idea is Shortlisted or in "
        "Proposal). The whole new text of one section; your earlier pending suggestion for "
        "the same section is discarded. source is ai for a service account, else api. 404 "
        "when the idea has no proposal; 422 validation_error for a base_version above the "
        "section's; 409 proposal_not_available, too_many_suggestions (50 pending), "
        "project_archived, awaiting_moderation."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def create_proposal_suggestion(
    principal: PrincipalDep, idea: IdeaParam, body: ProposalSuggestionCreate
) -> ProposalSuggestion:
    raise NotImplementedProblem


@router.post(
    "/{suggestion_id}/accept",
    operation_id="accept_proposal_suggestion",
    summary="Accept a suggestion",
    description=(
        "proposal.write (the owner and admins, c7). The section's text becomes the "
        "suggestion's, saved like update_proposal_section with base_version (the section "
        "version you are looking at): 409 proposal_conflict with current when someone saved "
        "it since; suggestion_not_pending when it was already accepted or discarded."
    ),
    responses={**problems(401, 403, 404, 422), **_ACCEPT_CONFLICT},
)
async def accept_proposal_suggestion(
    principal: PrincipalDep,
    idea: IdeaParam,
    suggestion_id: SuggestionId,
    body: ProposalSuggestionAccept,
) -> AcceptedProposalSuggestion:
    raise NotImplementedProblem


@router.post(
    "/{suggestion_id}/discard",
    operation_id="discard_proposal_suggestion",
    summary="Discard a suggestion",
    description=(
        "proposal.write (the owner and admins, c7), under the same locks as accept. "
        "Idempotent for a discarded suggestion; 409 suggestion_not_pending for an accepted "
        "one, proposal_not_available, project_archived, awaiting_moderation."
    ),
    responses=problems(401, 403, 404, 409),
)
async def discard_proposal_suggestion(
    principal: PrincipalDep, idea: IdeaParam, suggestion_id: SuggestionId
) -> ProposalSuggestion:
    raise NotImplementedProblem
