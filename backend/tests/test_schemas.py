"""Validation rules encoded in the API schemas, and the default rubric."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.domain.rubric_defaults import DEFAULT_RUBRIC, default_rubric_criteria
from app.models.enums import IdeaStatus, Resolution
from app.schemas.activity import ACTIVITY_TYPES, ActivityPage
from app.schemas.base import ResponseModel
from app.schemas.evaluations import MyEvaluationIn
from app.schemas.ideas import EvaluationDueDate, IdeaCreate, IdeaUpdate, StatusChange
from app.schemas.projects import DEFAULT_STATUS_LABELS, ProjectCreate, StatusLabels
from app.schemas.rubric import MAX_CRITERIA, MIN_CRITERIA, RubricCriterion, RubricUpdate
from app.schemas.users import UserRef, initials_for


@pytest.mark.parametrize(
    ("status", "resolution", "valid"),
    [
        (IdeaStatus.CLOSED, Resolution.ACCEPTED, True),
        (IdeaStatus.CLOSED, None, False),
        (IdeaStatus.SHORTLISTED, None, True),
        (IdeaStatus.NEW, Resolution.PARKED, False),
    ],
)
def test_status_change_requires_resolution_exactly_when_closing(
    status: IdeaStatus, resolution: Resolution | None, valid: bool
) -> None:
    if valid:
        StatusChange(status=status, resolution=resolution)
    else:
        with pytest.raises(ValidationError, match="resolution"):
            StatusChange(status=status, resolution=resolution)


def test_idea_tags_are_trimmed_and_deduplicated_case_insensitively() -> None:
    idea = IdeaCreate.model_validate(
        {"title": "  Refunds ", "summary": "Faster.", "tags": [" UX ", "ux", "Pricing"]}
    )

    assert idea.title == "Refunds"
    assert idea.tags == ["UX", "Pricing"]
    assert IdeaUpdate.model_validate({"tags": ["a", "A"]}).tags == ["a"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"title": "   ", "summary": "s"}, "title"),
        ({"title": "x"}, "summary"),
        ({"title": "x", "summary": "  "}, "summary"),
        ({"title": "x", "summary": "s", "tags": ["a,b"]}, "tags"),
        ({"title": "x", "summary": "s", "tags": [str(n) for n in range(11)]}, "tags"),
        ({"title": "x", "summary": "s", "unexpected": True}, "unexpected"),
    ],
)
def test_invalid_idea_is_rejected(body: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError) as caught:
        IdeaCreate.model_validate(body)
    assert caught.value.errors()[0]["loc"][0] == field


def test_idea_summary_cannot_be_cleared() -> None:
    assert IdeaUpdate.model_validate({"summary": None}).summary is None  # unchanged
    with pytest.raises(ValidationError):
        IdeaUpdate.model_validate({"summary": ""})


def test_due_date_is_replaced_explicitly() -> None:
    assert EvaluationDueDate.model_validate({"due_at": None}).due_at is None
    EvaluationDueDate.model_validate({"due_at": "2026-10-07T17:00:00+01:00"})
    for body in ({}, {"due_at": "2026-10-07T17:00:00"}):  # missing; no UTC offset
        with pytest.raises(ValidationError):
            EvaluationDueDate.model_validate(body)


@pytest.mark.parametrize(
    ("slug", "key", "valid"),
    [
        ("customer-innovation", "CUST", True),
        ("ab", "AB", True),
        ("Customer", "CUST", False),
        ("double--hyphen", "CUST", False),
        ("ok", "cust", False),
        ("ok", "C", False),
        ("ok", "TOOLONG", False),
        ("ok", "1ABC", False),
    ],
)
def test_project_slug_and_key_formats(slug: str, key: str, valid: bool) -> None:
    body = {"name": "Project", "slug": slug, "key": key}
    if valid:
        ProjectCreate.model_validate(body)
    else:
        with pytest.raises(ValidationError):
            ProjectCreate.model_validate(body)


def _criteria(count: int) -> list[dict[str, Any]]:
    return [{"name": f"Criterion {n}"} for n in range(count)]


def test_rubric_size_and_uniqueness() -> None:
    RubricUpdate.model_validate({"criteria": _criteria(MIN_CRITERIA)})
    RubricUpdate.model_validate({"criteria": _criteria(MAX_CRITERIA)})
    for count in (MIN_CRITERIA - 1, MAX_CRITERIA + 1):
        with pytest.raises(ValidationError):
            RubricUpdate.model_validate({"criteria": _criteria(count)})
    duplicate = [*_criteria(2), {"name": "criterion 0"}]
    with pytest.raises(ValidationError, match="unique"):
        RubricUpdate.model_validate({"criteria": duplicate})
    with pytest.raises(ValidationError):
        RubricUpdate.model_validate(
            {"criteria": [*_criteria(2), {"name": "x", "guidance": {"6": "no such score"}}]}
        )


@pytest.mark.parametrize(
    ("weight", "valid"),
    [(0.01, True), (1.25, True), (10, True), (0.004, False), (0, False), (1.234, False),
     (10.01, False)],
)  # fmt: skip
def test_rubric_weights_fit_the_database_column(weight: float, valid: bool) -> None:
    """numeric(4,2) with weight > 0: a weight that would round to 0.00 is a 422, not a 500."""
    body = {"criteria": [*_criteria(2), {"name": "Weighted", "weight": weight}]}
    if valid:
        assert RubricUpdate.model_validate(body).criteria[-1].weight == weight
    else:
        with pytest.raises(ValidationError):
            RubricUpdate.model_validate(body)


def test_default_rubric_is_a_valid_rubric() -> None:
    names = [criterion.name for criterion in DEFAULT_RUBRIC]
    assert names == ["Value", "Feasibility", "Effort", "Strategic fit", "Risk"]
    assert [c.name for c in DEFAULT_RUBRIC if c.inverted] == ["Effort", "Risk"]
    assert all(set(c.guidance) == {"1", "3", "5"} for c in DEFAULT_RUBRIC)

    RubricUpdate.model_validate(
        {
            "criteria": [
                {
                    "name": c.name,
                    "description": c.description,
                    "weight": float(c.weight),
                    "inverted": c.inverted,
                    "guidance": dict(c.guidance),
                }
                for c in DEFAULT_RUBRIC
            ]
        }
    )
    project_id = uuid.uuid4()
    rows = default_rubric_criteria(project_id)
    assert [row.position for row in rows] == list(range(len(DEFAULT_RUBRIC)))
    assert all(row.project_id == project_id for row in rows)
    assert rows[0].guidance is not DEFAULT_RUBRIC[0].guidance  # a copy, not shared state
    for row in rows:
        row.id = uuid.uuid4()
        RubricCriterion.model_validate(row, from_attributes=True)


def test_my_evaluation_rejects_repeated_criteria_and_bad_scores() -> None:
    criterion = str(uuid.uuid4())
    MyEvaluationIn.model_validate({"scores": [{"criterion_id": criterion, "score": None}]})
    with pytest.raises(ValidationError, match="only once"):
        MyEvaluationIn.model_validate(
            {"scores": [{"criterion_id": criterion}, {"criterion_id": criterion}]}
        )
    for score in (0, 6):
        with pytest.raises(ValidationError):
            MyEvaluationIn.model_validate({"scores": [{"criterion_id": criterion, "score": score}]})


@pytest.mark.parametrize(
    ("name", "initials"),
    [("Ada Lovelace", "AL"), ("grace brewster hopper", "GH"), ("Cher", "C"), ("  ", "?")],
)
def test_initials(name: str, initials: str) -> None:
    assert initials_for(name) == initials


def test_user_ref_serialises_initials() -> None:
    user = UserRef(id=uuid.uuid4(), display_name="Ada Lovelace")

    assert user.model_dump()["initials"] == "AL"


def test_status_labels_cover_every_status_and_resolution() -> None:
    keys = {str(k) for k in DEFAULT_STATUS_LABELS}

    assert keys == {s.value for s in IdeaStatus} | {r.value for r in Resolution}
    assert keys == set(StatusLabels.model_fields)


def test_activity_union_covers_every_type() -> None:
    items_schema = ActivityPage.model_json_schema(mode="serialization")["properties"]["items"]
    mapping = items_schema["items"]["discriminator"]["mapping"]

    assert set(mapping) == set(ACTIVITY_TYPES)


def _response_models() -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    pending: list[type[BaseModel]] = [ResponseModel]
    while pending:
        cls = pending.pop()
        found.append(cls)
        pending.extend(cls.__subclasses__())
    return [cls for cls in found if cls is not ResponseModel]


def test_response_fields_are_always_present() -> None:
    """Generated TypeScript types must have no optional response fields."""
    for model in _response_models():
        schema = model.model_json_schema(mode="serialization")
        assert set(schema.get("required", [])) == set(schema["properties"]), model.__name__
