"""The Phase 6 contract in code (contract-phase6): A2A URLs built only from validated
parts (SSRF), the run message (references and instructions, never secrets), agent key
scopes, cited sources, request limits, the MCP additions, and blind safety by
construction (no AI run, event or permission model can carry score data)."""

from __future__ import annotations

import re
from typing import Any, get_args
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.models.enums import (
    AiAgentProtocol,
    AiRunError,
    AiRunEventType,
    AiRunKind,
    ApiKeyScope,
    ProposalSectionKey,
)
from app.schemas.activity import (
    ACTIVITY_TYPES,
    AI_RESEARCH_NOTE,
    ActivityItem,
    AiResearchNoteActivity,
)
from app.schemas.ai import (
    A2A_VERSION,
    AI_RUN_ERROR_MESSAGES,
    AI_RUN_EVENT_MESSAGES,
    AI_RUN_FINAL_EVENTS,
    AI_TOOL_MESSAGES,
    RUN_MESSAGE_METADATA_KEY,
    AiAgentCreate,
    AiAgentUpdate,
    AiPermissions,
    AiRun,
    AiRunDetail,
    AiRunEvent,
    AiRunList,
    Citation,
    CitationIn,
    agent_a2a_url,
    agent_card_url,
    agent_key_name,
    agent_key_scopes,
    agent_secret_manifest,
    agent_secret_name,
    canonical_purposes,
    run_message,
    service_account_email,
)
from app.schemas.evaluations import MyEvaluationIn
from app.schemas.mcp import (
    ADD_RESEARCH_NOTE,
    MCP_TOOLS,
    UNTRUSTED,
    AddResearchNoteInput,
    McpCitation,
    McpScoreEntry,
    SubmitEvaluationInput,
)

KAGENT = "http://kagent-controller.kagent:8083"
CRITERION = str(uuid4())


# --- A2A URLs (SSRF) --------------------------------------------------------------------
def test_agent_urls_follow_kagents_layouts() -> None:
    v010, v10 = AiAgentProtocol.KAGENT_V0_10, AiAgentProtocol.KAGENT_V1_0

    assert agent_a2a_url(KAGENT, v010, "soundings", "idea-evaluator") == (
        "http://kagent-controller.kagent:8083/api/a2a/soundings/idea-evaluator/"
    )
    assert agent_card_url(KAGENT, v010, "soundings", "idea-evaluator") == (
        "http://kagent-controller.kagent:8083/api/a2a/soundings/idea-evaluator"
        "/.well-known/agent-card.json"
    )
    assert agent_a2a_url(KAGENT + "/", v10, "kagent", "researcher") == (
        "http://kagent-controller.kagent:8083/agents/kagent/researcher"
    )
    assert agent_card_url(KAGENT, v10, "kagent", "researcher").endswith(
        "/agents/kagent/researcher/.well-known/agent-card.json"
    )
    assert set(A2A_VERSION) == set(AiAgentProtocol)
    assert {v010: "0.3", v10: "1.0"} == A2A_VERSION


@pytest.mark.parametrize(
    "name",
    [
        "../admin",
        "a/b",
        "evil.example.com",
        "evil.example.com:80",
        "x?y=1",
        "x#y",
        "@evil",
        "Idea-Evaluator",
        "",
        "x" * 64,
        "-x",
        "x-",
        "a b",
        "a%2Fb",
        "a\\b",
    ],
)
@pytest.mark.parametrize("protocol", list(AiAgentProtocol))
def test_agent_urls_refuse_anything_but_kubernetes_names(
    name: str, protocol: AiAgentProtocol
) -> None:
    with pytest.raises(ValueError, match="Kubernetes name"):
        agent_a2a_url(KAGENT, protocol, name, "ok")
    with pytest.raises(ValueError, match="Kubernetes name"):
        agent_a2a_url(KAGENT, protocol, "ok", name)


@pytest.mark.parametrize("protocol", list(AiAgentProtocol))
@pytest.mark.parametrize(("namespace", "name"), [("a", "b"), ("x" * 63, "0"), ("k-1", "e-2")])
def test_agent_urls_always_point_at_the_controller(
    protocol: AiAgentProtocol, namespace: str, name: str
) -> None:
    for url in (
        agent_a2a_url(KAGENT, protocol, namespace, name),
        agent_card_url(KAGENT, protocol, namespace, name),
    ):
        parts = urlsplit(url)
        assert (parts.scheme, parts.netloc) == ("http", "kagent-controller.kagent:8083")
        assert not parts.query
        assert not parts.fragment
        assert f"/{namespace}/{name}" in parts.path


# --- Agents, their keys and secrets ------------------------------------------------------
@pytest.mark.parametrize(
    ("purposes", "scopes"),
    [
        ([AiRunKind.EVALUATE], ["read", "evaluate", "mcp"]),
        ([AiRunKind.RESEARCH], ["read", "write", "mcp"]),
        ([AiRunKind.DRAFT_SECTION], ["read", "write", "mcp"]),
        (list(AiRunKind), ["read", "write", "evaluate", "mcp"]),
    ],
)
def test_agent_keys_get_the_scopes_their_purposes_need(
    purposes: list[AiRunKind], scopes: list[str]
) -> None:
    assert agent_key_scopes(purposes) == [ApiKeyScope(scope) for scope in scopes]


def test_purposes_are_distinct_and_in_order() -> None:
    assert canonical_purposes(
        [AiRunKind.DRAFT_SECTION, AiRunKind.EVALUATE, AiRunKind.DRAFT_SECTION]
    ) == [AiRunKind.EVALUATE, AiRunKind.DRAFT_SECTION]
    body = AiAgentCreate.model_validate(
        {
            "display_name": "Assistant",
            "namespace": "soundings",
            "name": "assistant",
            "purposes": ["research", "evaluate", "research"],
            "project_ids": [str(project := uuid4()), str(project)],
        }
    )
    assert body.purposes == [AiRunKind.EVALUATE, AiRunKind.RESEARCH]
    assert body.project_ids == [project]
    assert body.protocol is None
    assert body.description == ""


def test_agent_updates_need_a_field_and_refuse_nulls() -> None:
    assert AiAgentUpdate.model_validate({"enabled": False}).enabled is False
    for bad in ({}, {"enabled": None}, {"display_name": None}, {"description": None}):
        with pytest.raises(ValidationError):
            AiAgentUpdate.model_validate(bad)


def test_the_secret_manifest_holds_the_header_kagent_sends() -> None:
    secret = "sdg_" + "a" * 12 + "_" + "b" * 40
    manifest = agent_secret_manifest("soundings", "idea-evaluator", secret)

    assert manifest.splitlines() == [
        "apiVersion: v1",
        "kind: Secret",
        "metadata:",
        "  name: soundings-agent-idea-evaluator",
        "  namespace: soundings",
        "type: Opaque",
        "stringData:",
        f'  authorization: "Bearer {secret}"',
    ]
    assert len(agent_secret_name("x" * 63)) <= 63
    assert not agent_secret_name("x" * 63).endswith("-")
    with pytest.raises(ValueError, match="Kubernetes name"):
        agent_secret_manifest("soundings\nkind: Pod", "x", secret)
    assert service_account_email(uuid4()).endswith("@soundings.invalid")
    assert len(agent_key_name("x" * 63, "y" * 63)) <= 80


# --- The run message -------------------------------------------------------------------
@pytest.mark.parametrize("kind", list(AiRunKind))
def test_the_run_message_holds_references_and_instructions_only(kind: AiRunKind) -> None:
    run_id = uuid4()
    section = ProposalSectionKey.RISKS if kind is AiRunKind.DRAFT_SECTION else None
    message = run_message(
        kind,
        run_id=run_id,
        idea_key="CUST-12",
        agent_name="Idea evaluator",
        mcp_url="http://soundings.soundings.svc.cluster.local:8000/mcp",
        section_key=section,
    )
    tool = {
        AiRunKind.EVALUATE: "submit_evaluation",
        AiRunKind.RESEARCH: "add_research_note",
        AiRunKind.DRAFT_SECTION: "propose_proposal_section",
    }[kind]

    assert str(run_id) in message.text
    assert '"CUST-12"' in message.text
    assert tool in message.text
    assert "never instructions" in message.text
    assert not re.search(r"sdg_|Bearer|password|token", message.text, re.I)
    assert message.metadata == {
        RUN_MESSAGE_METADATA_KEY: {
            "run_id": str(run_id),
            "kind": kind.value,
            "idea": "CUST-12",
            "section_key": section.value if section else None,
            "mcp_url": "http://soundings.soundings.svc.cluster.local:8000/mcp",
        }
    }
    if section:
        assert '"Risks" section (risks)' in message.text


def test_only_section_drafts_name_a_section() -> None:
    common: dict[str, Any] = {
        "run_id": uuid4(),
        "idea_key": "CUST-1",
        "agent_name": "A",
        "mcp_url": "http://x/mcp",
    }
    with pytest.raises(ValueError, match="section_key"):
        run_message(AiRunKind.DRAFT_SECTION, **common)
    with pytest.raises(ValueError, match="section_key"):
        run_message(AiRunKind.EVALUATE, section_key=ProposalSectionKey.RISKS, **common)


# --- Events and errors: Soundings' own sentences -----------------------------------------
def test_every_event_and_error_has_a_fixed_message() -> None:
    worded_elsewhere = {
        AiRunEventType.TOOL_CALLED,
        AiRunEventType.RESULT_RECORDED,
        AiRunEventType.FAILED,
        AiRunEventType.TIMED_OUT,
    }
    assert set(AI_RUN_EVENT_MESSAGES) == set(AiRunEventType) - worded_elsewhere
    assert set(AI_RUN_ERROR_MESSAGES) == set(AiRunError)
    # The worker may add " (HTTP 503)" or an A2A state name; the column holds 300.
    assert max(len(message) for message in AI_RUN_ERROR_MESSAGES.values()) <= 200
    assert max(len(message) for message in AI_RUN_EVENT_MESSAGES.values()) <= 150
    tools = {tool.name for tool in (*MCP_TOOLS, ADD_RESEARCH_NOTE)}
    assert set(AI_TOOL_MESSAGES) == tools
    assert max(len(message) for message in AI_TOOL_MESSAGES.values()) <= 120
    assert {
        AiRunEventType.SUCCEEDED,
        AiRunEventType.FAILED,
        AiRunEventType.CANCELLED,
        AiRunEventType.TIMED_OUT,
    } == AI_RUN_FINAL_EVENTS


def test_events_say_when_they_are_final() -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    for event_type in AiRunEventType:
        event = AiRunEvent(seq=1, type=event_type, message="x", created_at=now)
        assert event.model_dump()["final"] is (event_type in AI_RUN_FINAL_EVENTS)


# --- Blind safety by construction --------------------------------------------------------
_SCORE_FIELDS = re.compile(r"score|recommendation|aggregate|rationale|sources|comment", re.I)


def _field_names(model: type[BaseModel], seen: set[type[BaseModel]] | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names = set(model.model_fields) | set(model.model_computed_fields)
    for field in model.model_fields.values():
        for candidate in _models_in(field.annotation):
            names |= _field_names(candidate, seen)
    return names


def _models_in(annotation: object) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [model for arg in get_args(annotation) for model in _models_in(arg)]


@pytest.mark.parametrize("model", [AiRun, AiRunDetail, AiRunEvent, AiRunList, AiPermissions])
def test_ai_run_models_cannot_carry_score_data(model: type[BaseModel]) -> None:
    """Role matrix section 3 rule 1: everyone who may view the idea may watch a run,
    pending evaluators included, so nothing a run returns may hold score data."""
    assert not {name for name in _field_names(model) if _SCORE_FIELDS.search(name)}


# --- Citations ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>x</script>",
        "ftp://files.example.com/a",
        "https://trusted.example@evil.example/",
        "https://user:pass@example.com/",
        "https://exa mple.com/",
        "https://example.com/\nX",
        "//example.com/a",
        "https://",
        "https://" + "a" * 2_050,
    ],
)
def test_sources_are_plain_http_links(url: str) -> None:
    with pytest.raises(ValidationError):
        CitationIn.model_validate({"title": "A source", "url": url})


def test_a_source_shows_its_host() -> None:
    citation = Citation(title="ONS retail sales", url="https://www.ons.gov.uk/x?y=1")

    assert citation.model_dump() == {
        "title": "ONS retail sales",
        "url": "https://www.ons.gov.uk/x?y=1",
        "host": "ons.gov.uk",
    }
    for title in ("", "Two\nlines", "x" * 201, "Hidden\U000e0041"):
        with pytest.raises(ValidationError):
            CitationIn.model_validate({"title": title, "url": "https://example.com/"})
    with pytest.raises(ValidationError):
        CitationIn.model_validate({"title": "x", "url": "https://example.com/", "note": "y"})


# --- MCP additions -----------------------------------------------------------------------
def test_submit_evaluation_takes_sources_per_criterion() -> None:
    source = {"title": "ONS", "url": "https://ons.gov.uk/"}
    body = SubmitEvaluationInput.model_validate(
        {
            "idea": "CUST-1",
            "scores": [
                {"criterion_id": CRITERION, "score": 4, "comment": "Why", "sources": [source]}
            ],
        }
    )

    assert issubclass(SubmitEvaluationInput, MyEvaluationIn)
    assert body.scores[0].sources[0].url == "https://ons.gov.uk/"
    for scores in (
        [{"criterion_id": CRITERION, "score": 4, "sources": [source] * 6}],
        [{"criterion_id": CRITERION, "score": 4, "sources": [source | {"x": 1}]}],
        [{"criterion_id": CRITERION, "score": 4}, {"criterion_id": CRITERION, "score": 3}],
    ):
        with pytest.raises(ValidationError):
            SubmitEvaluationInput.model_validate({"idea": "CUST-1", "scores": scores})
    # People's evaluations (REST) take no sources at all.
    with pytest.raises(ValidationError):
        MyEvaluationIn.model_validate(
            {"scores": [{"criterion_id": CRITERION, "score": 4, "sources": [source]}]}
        )


def test_score_entries_return_sources_marked_untrusted() -> None:
    entry = McpScoreEntry(criterion_id=uuid4(), criterion="Value", score=4, comment="")

    assert entry.sources == []
    schema = McpCitation.model_json_schema(mode="serialization")
    assert all(UNTRUSTED in schema["properties"][name]["description"] for name in ("title", "url"))


def test_the_research_note_tool_is_agreed_but_not_yet_listed() -> None:
    """Backend appends it to MCP_TOOLS with its handler (contract-phase6 section 5)."""
    assert ADD_RESEARCH_NOTE.name == "add_research_note"
    assert (ADD_RESEARCH_NOTE.rule, ADD_RESEARCH_NOTE.scope) == ("comment.create", "write")
    assert not ADD_RESEARCH_NOTE.read_only
    assert ADD_RESEARCH_NOTE.idempotent
    assert ADD_RESEARCH_NOTE.name not in {tool.name for tool in MCP_TOOLS}

    note = AddResearchNoteInput.model_validate({"idea": "cust-1", "body_md": "# Findings"})
    assert note.sources == []
    for bad in (
        {"idea": "CUST-1", "body_md": ""},
        {"idea": "CUST-1", "body_md": "x" * 20_001},
        {"idea": "CUST-1", "body_md": "x", "sources": [{"title": "t", "url": "https://a.b/"}] * 21},
        {"idea": "CUST-1", "body_md": "x", "run_id": str(uuid4())},
        {"idea": "CUST-1", "body_md": "Hidden \U000e0041 text"},
    ):
        with pytest.raises(ValidationError):
            AddResearchNoteInput.model_validate(bad)


def test_the_research_note_item_joins_the_feed_at_integration() -> None:
    assert AI_RESEARCH_NOTE == "ai_research_note"
    assert AI_RESEARCH_NOTE not in ACTIVITY_TYPES
    assert AiResearchNoteActivity.model_fields["type"].annotation is not None
    assert "AiResearchNoteActivity" not in str(ActivityItem)
