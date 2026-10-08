"""Per-project proposal templates (contract-phase8 section 2), tests first: the template
rules (keys stable across renames and reorders, keys from titles and collisions with
removed keys, archive vs delete, restore with text, threads and suggestions, missing rows
created in every proposal, unknown keys), who may read and edit it, and every proposal
path on the template (the editor, margin threads, suggestions and their cap, exports)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import AuditLog
from app.models.enums import IdeaStatus
from app.models.idea import Idea
from app.models.proposal import ProposalSection, ProposalTemplateSection
from app.schemas.proposals import MAX_PENDING_SUGGESTIONS
from tests.api_keys.helpers import key_client, make_key
from tests.factories import make_idea
from tests.proposals.conftest import (
    SECTION_KEYS,
    AsUser,
    Team,
    assert_problem,
    ok,
    proposal_url,
    start,
)

DEFAULT_TITLES = [
    "Summary",
    "Problem",
    "Solution",
    "Market & users",
    "Cost & effort",
    "Benefits / revenue",
    "Risks",
    "Next steps / the ask",
]


def _url(team: Team) -> str:
    return f"/projects/{team.slug}/proposal-template"


def _keep(template: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    """The template's sections with ``keys`` (in this order), as a request."""
    by_key = {section["key"]: section for section in template["sections"]}
    by_key |= {section["key"]: section for section in template["removed_sections"]}
    return [
        {"key": key, "title": by_key[key]["title"], "hint": by_key[key]["hint"]} for key in keys
    ]


async def _audits(db: AsyncSession) -> list[dict[str, Any]]:
    rows: Any = await db.scalars(
        select(AuditLog.details)
        .where(AuditLog.action == "project.proposal_template_replace")
        .order_by(AuditLog.created_at)
    )
    return [{k: v for k, v in details.items() if not k.startswith("auth")} for details in rows]


async def _write(client: Any, key: str, section: str, text: str) -> dict[str, Any]:
    view = ok(await client.get(proposal_url(key)))
    current = next(s for s in view["proposal"]["sections"] if s["key"] == section)
    saved: dict[str, Any] = ok(
        await client.put(
            f"{proposal_url(key)}/sections/{section}",
            {"body_md": text, "base_version": current["version"]},
        )
    )
    return saved


# --- Reading ----------------------------------------------------------------------------------
async def test_every_project_starts_from_the_default_eight(api: AsUser, team: Team) -> None:
    template = ok(await (await api(team.viewer)).get(_url(team)))

    assert [s["key"] for s in template["sections"]] == SECTION_KEYS
    assert [s["title"] for s in template["sections"]] == DEFAULT_TITLES
    assert [s["position"] for s in template["sections"]] == list(range(8))
    assert template["sections"][1]["hint"] == "Who has this problem, and how do we know?"
    assert {s["proposal_count"] for s in template["sections"]} == {0}
    assert template["removed_sections"] == []


async def test_a_project_created_through_the_api_gets_the_default_eight(
    api: AsUser, team: Team
) -> None:
    pat = await api(team.platform)
    ok(
        await pat.post(
            "/projects",
            {"slug": "green", "key": "GREEN", "name": "Sustainability", "visibility": "internal"},
        ),
        201,
    )

    template = ok(await pat.get("/projects/green/proposal-template"))

    assert [s["key"] for s in template["sections"]] == SECTION_KEYS


@pytest.mark.parametrize(
    ("who", "status"),
    [("platform", 200), ("admin", 200), ("owner", 403), ("member", 403), ("viewer", 403)],
)
async def test_who_may_edit_the_template(api: AsUser, team: Team, who: str, status: int) -> None:
    client = await api(getattr(team, who))
    template = ok(await client.get(_url(team)))

    response = await client.put(_url(team), {"sections": _keep(template, "summary", "risks")})

    assert response.status_code == status, response.text


async def test_keys_read_the_template_but_never_change_it(
    app: FastAPI, team: Team, db_session: AsyncSession
) -> None:
    secret = await make_key(db_session, team.admin, scopes=["read", "write"])
    async with key_client(app, secret) as client:
        read = await client.get(f"/api/v1{_url(team)}")
        write = await client.put(f"/api/v1{_url(team)}", json={"sections": [{"title": "Summary"}]})

    assert read.status_code == 200
    assert_problem(write, 403, "insufficient_scope")


# --- The rules ---------------------------------------------------------------------------------
async def test_rename_reorder_add_and_remove(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ada = await api(team.admin)
    template = ok(await ada.get(_url(team)))
    sections = [
        *_keep(template, "summary", "problem", "solution"),
        {"title": "Effort & rollout", "hint": "People, time and the plan."},
        {"key": "risks", "title": "Risks and mitigations", "hint": "What could go wrong?"},
        {"title": "The ask"},
    ]

    replaced = ok(await ada.put(_url(team), {"sections": sections}))

    assert [(s["key"], s["title"], s["position"]) for s in replaced["sections"]] == [
        ("summary", "Summary", 0),
        ("problem", "Problem", 1),
        ("solution", "Solution", 2),
        ("effort_rollout", "Effort & rollout", 3),
        ("risks", "Risks and mitigations", 4),
        ("the_ask", "The ask", 5),
    ]
    assert replaced["removed_sections"] == []  # nothing referred to them: deleted
    [audit] = await _audits(db_session)
    assert audit == {
        "rule": "project.edit_proposal_template",
        "added": ["effort_rollout", "the_ask"],
        "restored": [],
        "archived": [],
        "deleted": ["market", "cost", "benefits", "next_steps"],
        "renamed": ["risks"],
        "reordered": False,
    }


async def test_keys_are_stable_across_renames_and_reorders(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ada = await api(team.admin)
    template = ok(await ada.get(_url(team)))
    swapped = _keep(template, "problem", "summary")
    swapped[0]["title"], swapped[1]["title"] = "Summary", "Problem"  # swap titles too

    replaced = ok(await ada.put(_url(team), {"sections": swapped}))

    assert [(s["key"], s["title"]) for s in replaced["sections"]] == [
        ("problem", "Summary"),
        ("summary", "Problem"),
    ]
    [audit] = await _audits(db_session)
    assert audit["reordered"] is True
    assert sorted(audit["renamed"]) == ["problem", "summary"]


async def test_nothing_changed_writes_no_audit(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ada = await api(team.admin)
    template = ok(await ada.get(_url(team)))

    again = ok(await ada.put(_url(team), {"sections": _keep(template, *SECTION_KEYS)}))

    assert again == template
    assert await _audits(db_session) == []


@pytest.mark.parametrize(
    "sections",
    [
        [{"key": "nope", "title": "Nope"}],
        [{"key": "Summary", "title": "Summary"}],  # not a key's format: 422 validation
    ],
)
async def test_an_unknown_key_is_refused(
    api: AsUser, team: Team, sections: list[dict[str, Any]]
) -> None:
    response = await (await api(team.admin)).put(_url(team), {"sections": sections})

    assert response.status_code == 422
    assert response.json()["code"] in ("unknown_section", "validation_error")


@pytest.mark.parametrize(
    "sections",
    [
        [],
        [{"title": f"Section {n}"} for n in range(13)],
        [{"title": "Risks"}, {"title": "risks"}],
        [{"key": "risks", "title": "A"}, {"key": "risks", "title": "B"}],
        [{"title": "x" * 61}],
        [{"title": "Line\nbreak"}],
        [{"title": "Hint", "hint": "y" * 201}],
    ],
)
async def test_the_templates_shape(api: AsUser, team: Team, sections: list[dict[str, Any]]) -> None:
    response = await (await api(team.admin)).put(_url(team), {"sections": sections})

    assert_problem(response, 422, "validation_error")


async def test_removing_a_section_with_text_archives_it_and_restoring_brings_it_back(
    api: AsUser, team: Team, key: str, db_session: AsyncSession
) -> None:
    olive, ada = await api(team.owner), await api(team.admin)
    await start(olive, key)
    await _write(olive, key, "market", "Every store has a parcel desk.")
    template = ok(await ada.get(_url(team)))
    without = [k for k in SECTION_KEYS if k != "market"]

    removed = ok(await ada.put(_url(team), {"sections": _keep(template, *without)}))
    hidden = ok(await olive.get(proposal_url(key)))
    restored = ok(await ada.put(_url(team), {"sections": _keep(removed, *SECTION_KEYS)}))
    shown = ok(await olive.get(proposal_url(key)))

    assert [(s["key"], s["proposal_count"]) for s in removed["removed_sections"]] == [("market", 1)]
    assert "market" not in [s["key"] for s in hidden["proposal"]["sections"]]
    assert [s["key"] for s in shown["proposal"]["sections"]] == SECTION_KEYS
    market = next(s for s in shown["proposal"]["sections"] if s["key"] == "market")
    assert market["body_md"] == "Every store has a parcel desk."
    assert restored["removed_sections"] == []
    audits = await _audits(db_session)
    assert (audits[0]["archived"], audits[1]["restored"]) == (["market"], ["market"])


@pytest.mark.parametrize("what", ["thread", "suggestion"])
async def test_a_thread_or_a_suggestion_keeps_a_section(
    api: AsUser, team: Team, key: str, what: str
) -> None:
    olive, ada, max_ = await api(team.owner), await api(team.admin), await api(team.member)
    await start(olive, key)
    if what == "thread":
        ok(
            await max_.post(
                f"{proposal_url(key)}/threads", {"section_key": "cost", "body_md": "How much?"}
            ),
            201,
        )
    else:
        ok(
            await max_.post(
                f"{proposal_url(key)}/suggestions",
                {"section_key": "cost", "body_md": "About 40k."},
            ),
            201,
        )
    template = ok(await ada.get(_url(team)))

    removed = ok(await ada.put(_url(team), {"sections": _keep(template, "summary", "problem")}))
    threads = ok(await olive.get(f"{proposal_url(key)}/threads"))
    suggestions = ok(await olive.get(f"{proposal_url(key)}/suggestions"))
    restored = ok(
        await ada.put(_url(team), {"sections": _keep(removed, "summary", "problem", "cost")})
    )
    threads_back = ok(await olive.get(f"{proposal_url(key)}/threads"))
    suggestions_back = ok(await olive.get(f"{proposal_url(key)}/suggestions"))

    assert [(s["key"], s["proposal_count"]) for s in removed["removed_sections"]] == [("cost", 0)]
    assert threads["items"] == []
    assert suggestions["items"] == []
    assert [s["key"] for s in restored["sections"]] == ["summary", "problem", "cost"]
    found = threads_back["items"] if what == "thread" else suggestions_back["items"]
    assert [item["section_key"] for item in found] == ["cost"]


async def test_new_keys_never_reuse_a_removed_sections_key(
    api: AsUser, team: Team, key: str
) -> None:
    olive, ada = await api(team.owner), await api(team.admin)
    await start(olive, key)
    await _write(olive, key, "risks", "Supplier lock-in.")
    template = ok(await ada.get(_url(team)))
    removed = ok(await ada.put(_url(team), {"sections": _keep(template, "summary")}))

    added = ok(
        await ada.put(_url(team), {"sections": [*_keep(removed, "summary"), {"title": "Risks"}]})
    )

    assert [s["key"] for s in added["sections"]] == ["summary", "risks_2"]
    assert [s["key"] for s in added["removed_sections"]] == ["risks"]


async def test_a_deleted_key_can_be_given_out_again(api: AsUser, team: Team) -> None:
    ada = await api(team.admin)
    template = ok(await ada.get(_url(team)))
    ok(await ada.put(_url(team), {"sections": _keep(template, "summary")}))

    refused = await ada.put(_url(team), {"sections": [{"key": "risks", "title": "Risks"}]})
    again = ok(await ada.put(_url(team), {"sections": [{"title": "Risks"}]}))

    assert_problem(refused, 422, "unknown_section")
    assert [s["key"] for s in again["sections"]] == ["risks"]


async def test_every_proposal_gets_rows_for_new_sections(
    api: AsUser, team: Team, key: str, db_session: AsyncSession
) -> None:
    olive, ada = await api(team.owner), await api(team.admin)
    await start(olive, key)
    other = await make_idea(
        db_session, team.project, status=IdeaStatus.SHORTLISTED, owner=team.owner
    )
    await start(olive, f"CUST-{other.number}")
    template = ok(await ada.get(_url(team)))

    ok(
        await ada.put(
            _url(team),
            {"sections": [*_keep(template, *SECTION_KEYS), {"title": "Carbon impact"}]},
        )
    )
    view = ok(await olive.get(proposal_url(key)))
    saved = await _write(olive, key, "carbon_impact", "Fewer van trips.")

    assert view["proposal"]["sections"][-1] | {"updated_at": None} == {
        "key": "carbon_impact",
        "title": "Carbon impact",
        "prompt": "",
        "body_md": "",
        "version": 1,
        "updated_at": None,
        "updated_by": None,
    }
    assert saved["version"] == 2
    rows = await db_session.scalar(
        select(func.count())
        .select_from(ProposalSection)
        .where(ProposalSection.key == "carbon_impact")
    )
    assert rows == 2


async def test_a_new_proposal_follows_the_template(
    api: AsUser, team: Team, key: str, idea: Idea
) -> None:
    ada, olive = await api(team.admin), await api(team.owner)
    ok(
        await ada.put(
            _url(team),
            {
                "sections": [
                    {"title": "The ask", "hint": "Money and people."},
                    {"key": "summary", "title": "In short"},
                ]
            },
        )
    )

    view = await start(olive, key)

    assert [(s["key"], s["title"], s["prompt"]) for s in view["proposal"]["sections"]] == [
        ("the_ask", "The ask", "Money and people."),
        ("summary", "In short", ""),
    ]
    assert view["proposal"]["sections"][1]["body_md"] == idea.summary


# --- Paths on a removed section ---------------------------------------------------------------
async def test_a_removed_section_is_404_or_unknown_section_everywhere(
    api: AsUser, team: Team, key: str
) -> None:
    olive, ada, max_ = await api(team.owner), await api(team.admin), await api(team.member)
    await start(olive, key)
    thread = ok(
        await max_.post(f"{proposal_url(key)}/threads", {"section_key": "cost", "body_md": "?"}),
        201,
    )
    suggestion = ok(
        await max_.post(
            f"{proposal_url(key)}/suggestions", {"section_key": "cost", "body_md": "40k"}
        ),
        201,
    )
    template = ok(await ada.get(_url(team)))
    ok(await ada.put(_url(team), {"sections": _keep(template, "summary", "problem")}))
    base = proposal_url(key)

    save = await olive.put(f"{base}/sections/cost", {"body_md": "x", "base_version": 1})
    unknown_save = await olive.put(f"{base}/sections/carbon", {"body_md": "x", "base_version": 1})
    new_thread = await max_.post(f"{base}/threads", {"section_key": "cost", "body_md": "?"})
    reply = await max_.post(f"{base}/threads/{thread['id']}/comments", {"body_md": "Hm"})
    resolve = await olive.put(f"{base}/threads/{thread['id']}/resolved")
    delete = await max_.delete(
        f"{base}/threads/{thread['id']}/comments/{thread['comments'][0]['id']}"
    )
    new_suggestion = await max_.post(
        f"{base}/suggestions", {"section_key": "cost", "body_md": "40k"}
    )
    accept = await olive.post(f"{base}/suggestions/{suggestion['id']}/accept", {"base_version": 1})
    discard = await olive.post(f"{base}/suggestions/{suggestion['id']}/discard")

    assert_problem(save, 404, "not_found")
    assert_problem(unknown_save, 404, "not_found")
    assert_problem(new_thread, 422, "unknown_section")
    for response in (reply, resolve, delete, accept, discard):
        assert_problem(response, 404, "not_found")
    assert_problem(new_suggestion, 422, "unknown_section")


async def test_the_suggestion_cap_counts_active_sections_only(
    api: AsUser, team: Team, key: str, db_session: AsyncSession
) -> None:
    from app.models.enums import ProjectRole
    from tests.factories import add_member, make_user

    olive, ada = await api(team.owner), await api(team.admin)
    await start(olive, key)
    for n in range(MAX_PENDING_SUGGESTIONS):
        person = await make_user(db_session, f"Sam Suggester{n}")
        await add_member(db_session, team.project, person, ProjectRole.MEMBER)
        ok(
            await (await api(person)).post(
                f"{proposal_url(key)}/suggestions", {"section_key": "cost", "body_md": f"#{n}"}
            ),
            201,
        )
    full = await (await api(team.member)).post(
        f"{proposal_url(key)}/suggestions", {"section_key": "risks", "body_md": "x"}
    )
    template = ok(await ada.get(_url(team)))
    ok(await ada.put(_url(team), {"sections": _keep(template, "summary", "risks")}))

    room = await (await api(team.member)).post(
        f"{proposal_url(key)}/suggestions", {"section_key": "risks", "body_md": "x"}
    )

    assert_problem(full, 409, "too_many_suggestions")
    assert room.status_code == 201, room.text


# --- Exports ----------------------------------------------------------------------------------
async def test_exports_follow_the_template(api: AsUser, team: Team, key: str) -> None:
    olive, ada = await api(team.owner), await api(team.admin)
    await start(olive, key)
    await _write(olive, key, "market", "Hidden market text.")
    template = ok(await ada.get(_url(team)))
    ok(
        await ada.put(
            _url(team),
            {
                "sections": [
                    *_keep(template, "risks", "summary"),
                    {"title": "Carbon impact"},
                ]
            },
        )
    )

    markdown = (await olive.get(f"{proposal_url(key)}/markdown")).text

    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert headings == ["## Risks", "## Summary", "## Carbon impact"]
    assert "Hidden market text." not in markdown


async def test_template_rows_are_unique_per_project_and_key(
    api: AsUser, team: Team, db_session: AsyncSession
) -> None:
    ok(await (await api(team.admin)).put(_url(team), {"sections": [{"title": "Summary 2"}]}))

    keys = list(
        await db_session.scalars(
            select(ProposalTemplateSection.key).where(
                ProposalTemplateSection.project_id == team.project.id
            )
        )
    )

    assert keys == ["summary_2"]  # the unused defaults were deleted


async def test_the_pending_list_has_a_hard_ceiling(
    api: AsUser, team: Team, key: str, db_session: AsyncSession
) -> None:
    """Code review N2: removing and restoring sections (the cap counts active ones) can
    leave more than 50 pending; the list never returns more than
    MAX_LISTED_SUGGESTIONS (oldest first, then in template order)."""
    from uuid import uuid4

    from app.models.enums import SuggestionSource
    from app.models.proposal import ProposalSuggestion
    from app.proposals.suggestions import MAX_LISTED_SUGGESTIONS

    view = await start(await api(team.owner), key)
    proposal_id = view["proposal"]["id"]
    db_session.add_all(
        ProposalSuggestion(
            id=uuid4(),
            proposal_id=proposal_id,
            section_key=SECTION_KEYS[n % len(SECTION_KEYS)],
            body_md=f"#{n}",
            base_version=1,
            author_id=None,
            source=SuggestionSource.MCP,
        )
        for n in range(MAX_LISTED_SUGGESTIONS + 20)
    )
    await db_session.commit()

    listed = ok(await (await api(team.member)).get(f"{proposal_url(key)}/suggestions"))

    assert MAX_LISTED_SUGGESTIONS == 200
    assert len(listed["items"]) == MAX_LISTED_SUGGESTIONS
