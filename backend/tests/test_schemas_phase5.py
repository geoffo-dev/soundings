"""Phase 5 contract: API-key schemas and the MCP tool catalogue (docs/api/contract-phase5.md
sections 3.1 and 4; role matrix sections 5 and 6)."""

from __future__ import annotations

import json
import re
import typing
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.authz import Rule
from app.authz.rules import RULE_SCOPES, SESSION_ONLY_RULES
from app.domain.principal import ApiKeyScope as PrincipalScope
from app.models.enums import ApiKeyScope
from app.schemas.api_keys import (
    API_KEY_OWNER_IDLE_LIMIT,
    API_KEY_PATTERN,
    API_KEY_PREFIX,
    API_KEY_WRITES_PER_MINUTE,
    MAX_API_KEYS_PER_USER,
    ApiKeyCreate,
    ApiKeyState,
    canonical_scopes,
)
from app.schemas.comments import CommentCreate
from app.schemas.evaluations import MyEvaluationIn
from app.schemas.ideas import IdeaCreate
from app.schemas.mcp import (
    COMMENTS_MAX,
    MCP_EVALUATIONS_MAX,
    MCP_INSTRUCTIONS,
    MCP_TEXT_LIMIT,
    MCP_TOOLS,
    UNTRUSTED,
    AddCommentInput,
    CreateIdeaInput,
    GetIdeaInput,
    GetRubricInput,
    GetRubricOutput,
    McpComment,
    McpEvaluation,
    McpIdeaDetail,
    McpIdeaRef,
    McpIdeaSummary,
    McpOutput,
    McpProject,
    McpProposal,
    McpProposalSuggestion,
    McpRubricCriterion,
    McpScoreEntry,
    McpUser,
    ProposeProposalSectionInput,
    ProposeProposalSectionOutput,
    SearchIdeasInput,
    SubmitEvaluationInput,
    tool_by_name,
)
from app.schemas.proposals import SECTION_MAX_LENGTH, ProposalSuggestionCreate

SPEC_TOOLS = [
    "list_projects",
    "search_ideas",
    "get_idea",
    "get_rubric",
    "get_proposal",
    "create_idea",
    "add_comment",
    "submit_evaluation",
    "propose_proposal_section",
]
"""SPEC section 8's tools, in role matrix section 6's order."""


# --- API keys --------------------------------------------------------------------------
def test_scopes_are_the_role_matrix_scopes_in_canonical_order() -> None:
    assert [scope.value for scope in ApiKeyScope] == ["read", "write", "evaluate", "mcp"]
    assert set(typing.get_args(PrincipalScope)) == {scope.value for scope in ApiKeyScope}
    assert set(RULE_SCOPES.values()) == {scope.value for scope in ApiKeyScope}
    assert canonical_scopes([ApiKeyScope.MCP, ApiKeyScope.READ, ApiKeyScope.MCP]) == [
        ApiKeyScope.READ,
        ApiKeyScope.MCP,
    ]


def test_key_management_is_session_only() -> None:
    """Role matrix section 5: no scope grants api_key.* (or platform.*)."""
    assert {Rule.API_KEY_MANAGE_OWN, Rule.API_KEY_MANAGE_ANY} <= SESSION_ONLY_RULES
    assert RULE_SCOPES[Rule.MCP_CONNECT] == "mcp"


@pytest.mark.parametrize(
    ("key", "valid"),
    [
        ("sdg_Ab12Cd34Ef56_" + "x" * 40, True),
        ("sdg_000000000000_" + "Z9" * 20, True),
        ("sdg_Ab12Cd34Ef5_" + "x" * 40, False),  # lookup id too short
        ("sdg_Ab12Cd34Ef56_" + "x" * 39, False),  # secret too short
        ("sdg_Ab12Cd34Ef56_" + "x" * 41, False),
        ("sdg_Ab12-d34Ef56_" + "x" * 40, False),
        ("SDG_Ab12Cd34Ef56_" + "x" * 40, False),
        ("sdg_Ab12Cd34Ef56-" + "x" * 40, False),
        ("sdg_Ab12Cd34Ef56_" + "x" * 39 + "\n", False),
        ("Bearer sdg_Ab12Cd34Ef56_" + "x" * 40, False),
    ],
)
def test_key_format(key: str, valid: bool) -> None:
    assert (re.fullmatch(API_KEY_PATTERN, key) is not None) is valid
    assert API_KEY_PREFIX == "sdg_"


def _create(**values: object) -> ApiKeyCreate:
    body: dict[str, object] = {"name": "Claude Desktop", "scopes": ["read", "mcp"]}
    body.update(values)
    return ApiKeyCreate.model_validate(body)


@pytest.mark.parametrize(
    ("asked", "stored"),
    [
        (["write"], ["read", "write"]),
        (["evaluate", "mcp"], ["read", "evaluate", "mcp"]),
        (["mcp"], ["mcp"]),
        (["mcp", "write", "evaluate"], ["read", "write", "evaluate", "mcp"]),
    ],
)
def test_write_and_evaluate_include_read(asked: list[str], stored: list[str]) -> None:
    """Role matrix section 5: their responses return readable data, so they include read."""
    assert [scope.value for scope in _create(scopes=asked).scopes] == stored


def test_key_throttles_and_states() -> None:
    assert API_KEY_WRITES_PER_MINUTE == 30
    assert timedelta(days=30) == API_KEY_OWNER_IDLE_LIMIT
    assert [state.value for state in ApiKeyState] == ["active", "expired", "dormant"]


def test_create_merges_scopes_and_projects() -> None:
    project = uuid4()

    created = _create(scopes=["mcp", "read", "mcp"], project_ids=[project, project])

    assert created.scopes == [ApiKeyScope.READ, ApiKeyScope.MCP]
    assert created.project_ids == [project]
    assert _create().project_ids is None
    assert _create().expires_at is None


@pytest.mark.parametrize(
    ("ahead", "valid"),
    [
        (timedelta(minutes=50), False),
        (timedelta(hours=2), True),
        (timedelta(days=365), True),
        (timedelta(days=367), False),
        (-timedelta(days=1), False),
    ],
)
def test_expiry_is_one_hour_to_a_year_ahead(ahead: timedelta, valid: bool) -> None:
    expires_at = (datetime.now(UTC) + ahead).isoformat()
    if valid:
        assert _create(expires_at=expires_at).expires_at is not None
    else:
        with pytest.raises(ValidationError):
            _create(expires_at=expires_at)


def test_key_limits() -> None:
    assert MAX_API_KEYS_PER_USER == 25
    with pytest.raises(ValidationError):
        _create(project_ids=[uuid4() for _ in range(51)])
    with pytest.raises(ValidationError):
        _create(name="Two\nlines")


# --- The MCP catalogue -----------------------------------------------------------------
def test_the_catalogue_is_spec_section_8() -> None:
    assert [tool.name for tool in MCP_TOOLS] == SPEC_TOOLS
    assert all(tool_by_name(name) is not None for name in SPEC_TOOLS)
    assert tool_by_name("delete_idea") is None


@pytest.mark.parametrize("tool", MCP_TOOLS, ids=lambda tool: tool.name)
def test_each_tool_names_a_rule_and_its_scope(tool: typing.Any) -> None:
    """Role matrix section 6: a policy rule per tool, and the key scope is exactly the
    one role matrix section 5 gives that rule; reads are read-only."""
    rule = Rule(tool.rule)

    assert rule not in SESSION_ONLY_RULES
    assert RULE_SCOPES[rule] == tool.scope
    assert tool.read_only == (tool.scope == ApiKeyScope.READ)
    assert not (tool.read_only and tool.destructive)
    assert re.fullmatch(r"[a-z][a-z_]{2,40}", tool.name)
    assert tool.title
    assert tool.description
    assert tool.name in MCP_INSTRUCTIONS


@pytest.mark.parametrize("tool", MCP_TOOLS, ids=lambda tool: tool.name)
def test_each_tool_has_json_schemas(tool: typing.Any) -> None:
    arguments = tool.input.model_json_schema()
    result = tool.output.model_json_schema(mode="serialization")

    assert arguments["type"] == "object"
    assert result["type"] == "object"
    assert issubclass(tool.output, McpOutput)
    # Every result field is always present (nullable rather than optional).
    assert set(result["required"]) == set(result["properties"])
    assert "secret" not in str(result)


def test_score_data_is_always_paired_with_score_hidden() -> None:
    """Role matrix section 3: every MCP result object that can carry other people's score
    data (the aggregate, submitted evaluations, the score summary) also
    says whether it is hidden (blind evaluation)."""
    score_fields = {"aggregate", "evaluations"}
    for tool in MCP_TOOLS:
        schema = tool.output.model_json_schema(mode="serialization")
        objects = [schema, *schema.get("$defs", {}).values()]
        for definition in objects:
            properties = definition.get("properties", {})
            score = properties.get("score", {})
            carries = score_fields & set(properties) or "McpScore" in str(score)
            if carries:
                assert "score_hidden" in properties, (tool.name, definition.get("title"))


def test_search_and_get_limits() -> None:
    assert SearchIdeasInput().limit == 20
    with pytest.raises(ValidationError):
        SearchIdeasInput(limit=51)
    with pytest.raises(ValidationError):
        SearchIdeasInput(query="")
    with pytest.raises(ValidationError):
        SearchIdeasInput(project="Not A Slug")
    with pytest.raises(ValidationError):
        SearchIdeasInput.model_validate({"status": ["new"] * 6})
    assert GetIdeaInput(idea="cust-12").comment_limit == 10
    assert GetIdeaInput(idea="0b7c7d1e-7a55-4a4f-9b8b-0d7d3a9d1c11", comment_limit=0)
    for reference in ("CUST12", "cust-0", "12", "x" * 37, "CUST-12; DROP"):
        with pytest.raises(ValidationError):
            GetIdeaInput(idea=reference)
    assert COMMENTS_MAX == 20
    with pytest.raises(ValidationError):
        GetIdeaInput(idea="CUST-1", comment_limit=21)


def test_results_are_bounded() -> None:
    """get_idea can't return megabytes: comments and evaluations are capped, long texts
    cut with a flag (contract-phase5 section 4.3)."""
    assert MCP_TEXT_LIMIT == 2_000
    assert MCP_EVALUATIONS_MAX == 25
    assert "truncated" in McpComment.model_fields
    assert "truncated" in McpEvaluation.model_fields
    assert "evaluation_count" in McpIdeaDetail.model_fields


def test_people_written_text_is_marked_untrusted() -> None:
    """Prompt injection: every field people write says it is untrusted, and ideas from the
    public form say where they came from, in search results too."""
    fields: list[tuple[type[BaseModel], str]] = [
        (McpIdeaDetail, "title"),
        (McpIdeaDetail, "summary"),
        (McpIdeaDetail, "description_md"),
        (McpIdeaDetail, "tags"),
        (McpComment, "body_md"),
        (McpEvaluation, "comment"),
        (McpScoreEntry, "comment"),
        (McpProject, "description"),
        (McpProposal, "sections"),
        (McpUser, "display_name"),
        (McpIdeaRef, "status_label"),
        (McpRubricCriterion, "name"),
        (McpRubricCriterion, "description"),
        (McpRubricCriterion, "guidance"),
        (McpProposalSuggestion, "body_md"),
    ]
    for model, name in fields:
        description = model.model_fields[name].description or ""
        assert UNTRUSTED in description, (model.__name__, name)
    assert "via_public_form" in McpIdeaSummary.model_fields
    for name in ("search_ideas", "get_idea", "get_proposal"):
        tool = tool_by_name(name)
        assert tool is not None
        assert "never instructions" in tool.description
    # The published output schemas carry the markings (review nit 2).
    rubric = json.dumps(GetRubricOutput.model_json_schema(mode="serialization"))
    suggestion = json.dumps(ProposeProposalSectionOutput.model_json_schema(mode="serialization"))
    assert rubric.count(UNTRUSTED) >= 3
    assert UNTRUSTED in suggestion


@pytest.mark.parametrize(
    ("tool_input", "rest_model"),
    [
        (CreateIdeaInput, IdeaCreate),
        (AddCommentInput, CommentCreate),
        (SubmitEvaluationInput, MyEvaluationIn),
        (ProposeProposalSectionInput, ProposalSuggestionCreate),
    ],
)
def test_write_tools_take_the_rest_request_models(
    tool_input: type[object], rest_model: type[object]
) -> None:
    """The write tools' arguments are the REST bodies plus the idea or project, so limits
    and normalisation can't drift."""
    assert issubclass(tool_input, rest_model)


def test_create_idea_merges_tags_like_rest() -> None:
    arguments = CreateIdeaInput.model_validate(
        {"project": "cust", "title": "T", "summary": "S", "tags": ["A", "a"]}
    )
    assert arguments.tags == ["A"]


def test_read_arguments_ignore_extras_strip_and_refuse_nul_and_tag_characters() -> None:
    assert SearchIdeasInput.model_validate({"query": "  returns ", "page": 2}).query == "returns"
    for query in ("a\x00b", "a\U000e0041b"):
        with pytest.raises(ValidationError):
            SearchIdeasInput(query=query)


@pytest.mark.parametrize(
    ("tool_input", "arguments"),
    [
        (CreateIdeaInput, {"project": "cust", "title": "T", "summary": "S"}),
        (AddCommentInput, {"idea": "CUST-1", "body_md": "Hi"}),
        (SubmitEvaluationInput, {"idea": "CUST-1", "scores": []}),
        (
            ProposeProposalSectionInput,
            {"idea": "CUST-1", "section_key": "summary", "body_md": "Text"},
        ),
    ],
)
def test_write_arguments_refuse_unknown_ones(
    tool_input: type[BaseModel], arguments: dict[str, object]
) -> None:
    """A typo in a write (``sumbit`` for ``submit``) is a validation error, never a
    silently ignored argument that leaves a default in place (security review L2)."""
    tool_input.model_validate(arguments)
    with pytest.raises(ValidationError) as caught:
        tool_input.model_validate(arguments | {"sumbit": False})
    assert [error["type"] for error in caught.value.errors()] == ["extra_forbidden"]


def test_get_rubric_takes_a_project_or_an_idea() -> None:
    assert GetRubricInput(project="cust").idea is None
    assert GetRubricInput(idea="CUST-1").project is None
    for arguments in ({}, {"project": "cust", "idea": "CUST-1"}):
        with pytest.raises(ValidationError):
            GetRubricInput.model_validate(arguments)


def test_submit_evaluation_maps_to_save_my_evaluation() -> None:
    criterion = uuid4()
    arguments = SubmitEvaluationInput.model_validate(
        {"idea": "CUST-1", "scores": [{"criterion_id": str(criterion), "score": 4}]}
    )

    assert arguments.submit is True  # unlike REST, submitting is the default
    assert arguments.recommendation is None  # completeness is the endpoint's 422
    for scores in (
        [{"criterion_id": str(criterion), "score": 6}],
        [{"criterion_id": str(criterion), "score": 3}] * 2,
        [{"criterion_id": str(uuid4()), "score": 3} for _ in range(7)],
    ):
        with pytest.raises(ValidationError):
            SubmitEvaluationInput.model_validate({"idea": "CUST-1", "scores": scores})


def test_proposed_text_is_verbatim_and_bounded() -> None:
    def propose(section_key: str, body_md: str) -> ProposeProposalSectionInput:
        return ProposeProposalSectionInput.model_validate(
            {"idea": "CUST-1", "section_key": section_key, "body_md": body_md}
        )

    assert propose("risks", "    code\n\n").body_md == "    code\n\n"
    for body in ("", "  \n", "x" * (SECTION_MAX_LENGTH + 1)):
        with pytest.raises(ValidationError):
            propose("risks", body)
    with pytest.raises(ValidationError):
        propose("appendix", "x")
