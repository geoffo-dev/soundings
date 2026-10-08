"""The research step (Phase 8, product owner 2026-10-07; contract-phase8 section 3):
project settings -> Research, an idea's Research panel and its "Similar ideas".

Rules: reading the settings is ``project.view``; changing them is
``project.edit_research`` (project and platform admins, session only). Reading an idea's
research and similar ideas is ``idea.view`` (no score data: pending evaluators see them
too); answering and clearing items is ``idea.answer_research`` (the owner and admins; c5;
an idea write: 409 ``project_archived``, ``awaiting_moderation``); a key needs ``write``
and an AI agent's key never answers (c22: REST is refused to agents). Order of checks: 401
-> 404 (the project or idea; an item that isn't active in the idea's project) -> 403 ->
422 -> 409.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.projects import ProjectSlug
from app.api.v1.responses import problems
from app.authz import Rule, load_project
from app.db import SessionDep
from app.errors import PROBLEM_CONTENT_TYPE
from app.schemas.ideas import SimilarIdeas
from app.schemas.research import (
    IdeaResearch,
    ResearchAnswerIn,
    ResearchSettings,
    ResearchSettingsUpdate,
)
from app.services import ideas, research

router = APIRouter(tags=["research"])

ItemId = Annotated[UUID, Path(description="An active item of the project's research checklist.")]

_STEP_CONFLICT: dict[int | str, dict[str, Any]] = {
    409: {
        "description": (
            "ideas_in_research (with idea_count): the step can't be turned off or moved "
            "while ideas are in Research"
        ),
        "content": {
            PROBLEM_CONTENT_TYPE: {
                "schema": {"$ref": "#/components/schemas/IdeasInResearchProblem"}
            }
        },
    }
}
_ANSWER_ERRORS = (
    " 404 when the item isn't an active item of the idea's project's checklist; 409 "
    "research_step_off while the project's step is off, idea_closed (c5), project_archived, "
    "awaiting_moderation."
)


# --- Project settings -> Research ----------------------------------------------------
@router.get(
    "/projects/{slug}/research",
    operation_id="get_research_settings",
    summary="The project's research step and checklist",
    description=(
        "project.view: the step (off, before_evaluation, before_proposal), the active "
        "checklist in order, removed items that hold answers, the default checklist to "
        "start from, and how many ideas are in Research."
    ),
    responses=problems(401, 404),
)
async def get_research_settings(
    principal: PrincipalDep, session: SessionDep, slug: ProjectSlug
) -> ResearchSettings:
    project, _ = await load_project(session, principal, slug)
    return await research.settings_out(session, project)


@router.put(
    "/projects/{slug}/research",
    operation_id="replace_research_settings",
    summary="Set the research step and checklist",
    description=(
        "project.edit_research (project and platform admins, session only): the step and, "
        "while it is on, the complete checklist in order (1-10 items; with the step off, "
        "items is ignored and the checklist is kept, hidden). Existing items by id (a "
        "removed item's id restores it with its answers); items left out are archived if "
        "answered, else deleted. Last write wins (no version), like the rubric. Changing "
        "the checklist never moves an idea. "
        "Changing the step (off, or the other position) while ideas are in Research: 409 "
        "ideas_in_research with idea_count. 422 unknown_research_item; validation_error for "
        "duplicate titles or ids, or no item while on. Audited as "
        "project.research_step_change and project.research_checklist_replace (each when "
        "it changed)."
    ),
    responses={**problems(401, 403, 404, 422), **_STEP_CONFLICT},
)
async def replace_research_settings(
    principal: PrincipalDep, session: SessionDep, slug: ProjectSlug, body: ResearchSettingsUpdate
) -> ResearchSettings:
    project, _ = await load_project(
        session, principal, slug, Rule.PROJECT_EDIT_RESEARCH, for_update=True
    )
    return await research.replace_settings(session, principal, project, body)


# --- An idea's research ----------------------------------------------------------------
@router.get(
    "/ideas/{idea}/research",
    operation_id="get_idea_research",
    summary="The idea's research checklist",
    description=(
        "idea.view: the checklist with this idea's answers, progress, whether the gate "
        "blocks moving past Research (never for a closed idea), and what you may do. While "
        "the project's step is off: step off and no items. No score data."
    ),
    responses=problems(401, 404),
)
async def get_idea_research(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> IdeaResearch:
    loaded = await ideas.load_idea(session, principal, idea)
    return await research.idea_research(
        session, principal, loaded.idea, loaded.project, loaded.resource
    )


@router.put(
    "/ideas/{idea}/research/items/{item_id}",
    operation_id="answer_research_item",
    summary="Answer a research item",
    description=(
        "idea.answer_research (the owner and admins; c5): the item's answer (plain text, "
        "1-2,000 characters with at least one visible character; invisible characters "
        "such as zero-width spaces and bidi controls are removed), replacing any earlier "
        "one (last write wins; the first "
        "answer's author and time are kept, the editor's recorded). Returns the whole "
        "panel." + _ANSWER_ERRORS
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def answer_research_item(
    principal: PrincipalDep,
    session: SessionDep,
    idea: IdeaParam,
    item_id: ItemId,
    body: ResearchAnswerIn,
) -> IdeaResearch:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await research.answer_item(
        session, principal, loaded.idea, loaded.project, loaded.resource, item_id, body
    )
    return await research.idea_research(
        session, principal, loaded.idea, loaded.project, loaded.resource
    )


@router.delete(
    "/ideas/{idea}/research/items/{item_id}",
    operation_id="clear_research_item",
    summary="Clear a research item's answer",
    description=(
        "idea.answer_research (the owner and admins; c5): delete the item's answer "
        "(idempotent: an unanswered item stays unanswered). Clearing never moves the idea. "
        "Once the idea is past Research (in a status after it), a required item's answer "
        "is kept: 409 research_answer_required (edit it instead; Phase 8 review M1). "
        "Returns the whole panel." + _ANSWER_ERRORS
    ),
    responses=problems(401, 403, 404, 409),
)
async def clear_research_item(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, item_id: ItemId
) -> IdeaResearch:
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    await research.clear_item(
        session, principal, loaded.idea, loaded.project, loaded.resource, item_id
    )
    return await research.idea_research(
        session, principal, loaded.idea, loaded.project, loaded.resource
    )


@router.get(
    "/ideas/{idea}/similar-ideas",
    operation_id="list_similar_ideas",
    summary="Similar ideas",
    description=(
        "idea.view: up to 5 ideas whose title or summary is like this idea's (pg_trgm "
        "similarity >= 0.3, the higher of title and summary), most similar first, from "
        "every project you can view (archived ones included); never this idea or a held "
        "idea; a key's project restriction applies. No score data."
    ),
    responses=problems(401, 404),
)
async def list_similar_ideas(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> SimilarIdeas:
    loaded = await ideas.load_idea(session, principal, idea)
    return await research.similar_ideas(session, principal, loaded.idea)
