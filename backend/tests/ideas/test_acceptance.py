"""Phase 1 acceptance, end to end through the API (SPEC section 13): create a project,
submit an idea, assign an owner, have three evaluators score it blind, see the
aggregate and the ranking.

Before each evaluator submits, they must see nothing of the others' scores on any
surface: the idea page, the list, the board, the evaluations list, the activity
feed, My work and search.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_user
from tests.ideas.conftest import Api, AsUser, ok

# Adjusted scores (Effort and Risk are inverted: 6 - score).
SCORES = {
    "Eve": {"Value": 5, "Feasibility": 4, "Effort": 2, "Strategic fit": 5, "Risk": 1},
    "Fay": {"Value": 4, "Feasibility": 4, "Effort": 3, "Strategic fit": 4, "Risk": 2},
    "Gus": {"Value": 2, "Feasibility": 3, "Effort": 4, "Strategic fit": 3, "Risk": 3},
}
COMMENTS = {name: f"{name}'s private reasoning" for name in SCORES}


def no_scores_of_others(payload: Any, evaluators: list[str]) -> None:
    text = json.dumps(payload)
    for name in evaluators:
        assert COMMENTS[name] not in text, name
    for key in ('"overall"', '"aggregate": {', '"mean"', '"recommendations"'):
        assert key not in text, key


async def blind_everywhere(
    client: Api, slug: str, idea: dict[str, Any], submitted: list[str]
) -> None:
    """What a pending evaluator sees while ``submitted`` have already submitted."""
    detail = ok(await client.get(f"/ideas/{idea['key']}"))
    assert (detail["score"], detail["aggregate"], detail["score_hidden"]) == (None, None, True)
    assert detail["high_disagreement"] is False
    assert detail["evaluator_progress"]["submitted"] == len(submitted)
    states = sorted(e["state"] for e in detail["evaluators"])
    assert states.count("submitted") == len(submitted)
    no_scores_of_others(detail, submitted)

    page = ok(await client.get(f"/projects/{slug}/ideas", sort="-score"))
    row = next(i for i in page["items"] if i["id"] == idea["id"])
    assert (row["score"], row["score_hidden"], row["high_disagreement"]) == (None, True, False)
    position = [i["id"] for i in page["items"]].index(idea["id"])
    assert all(i["score"] is None for i in page["items"][position:])  # sorts as unscored

    board = ok(await client.get(f"/projects/{slug}/board"))
    card = next(i for c in board["columns"] for i in c["items"] if i["id"] == idea["id"])
    assert (card["score"], card["score_hidden"]) == (None, True)

    evaluations = ok(await client.get(f"/ideas/{idea['id']}/evaluations"))
    assert evaluations == {"items": [], "score_hidden": True}

    feed = ok(await client.get(f"/ideas/{idea['id']}/activity"))
    submitted_events = [i for i in feed["items"] if i["type"] == "evaluation_submitted"]
    assert len(submitted_events) == len(submitted)  # who submitted is visible, not what
    no_scores_of_others(feed, submitted)

    work = ok(await client.get("/me/work"))
    assert [e["idea"]["id"] for e in work["evaluations_due"]] == [idea["id"]]
    no_scores_of_others(work, submitted)

    found = ok(await client.get("/search", q=idea["key"]))
    assert found["ideas"][0]["id"] == idea["id"]
    no_scores_of_others(found, submitted)


async def test_phase_1_acceptance(api: AsUser, db_session: AsyncSession) -> None:
    root = await make_user(db_session, "Root Admin", platform_admin=True)
    people = {
        name: await make_user(db_session, name)
        for name in ("Ada", "Max", "Olive", "Eve", "Fay", "Gus", "Vic")
    }
    platform = await api(root)

    # 1. Create a project (Ada is its admin) and add the team.
    project = ok(
        await platform.post(
            "/projects",
            {
                "name": "Customer Innovation",
                "slug": "customer-innovation",
                "key": "CUST",
                "admin_user_id": str(people["Ada"].id),
            },
        ),
        201,
    )
    slug = project["slug"]
    ada = await api(people["Ada"])
    for name in ("Max", "Olive", "Eve", "Fay", "Gus"):
        ok(await ada.post(f"/projects/{slug}/members", {"user_id": str(people[name].id)}), 201)
    body = {"user_id": str(people["Vic"].id), "role": "viewer"}
    ok(await ada.post(f"/projects/{slug}/members", body), 201)
    rubric = {c["name"]: c["id"] for c in ok(await ada.get(f"/projects/{slug}"))["rubric"]}

    # 2. Max submits an idea; two more ideas give the ranking something to rank.
    max_ = await api(people["Max"])
    idea = await max_.create_idea(slug, title="Self-service refunds", summary="Refund in the app.")
    assert idea["key"] == "CUST-1"
    runner_up = await max_.create_idea(slug, title="Refund chatbot", summary="Chat refunds.")
    unscored = await max_.create_idea(slug, title="Refund kiosk", summary="In-store refunds.")

    # 3. Ada assigns Olive as owner; Olive invites three evaluators.
    detail = ok(await ada.put(f"/ideas/{idea['key']}/owner", {"user_id": str(people["Olive"].id)}))
    assert detail["owner"]["display_name"] == "Olive"
    olive = await api(people["Olive"])
    ok(await olive.post(f"/ideas/{idea['key']}/status", {"status": "evaluating"}))
    invite = {"user_ids": [str(people[n].id) for n in SCORES]}
    detail = ok(await olive.post(f"/ideas/{idea['key']}/evaluators", invite))
    assert [e["user"]["display_name"] for e in detail["evaluators"]] == list(SCORES)
    assert detail["evaluation_due_at"] is not None  # the first invite's default

    # 4. Each evaluator is blind until they submit.
    submitted: list[str] = []
    for name, scores in SCORES.items():
        client = await api(people[name])
        await blind_everywhere(client, slug, idea, submitted)
        draft = {
            "scores": [{"criterion_id": rubric["Value"], "score": scores["Value"]}],
            "submit": False,
        }
        ok(await client.put(f"/ideas/{idea['id']}/evaluations/me", draft))
        await blind_everywhere(client, slug, idea, submitted)  # a draft changes nothing
        final = {
            "scores": [{"criterion_id": rubric[c], "score": s} for c, s in scores.items()],
            "recommendation": "go" if name != "Gus" else "maybe",
            "comment": COMMENTS[name],
            "submit": True,
        }
        mine = ok(await client.put(f"/ideas/{idea['id']}/evaluations/me", final))
        assert mine["state"] == "submitted"
        submitted.append(name)
        # Submitting lifts the blind at once.
        now_visible = ok(await client.get(f"/ideas/{idea['id']}/evaluations"))
        assert [e["evaluator"]["display_name"] for e in now_visible["items"]] == submitted

    # The runner-up gets one evaluation from Eve.
    eve = await api(people["Eve"])
    ok(
        await ada.post(
            f"/ideas/{runner_up['key']}/evaluators", {"user_ids": [str(people["Eve"].id)]}
        )
    )
    scores = {"Value": 3, "Feasibility": 3, "Effort": 3, "Strategic fit": 3, "Risk": 3}
    runner_body = {
        "scores": [{"criterion_id": rubric[c], "score": s} for c, s in scores.items()],
        "recommendation": "maybe",
        "submit": True,
    }
    ok(await eve.put(f"/ideas/{runner_up['id']}/evaluations/me", runner_body))

    # 5. The aggregate and the ranking, as the viewer sees them.
    vic = await api(people["Vic"])
    detail = ok(await vic.get(f"/ideas/{idea['key']}"))
    # Adjusted means: Value 11/3, Feasibility 11/3, Effort 3, Strategic fit 4, Risk 4
    # -> overall (11/3 + 11/3 + 3 + 4 + 4) / 5 = 11/3 = 3.67 -> 3.7.
    aggregate = detail["aggregate"]
    assert (aggregate["overall"], aggregate["count"]) == (3.7, 3)
    assert aggregate["high_disagreement"] is True  # Value 5 vs 2
    assert aggregate["recommendations"] == {"go": 2, "maybe": 1, "no": 0}
    value = next(c for c in aggregate["criteria"] if c["name"] == "Value")
    assert (value["mean"], value["min"], value["max"], value["spread"]) == (3.7, 2, 5, 3)
    assert detail["score"] == {"overall": 3.7, "count": 3}
    assert len(ok(await vic.get(f"/ideas/{idea['key']}/evaluations"))["items"]) == 3

    ranking = ok(await vic.get(f"/projects/{slug}/ideas", sort="-score"))
    assert [(i["key"], i["score"]) for i in ranking["items"]] == [
        (idea["key"], {"overall": 3.7, "count": 3}),
        (runner_up["key"], {"overall": 3.0, "count": 1}),
        (unscored["key"], None),
    ]
    assert ranking["total"] == 3
