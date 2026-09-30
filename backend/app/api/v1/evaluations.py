"""Evaluations of an idea: everyone's (blind-filtered) and my own."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.db import SessionDep
from app.schemas.evaluations import EvaluationList, MyEvaluation, MyEvaluationIn
from app.services import evaluations, ideas

router = APIRouter(prefix="/ideas/{idea}/evaluations", tags=["evaluations"])


@router.get(
    "",
    operation_id="list_evaluations",
    summary="List submitted evaluations",
    description=(
        "Blind: empty with score_hidden true while you are an assigned evaluator who "
        "has not submitted. Otherwise every submitted evaluation. Never drafts."
    ),
    responses=problems(401, 404),
)
async def list_evaluations(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> EvaluationList:
    loaded = await ideas.load_idea(session, principal, idea)
    return await evaluations.list_evaluations(session, principal, loaded)


@router.get(
    "/me",
    operation_id="get_my_evaluation",
    summary="Get my evaluation",
    description="The evaluate sheet's state; null if you are not an evaluator of this idea.",
    responses=problems(401, 404),
)
async def get_my_evaluation(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam
) -> MyEvaluation | None:
    loaded = await ideas.load_idea(session, principal, idea)
    return await evaluations.my_evaluation(session, principal, loaded)


@router.put(
    "/me",
    operation_id="save_my_evaluation",
    summary="Save or submit my evaluation",
    description=(
        "Replaces your saved evaluation. 403 unless you are an assigned evaluator "
        "with role member/admin. 409 evaluation_closed unless evaluation is open. "
        "409 evaluation_already_submitted for submit=false after submitting. "
        "422 evaluation_incomplete (errors list what is missing). "
        "422 unknown_criterion for a criterion outside the active rubric."
    ),
    responses=problems(401, 403, 404, 409, 422),
)
async def save_my_evaluation(
    principal: PrincipalDep, session: SessionDep, idea: IdeaParam, body: MyEvaluationIn
) -> MyEvaluation:
    # The idea row lock serialises submissions, so each aggregate recompute sees the
    # evaluations committed before it.
    loaded = await ideas.load_idea(session, principal, idea, for_update=True)
    return await evaluations.save_my_evaluation(session, principal, loaded, body)
