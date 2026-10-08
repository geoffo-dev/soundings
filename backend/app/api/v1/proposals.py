"""Proposals: the Proposal tab of an idea (SPEC section 5, screen 5).

One proposal per idea over its project's template (Phase 8: per project, contract-phase8
section 2), edited section by section with optimistic concurrency, margin comment threads
per section, and PDF / Markdown export. Business rules: docs/api/contract-phase4.md
sections 3.1-3.4; rules ``proposal.*`` (role matrix section E).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Request, status
from fastapi.responses import JSONResponse, Response

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.research_gate import GATE_DESCRIPTION, research_gate_conflict
from app.api.v1.responses import binary, problems
from app.config import Settings
from app.db import SessionDep
from app.errors import PROBLEM_CONTENT_TYPE, PROBLEM_TYPE_PREFIX
from app.models.base import utcnow
from app.models.proposal import SECTION_KEY_MAX_LENGTH, SECTION_KEY_PATTERN
from app.observability import request_id_var
from app.proposals import comments, export, service
from app.schemas.proposals import (
    ProposalCommentCreate,
    ProposalConflictProblem,
    ProposalSection,
    ProposalSectionUpdate,
    ProposalStart,
    ProposalThread,
    ProposalThreadCreate,
    ProposalThreadList,
    ProposalView,
)
from app.services import ideas

router = APIRouter(tags=["proposals"])

SectionKeyParam = Annotated[
    str,
    Path(
        min_length=1,
        max_length=SECTION_KEY_MAX_LENGTH,
        pattern=SECTION_KEY_PATTERN,
        description=(
            "A section of the project's template, by key (Phase 8: per project; a key the "
            "template doesn't have, or a removed section's, is 404)."
        ),
    ),
]
ThreadId = Annotated[UUID, Path(description="A margin thread's id.")]
CommentId = Annotated[UUID, Path(description="A comment's id (in that thread).")]

_SECTION_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {
        "description": (
            "Conflicts with the current state: proposal_conflict (with current: the "
            "section as saved now), proposal_not_available, project_archived, "
            "awaiting_moderation"
        ),
        "content": {
            PROBLEM_CONTENT_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProposalConflictProblem"}
            }
        },
    }
}


def _conflict(request: Request, current: ProposalSection) -> JSONResponse:
    """409 ``proposal_conflict`` with the section as saved now (``current`` keeps its
    nulls, unlike the other fields of a problem)."""
    problem = ProposalConflictProblem(
        type=PROBLEM_TYPE_PREFIX + "proposal_conflict",
        title="Conflict",
        status=409,
        detail="Someone else changed this section since you started editing it.",
        instance=request.url.path,
        code="proposal_conflict",
        request_id=request_id_var.get(),
    )
    body = problem.model_dump(mode="json", exclude_none=True)
    body["current"] = current.model_dump(mode="json")
    return JSONResponse(body, status_code=409, media_type=PROBLEM_CONTENT_TYPE)


_DOWNLOAD_HEADERS = {
    "Content-Disposition": 'attachment; filename="<KEY>-proposal.<ext>" (e.g. CUST-12).',
}


@router.get(
    "/ideas/{idea}/proposal",
    operation_id="get_proposal",
    summary="The Proposal tab",
    description=(
        "proposal.view. The proposal (null until the owner starts one) and what you may do. "
        "Carries no score data."
    ),
    responses=problems(401, 404),
)
async def get_proposal(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> ProposalView:
    loaded = await ideas.load_idea(session, principal, idea)
    return await service.proposal_view(session, principal, loaded)


@router.post(
    "/ideas/{idea}/proposal",
    operation_id="create_proposal",
    status_code=status.HTTP_201_CREATED,
    summary="Start the proposal",
    description=(
        "proposal.write (owner, project and platform admins) while the idea is Shortlisted "
        "or in Proposal (c7, else 409 proposal_not_available; Phase 8: also in Research when "
        "the project's research step is before_proposal). Creates a section for each active "
        "section of the project's template (a summary section starts as the idea's summary) "
        "and moves a Shortlisted (or Research) idea to Proposal (a status change like any "
        "other: feed, notifications, audit). 409 proposal_exists when there already is one. "
        "The body is optional (ProposalStart: the research override)." + GATE_DESCRIPTION
    ),
    responses={
        **problems(401, 403, 404, 422),
        **research_gate_conflict(
            "proposal_not_available, proposal_exists, project_archived, awaiting_moderation"
        ),
    },
)
async def create_proposal(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    body: ProposalStart | None = None,
) -> ProposalView:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await service.create_proposal(session, principal, loaded, body)
    return await service.proposal_view(session, principal, loaded)


@router.put(
    "/ideas/{idea}/proposal/sections/{section_key}",
    operation_id="update_proposal_section",
    summary="Save a section",
    description=(
        "proposal.write (c7). Optimistic concurrency per section: base_version must be the "
        "section's current version, else 409 proposal_conflict whose current is the "
        "section as saved now (someone saved it since). Identical text changes nothing "
        "(same version). The text is kept verbatim (no trimming). 404 when there is no "
        "proposal."
    ),
    response_model=ProposalSection,
    responses={**problems(401, 403, 404, 422), **_SECTION_CONFLICT},
)
async def update_proposal_section(
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    section_key: SectionKeyParam,
    body: ProposalSectionUpdate,
) -> ProposalSection | JSONResponse:
    loaded = await service.load_idea_shared(session, principal, idea)
    try:
        return await service.update_section(session, principal, loaded, section_key, body)
    except service.SectionConflict as conflict:
        return _conflict(request, conflict.current)


@router.get(
    "/ideas/{idea}/proposal/markdown",
    operation_id="export_proposal_markdown",
    response_class=Response,
    summary="Export as Markdown",
    description=(
        "proposal.export: a text/markdown download (title, metadata, the project's template "
        'sections; the aggregate score only if you may see it; Phase 8: a closing "Research '
        "and consultation\" appendix of the answered checklist items while the project's "
        "research step is on). Shares the export limit with PDF (429 too_many_attempts with "
        "Retry-After). 404 when there is no proposal."
    ),
    responses={
        **binary(
            200, "The proposal as Markdown (UTF-8).", "text/markdown", headers=_DOWNLOAD_HEADERS
        ),
        **problems(401, 404, 429),
    },
)
async def export_proposal_markdown(
    request: Request, principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> Response:
    settings: Settings = request.app.state.settings
    loaded = await ideas.load_idea(session, principal, idea)
    document = await export.export_document(
        session, principal, loaded, settings, request.app, now=utcnow()
    )
    return await export.markdown_response(document)


@router.get(
    "/ideas/{idea}/proposal/pdf",
    operation_id="export_proposal_pdf",
    response_class=Response,
    summary="Export as PDF",
    description=(
        "proposal.export: an application/pdf download in the project's effective branding "
        "(cover with logo or app name, colours and font; page numbers; the project's "
        'template sections, then Phase 8\'s "Research and consultation" appendix while the '
        "research step is on), rendered in a "
        "separate process without any remote resource. 429 too_many_attempts (with "
        "Retry-After) beyond the export limit; 503 export_busy (with Retry-After) when "
        "the renderer stayed busy for 30 s or a render hit its 20 s limit. 404 when "
        "there is no proposal."
    ),
    responses={
        **binary(200, "The proposal as a PDF.", "application/pdf", headers=_DOWNLOAD_HEADERS),
        **problems(401, 404, 429, 503),
    },
)
async def export_proposal_pdf(
    request: Request, principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> Response:
    settings: Settings = request.app.state.settings
    loaded = await ideas.load_idea(session, principal, idea)
    document = await export.export_document(
        session, principal, loaded, settings, request.app, now=utcnow()
    )
    # Nothing to write: end the transaction before the (slow) render.
    await session.commit()
    return await export.pdf_response(request.app.state, document, loaded.idea.id)


@router.get(
    "/ideas/{idea}/proposal/threads",
    operation_id="list_proposal_threads",
    summary="Margin comment threads",
    description=(
        "proposal.view: every thread with at least one comment that isn't deleted, by "
        "section in template order, then oldest first. 404 when there is no proposal."
    ),
    responses=problems(401, 404),
)
async def list_proposal_threads(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> ProposalThreadList:
    loaded = await ideas.load_idea(session, principal, idea)
    return await comments.list_threads(session, principal, loaded)


@router.post(
    "/ideas/{idea}/proposal/threads",
    operation_id="create_proposal_thread",
    status_code=status.HTTP_201_CREATED,
    summary="Comment on a section",
    description=(
        "proposal.comment (members and admins): opens a thread on a section with its first "
        "comment. 409 too_many_comments beyond 500 threads. 404 when there is no proposal."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def create_proposal_thread(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: ProposalThreadCreate
) -> ProposalThread:
    loaded = await service.load_idea_shared(session, principal, idea)
    return await comments.create_thread(session, principal, loaded, body)


@router.post(
    "/ideas/{idea}/proposal/threads/{thread_id}/comments",
    operation_id="reply_to_proposal_thread",
    status_code=status.HTTP_201_CREATED,
    summary="Reply in a thread",
    description=(
        "proposal.comment. Replies are flat; replying to a resolved thread reopens it. "
        "409 too_many_comments beyond 200 comments in a thread."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def reply_to_proposal_thread(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    thread_id: ThreadId,
    body: ProposalCommentCreate,
) -> ProposalThread:
    loaded = await service.load_idea_shared(session, principal, idea)
    return await comments.reply(session, principal, loaded, thread_id, body)


@router.put(
    "/ideas/{idea}/proposal/threads/{thread_id}/resolved",
    operation_id="resolve_proposal_thread",
    summary="Resolve a thread",
    description="proposal.comment. Idempotent; the thread collapses.",
    responses=problems(401, 403, 404, 409),
)
async def resolve_proposal_thread(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, thread_id: ThreadId
) -> ProposalThread:
    loaded = await service.load_idea_shared(session, principal, idea)
    return await comments.set_resolved(session, principal, loaded, thread_id, resolved=True)


@router.delete(
    "/ideas/{idea}/proposal/threads/{thread_id}/resolved",
    operation_id="reopen_proposal_thread",
    summary="Reopen a thread",
    description="proposal.comment. Idempotent.",
    responses=problems(401, 403, 404, 409),
)
async def reopen_proposal_thread(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, thread_id: ThreadId
) -> ProposalThread:
    loaded = await service.load_idea_shared(session, principal, idea)
    return await comments.set_resolved(session, principal, loaded, thread_id, resolved=False)


@router.delete(
    "/ideas/{idea}/proposal/threads/{thread_id}/comments/{comment_id}",
    operation_id="delete_proposal_comment",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a margin comment",
    description=(
        "Your own (comment.edit_own: 403 not_author otherwise) or anyone's as a project "
        "admin (comment.delete_any). Leaves a stub; a thread with only deleted comments "
        "disappears. Idempotent."
    ),
    responses=problems(401, 403, 404, 409),
)
async def delete_proposal_comment(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    thread_id: ThreadId,
    comment_id: CommentId,
) -> None:
    loaded = await service.load_idea_shared(session, principal, idea)
    await comments.delete_comment(session, principal, loaded, thread_id, comment_id)
