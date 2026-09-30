"""Evaluations of an idea: everyone's (blind-filtered) and my own."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.ideas import IdeaParam
from app.api.v1.principal import PrincipalDep
from app.api.v1.responses import problems
from app.errors import NotImplementedProblem
from app.schemas.evaluations import EvaluationList, MyEvaluation, MyEvaluationIn

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
async def list_evaluations(principal: PrincipalDep, idea: IdeaParam) -> EvaluationList:
    raise NotImplementedProblem


@router.get(
    "/me",
    operation_id="get_my_evaluation",
    summary="Get my evaluation",
    description="The evaluate sheet's state; null if you are not an evaluator of this idea.",
    responses=problems(401, 404),
)
async def get_my_evaluation(principal: PrincipalDep, idea: IdeaParam) -> MyEvaluation | None:
    raise NotImplementedProblem


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
    principal: PrincipalDep, idea: IdeaParam, body: MyEvaluationIn
) -> MyEvaluation:
    raise NotImplementedProblem
