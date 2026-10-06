"""AI runs on an idea: "Ask AI to evaluate", "Research this", "Draft section", their
progress (live over SSE, or by polling), cancel; including an AI evaluation in the
aggregate; deleting a research note (SPEC section 9; contract-phase6 sections 2 and 3).

Rules (role matrix section J): ``ai.request_evaluation`` (c6, c10), ``ai.research`` (c5,
c10), ``ai.draft_section`` (c7, c10): the owner and project/platform admins;
``ai.cancel_run``: the same people; watching runs needs only ``idea.view`` (events carry
no score data). ``evaluation.include_ai``: the owner and admins. Order of checks: 401 ->
404 (the idea, also for the section draft without a proposal) -> 403 -> 422 -> 409
(c5/c6/c7, ``project_archived``, ``awaiting_moderation``, then c10 ``ai_unavailable``)
-> 429.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Response, status

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.models.enums import AiRunKind
from app.schemas.ai import (
    AI_RUN_LIST_DEFAULT,
    AI_RUN_LIST_MAX,
    AiRun,
    AiRunDetail,
    AiRunList,
    AiRunRequest,
    AiSectionDraftRequest,
    EvaluationInclusionUpdate,
    ResearchNote,
)
from app.schemas.evaluations import Evaluation

router = APIRouter(prefix="/ideas/{idea}", tags=["ai"])

RunId = Annotated[UUID, Path(description="An AI run's id (on this idea).")]
EvaluationId = Annotated[UUID, Path(description="A submitted evaluation's id (on this idea).")]
NoteId = Annotated[UUID, Path(description="A research note's id (its activity item id).")]

_CREATED_OR_EXISTING: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "The same request is already active (queued or running) for this idea, agent "
            "and kind (and section): that run, unchanged (idempotent)."
        ),
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AiRun"}}},
    }
}
_REQUEST_ERRORS = (
    " 409 ai_unavailable (c10: AI is off, or the agent isn't enabled, doesn't serve this "
    "project with a member role and a usable key, or lacks the purpose), project_archived, "
    "awaiting_moderation; 429 too_many_attempts (20 runs an hour per person, with "
    "Retry-After). Audited as ai_run.request."
)


@router.get(
    "/ai-runs",
    operation_id="list_idea_ai_runs",
    summary="AI runs on an idea",
    description=(
        "idea.view: the idea's AI runs, newest first, with the agents you may ask here (c10) "
        "and what you may do (ai.request_evaluation, ai.research, ai.draft_section, "
        "ai.cancel_run, evaluation.include_ai). Runs never carry score data."
    ),
    responses=problems(401, 404),
)
async def list_idea_ai_runs(
    principal: PrincipalDep,
    idea: IdeaParam,
    kind: Annotated[AiRunKind | None, Query(description="Only runs of this kind.")] = None,
    limit: Annotated[int, Query(ge=1, le=AI_RUN_LIST_MAX)] = AI_RUN_LIST_DEFAULT,
) -> AiRunList:
    raise NotImplementedProblem


@router.post(
    "/ai-runs/evaluation",
    operation_id="request_ai_evaluation",
    status_code=status.HTTP_201_CREATED,
    summary="Ask AI to evaluate",
    description=(
        "ai.request_evaluation (the owner and admins; c6: evaluation open). Assigns the "
        "agent's service account as an evaluator if it isn't one (audited evaluator.add, "
        "activity evaluator_added) and queues a run: the agent reads the idea and the "
        "rubric through MCP and submits an evaluation with a rationale and sources per "
        "criterion, shown with an AI badge and left out of the aggregate until someone "
        "includes it. 201 with the new run, or 200 with the active one." + _REQUEST_ERRORS
    ),
    responses={**_CREATED_OR_EXISTING, **problems(401, 403, 404, 409, 422, 429)},
)
async def request_ai_evaluation(
    principal: PrincipalDep, idea: IdeaParam, body: AiRunRequest
) -> AiRun:
    raise NotImplementedProblem


@router.post(
    "/ai-runs/research",
    operation_id="request_ai_research",
    status_code=status.HTTP_201_CREATED,
    summary="Research this",
    description=(
        "ai.research (the owner and admins; c5: the idea isn't closed). Queues a run: the "
        "agent reads the idea through MCP and writes one cited research note into the "
        "activity feed (add_research_note). 201 with the new run, or 200 with the active one."
        + _REQUEST_ERRORS
    ),
    responses={**_CREATED_OR_EXISTING, **problems(401, 403, 404, 409, 422, 429)},
)
async def request_ai_research(
    principal: PrincipalDep, idea: IdeaParam, body: AiRunRequest
) -> AiRun:
    raise NotImplementedProblem


@router.post(
    "/ai-runs/section-draft",
    operation_id="request_ai_section_draft",
    status_code=status.HTTP_201_CREATED,
    summary="Draft a proposal section with AI",
    description=(
        "ai.draft_section (the owner and admins; c7: Shortlisted or Proposal). 404 when the "
        "idea has no proposal yet. Queues a run: the agent reads the idea and the proposal "
        "and suggests the whole text of the section (propose_proposal_section, source ai), "
        "which the owner accepts or discards. 201 with the new run, or 200 with the active "
        "one for the same section." + _REQUEST_ERRORS
    ),
    responses={**_CREATED_OR_EXISTING, **problems(401, 403, 404, 409, 422, 429)},
)
async def request_ai_section_draft(
    principal: PrincipalDep, idea: IdeaParam, body: AiSectionDraftRequest
) -> AiRun:
    raise NotImplementedProblem


@router.get(
    "/ai-runs/{run_id}",
    operation_id="get_ai_run",
    summary="An AI run with its events",
    description=(
        "idea.view: the run and every event so far (oldest first): the polling fallback "
        "of the event stream (every 2-3 seconds while it is active)."
    ),
    responses=problems(401, 404),
)
async def get_ai_run(principal: PrincipalDep, idea: IdeaParam, run_id: RunId) -> AiRunDetail:
    raise NotImplementedProblem


@router.post(
    "/ai-runs/{run_id}/cancel",
    operation_id="cancel_ai_run",
    summary="Cancel an AI run",
    description=(
        "ai.cancel_run (the owner and admins). A queued run is cancelled at once; a running "
        "one is marked cancel_requested and the worker asks the agent to cancel (A2A "
        "tasks/cancel) within a few seconds, then it ends cancelled. Idempotent while "
        "active. 409 ai_run_finished for a run that already ended. Audited as ai_run.cancel."
    ),
    responses=problems(401, 403, 404, 409),
)
async def cancel_ai_run(principal: PrincipalDep, idea: IdeaParam, run_id: RunId) -> AiRun:
    raise NotImplementedProblem


@router.get(
    "/ai-runs/{run_id}/events",
    operation_id="stream_ai_run_events",
    response_class=Response,
    summary="Live AI run progress (SSE)",
    description=(
        "idea.view: a text/event-stream of the run's events after Last-Event-ID (or "
        "after), then live ones until the run ends. Each event: 'id: <seq>' and 'data: "
        "<AiRunEvent JSON>' (no event name); 'retry: 3000' first; ': keep-alive' comments "
        "every 15 seconds; the stream ends after the final event (final true) and after 10 "
        "minutes (reconnect with Last-Event-ID). A run already over with nothing new: 204 "
        "(EventSource stops). Events carry no score data, so pending evaluators may watch. "
        "The principal and idea.view are re-checked every 30 seconds. 5 open streams per "
        "person (429 too_many_attempts). Doesn't keep a session alive."
    ),
    responses={
        200: {
            "description": "The event stream (text/event-stream; data: AiRunEvent as JSON).",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
            "headers": {
                "Cache-Control": {"description": "no-cache", "schema": {"type": "string"}},
                "X-Accel-Buffering": {
                    "description": "no (proxies must not buffer the stream)",
                    "schema": {"type": "string"},
                },
            },
        },
        204: {"description": "The run is over and the client has every event."},
        **problems(401, 404, 429),
    },
)
async def stream_ai_run_events(
    principal: PrincipalDep,
    idea: IdeaParam,
    run_id: RunId,
    last_event_id: Annotated[
        int | None,
        Header(
            alias="Last-Event-ID",
            ge=0,
            le=1_000_000,
            description="Sent by EventSource when it reconnects: replay events after it.",
        ),
    ] = None,
    after: Annotated[
        int | None,
        Query(ge=0, le=1_000_000, description="Replay events after this seq (header wins)."),
    ] = None,
) -> Response:
    raise NotImplementedProblem


@router.put(
    "/evaluations/{evaluation_id}/include-in-aggregate",
    operation_id="set_evaluation_inclusion",
    summary="Include an AI evaluation in the score",
    description=(
        "evaluation.include_ai (the owner and admins). Counts a submitted AI evaluation in "
        "the aggregate (include true) or leaves it out again (false, the default); returns "
        "it. 404 for an evaluation you can't see (a draft, another idea's, or any while you "
        "are a pending evaluator: blind evaluation). 409 not_ai_evaluation for a person's "
        "evaluation (always counted), project_archived, awaiting_moderation. Idempotent. "
        "Audited as evaluation.include_ai."
    ),
    responses=problems(401, 403, 404, 409),
)
async def set_evaluation_inclusion(
    principal: PrincipalDep,
    idea: IdeaParam,
    evaluation_id: EvaluationId,
    body: EvaluationInclusionUpdate,
) -> Evaluation:
    raise NotImplementedProblem


@router.get(
    "/research-notes/{note_id}",
    operation_id="get_research_note",
    summary="A research note",
    description=(
        "idea.view: one AI research note (Markdown and cited sources, untrusted: render it "
        "sanitised, with an AI label and the sources as plain links). The activity feed "
        "embeds the same object (ai_research_note items, from integration). Holds no score "
        "data. 404 for an unknown note or one on another idea."
    ),
    responses=problems(401, 404),
)
async def get_research_note(
    principal: PrincipalDep, idea: IdeaParam, note_id: NoteId
) -> ResearchNote:
    raise NotImplementedProblem


@router.delete(
    "/research-notes/{note_id}",
    operation_id="delete_research_note",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a research note",
    description=(
        "comment.delete_any (project and platform admins): removes an AI research note's "
        "text and sources; the feed shows that a note was deleted. Idempotent. 409 "
        "project_archived."
    ),
    responses=problems(401, 403, 404, 409),
)
async def delete_research_note(principal: PrincipalDep, idea: IdeaParam, note_id: NoteId) -> None:
    raise NotImplementedProblem
