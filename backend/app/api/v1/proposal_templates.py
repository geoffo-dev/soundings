"""A project's proposal template (Phase 8, product owner 2026-10-07; contract-phase8
section 2): project settings -> Workflow -> Proposal template.

Rules: reading is ``project.view``; replacing is ``project.edit_proposal_template``
(project and platform admins, session only). The template is live: every proposal of the
project follows it at once (the editor, margin threads, suggestions, "Draft with AI",
exports, MCP ``get_proposal`` / ``propose_proposal_section``).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.principal import PrincipalDep
from app.api.v1.projects import ProjectSlug
from app.api.v1.responses import problems
from app.db import SessionDep
from app.errors import NotImplementedProblem
from app.schemas.proposals import ProposalTemplate, ProposalTemplateUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/{slug}/proposal-template",
    operation_id="get_proposal_template",
    summary="The project's proposal template",
    description=(
        "project.view: the active sections in order (key, title, hint, how many proposals "
        "have text in each) and the removed sections that still hold something (restore "
        "one by putting its key back)."
    ),
    responses=problems(401, 404),
)
async def get_proposal_template(
    principal: PrincipalDep, session: SessionDep, slug: ProjectSlug
) -> ProposalTemplate:
    raise NotImplementedProblem


@router.put(
    "/{slug}/proposal-template",
    operation_id="replace_proposal_template",
    summary="Replace the proposal template",
    description=(
        "project.edit_proposal_template (project and platform admins, session only): the "
        "complete template, 1-12 sections in order. Existing sections by key (renaming "
        "keeps the key and the text; a removed section's key restores it with its text); "
        "new ones without a key get one made from the title. Sections left out are "
        "archived if anything refers to them, else deleted. Every proposal of the project "
        "follows it at once (missing section rows are created). Last write wins (no "
        "version), like the rubric. 422 unknown_section; validation_error for duplicate "
        "titles or keys. Audited as project.proposal_template_replace."
    ),
    responses=problems(401, 403, 404, 422),
)
async def replace_proposal_template(
    principal: PrincipalDep, session: SessionDep, slug: ProjectSlug, body: ProposalTemplateUpdate
) -> ProposalTemplate:
    raise NotImplementedProblem
