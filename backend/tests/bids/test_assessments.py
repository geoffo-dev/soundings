"""Section assessors and assessments (contract-phase10 section 7; role matrix 3a): who may be
assigned (c28), the removal rules (``cannot_remove_self``, ``assessor_has_submitted``,
drafts going with the assignment), saving and submitting, the blind rule on every surface
of this part (section assessments, the comparison, the AI's list), and c28 checked live."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bid import BidAssessment
from app.models.enums import ProjectRole, ProjectVisibility, ResearchStep
from app.models.project import Project, ProjectMember
from app.models.user import User
from tests.api_keys.helpers import ALL_SCOPES, key_client, make_key
from tests.bids.conftest import (
    Api,
    AsUser,
    Crew,
    add_bid,
    assert_problem,
    assign,
    call_url,
    ok,
    open_call,
    qualify,
    score_questions,
    sections_by_title,
    start,
    submit,
    to_assessing,
)
from tests.bids.test_scoring import ai_assessment
from tests.factories import make_user, set_researcher


async def _assessing(
    crew: Crew, api: AsUser, db: AsyncSession, people: dict[str, list[User]], bids: int = 2
) -> tuple[Api, dict[str, Any], list[dict[str, Any]]]:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    made = [await add_bid(owner, crew, f"Bidder {n}", price="1000.00") for n in range(bids)]
    for bid in made:
        await qualify(db, bid["id"], crew.owner)
    view = await assign(owner, crew, view, people)
    await to_assessing(owner, crew)
    return owner, view, made


def _assessment_url(crew: Crew, bid: dict[str, Any], section: dict[str, Any], tail: str) -> str:
    return call_url(crew, f"/bids/{bid['id']}/sections/{section['id']}/{tail}")


# --- Assigning (c28) ------------------------------------------------------------------------------
async def test_who_may_assess(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    owner = await api(crew.owner)
    view = await start(owner, crew)
    agent = await make_user(db_session, "Bid agent", service_account=True)
    db_session.add(
        ProjectMember(project_id=crew.project.id, user_id=agent.id, role=ProjectRole.MEMBER)
    )
    gone = await make_user(db_session, "Gone Member", active=False)
    db_session.add(
        ProjectMember(project_id=crew.project.id, user_id=gone.id, role=ProjectRole.MEMBER)
    )
    glass = await make_user(db_session, "Break Glass", platform_admin=True)
    await db_session.execute(update(User).where(User.id == glass.id).values(is_break_glass=True))
    await db_session.commit()

    # A viewer, a member, a platform admin without a role: fine.
    view = await assign(
        owner,
        crew,
        view,
        {"Technical": [crew.tech1, crew.viewer], "Delivery": [crew.platform]},
        due_at="2026-11-01T17:00:00+00:00",
    )
    technical = sections_by_title(view)["Technical"]
    assert [a["user"]["id"] for a in technical["assessors"]] == sorted(
        [str(crew.tech1.id), str(crew.viewer.id)],
        key=lambda uid: {str(crew.tech1.id): "carol", str(crew.viewer.id): "zanele"}[uid],
    )
    assert all(a["can_assess"] for a in technical["assessors"])
    assert view["call"]["assessment_due_at"].startswith("2026-11-01T17:00:00")
    # Someone without a role in the private project, an agent, a deactivated person, the
    # break-glass account, an unknown id: 422 naming them by name (P10-QA-N2: never an id).
    people = [(user.id, user.display_name) for user in (crew.outsider, agent, gone, glass)] + [
        (uuid4(), "That person")
    ]
    for user_id, name in people:
        body = {
            "sections": [
                {
                    "section_id": s["id"],
                    "user_ids": [str(user_id)] if s["title"] == "Technical" else [],
                }
                for s in view["call"]["template"]["sections"]
            ],
            "due_at": None,
        }
        response = await owner.put(call_url(crew, "/assessors"), body)
        problem = assert_problem(response, 422, "assessor_not_eligible")
        assert problem["detail"].startswith(f"{name} can't assess bids here")
        assert problem["errors"][0]["msg"] == f"{name} can't assess bids on this idea"
        assert str(user_id) not in json.dumps(problem)


async def test_an_internal_projects_non_member_may_assess(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    await db_session.execute(
        update(Project)
        .where(Project.id == crew.project.id)
        .values(visibility=ProjectVisibility.INTERNAL)
    )
    await db_session.commit()
    owner = await api(crew.owner)
    view = await start(owner, crew)

    view = await assign(owner, crew, view, {"Technical": [crew.outsider]})

    assert sections_by_title(view)["Technical"]["assessors"][0]["can_assess"] is True
    seen = ok(await (await api(crew.outsider)).get(call_url(crew)))
    assert seen["call"] is not None  # +Asr in the NMi column


async def test_every_section_once(crew: Crew, api: AsUser) -> None:
    owner = await api(crew.owner)
    view = await start(owner, crew)
    sections = view["call"]["template"]["sections"]
    short = {"sections": [{"section_id": sections[0]["id"], "user_ids": []}], "due_at": None}
    foreign = {
        "sections": [{"section_id": str(uuid4()), "user_ids": []}]
        + [{"section_id": s["id"], "user_ids": []} for s in sections],
        "due_at": None,
    }

    assert_problem(await owner.put(call_url(crew, "/assessors"), short), 422, "unknown_section")
    assert_problem(await owner.put(call_url(crew, "/assessors"), foreign), 422, "unknown_section")


async def test_removing_assessors(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    owner, view, bids = await _assessing(
        crew, api, db_session, {"Technical": [crew.tech1, crew.tech2]}
    )
    technical = sections_by_title(view)["Technical"]
    tech1, tech2 = await api(crew.tech1), await api(crew.tech2)
    await submit(tech1, crew, bids[0]["id"], technical, 4)
    await submit(tech2, crew, bids[0]["id"], technical, 3, final=False)  # a draft

    # Someone who submitted stays.
    response = await owner.put(
        call_url(crew, "/assessors"),
        {
            "sections": [
                {
                    "section_id": s["id"],
                    "user_ids": [str(crew.tech2.id)] if s["title"] == "Technical" else [],
                }
                for s in view["call"]["template"]["sections"]
            ],
            "due_at": None,
        },
    )
    assert_problem(response, 409, "assessor_has_submitted")
    # Someone with a draft goes, with the draft.
    await assign(owner, crew, view, {"Technical": [crew.tech1]})
    drafts = await db_session.scalar(
        select(func.count())
        .select_from(BidAssessment)
        .where(BidAssessment.assessor_id == crew.tech2.id)
    )
    assert drafts == 0


async def test_you_cant_step_out_of_a_section_you_owe(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    """Review M3: a pending assessor (a call manager here) can't remove themselves to read
    the scores; rejected bids count as owed too."""
    owner, view, bids = await _assessing(
        crew, api, db_session, {"Technical": [crew.owner, crew.tech1]}
    )
    technical = sections_by_title(view)["Technical"]
    await submit(owner, crew, bids[0]["id"], technical, 4)
    ok(await owner.put(call_url(crew, f"/bids/{bids[1]['id']}/rejection"), {"reason": "x"}))

    response = await owner.put(
        call_url(crew, "/assessors"),
        {
            "sections": [
                {
                    "section_id": s["id"],
                    "user_ids": [str(crew.tech1.id)] if s["title"] == "Technical" else [],
                }
                for s in view["call"]["template"]["sections"]
            ],
            "due_at": None,
        },
    )

    assert_problem(response, 403, "cannot_remove_self")
    # Another call manager may remove them (they submitted one bid: assessor_has_submitted).
    response = await (await api(crew.admin)).put(
        call_url(crew, "/assessors"),
        {
            "sections": [
                {
                    "section_id": s["id"],
                    "user_ids": [str(crew.tech1.id)] if s["title"] == "Technical" else [],
                }
                for s in view["call"]["template"]["sections"]
            ],
            "due_at": None,
        },
    )
    assert_problem(response, 409, "assessor_has_submitted")


async def test_assigning_is_the_managers_in_a_session(
    crew: Crew, api: AsUser, app: FastAPI, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    view = await start(owner, crew)
    body = {
        "sections": [
            {"section_id": s["id"], "user_ids": []} for s in view["call"]["template"]["sections"]
        ],
        "due_at": None,
    }
    response = await (await api(crew.member)).put(call_url(crew, "/assessors"), body)
    assert_problem(response, 403, "forbidden")
    key = await make_key(db_session, crew.owner, scopes=ALL_SCOPES)
    async with key_client(app, key) as http:
        response = await http.put("/api/v1" + call_url(crew, "/assessors"), json=body)
    assert_problem(response, 403, "insufficient_scope")


# --- Saving and submitting -----------------------------------------------------------------------
async def test_draft_then_submit(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    _, view, bids = await _assessing(crew, api, db_session, {"Technical": [crew.tech1]})
    technical = sections_by_title(view)["Technical"]
    tech = await api(crew.tech1)
    url = _assessment_url(crew, bids[0], technical, "assessment")

    mine = ok(await tech.get(url))
    assert (mine["state"], mine["answers"], mine["can_edit"]) == ("invited", [], True)
    q1, _ = score_questions(technical)
    comment = next(q for q in technical["questions"] if q["type"] == "comment")
    draft = ok(
        await tech.put(
            url,
            {
                "answers": [
                    {"question_id": q1["id"], "score": 4},
                    {"question_id": comment["id"], "comment": "Risky."},
                ],
                "submit": False,
            },
        )
    )
    assert draft["state"] == "draft"
    response = await tech.put(
        url, {"answers": [{"question_id": q1["id"], "score": 4}], "submit": True}
    )
    assert_problem(response, 422, "assessment_incomplete")

    done = await submit(tech, crew, bids[0]["id"], technical, [4, 5])
    assert done["state"] == "submitted"
    assert done["submitted_at"] is not None
    assert done["edited_at"] is None
    # Editable after submitting (it stays submitted); a draft save can't empty it.
    again = await submit(tech, crew, bids[0]["id"], technical, [3, 5], final=False)
    assert (again["state"], again["edited_at"] is not None) == ("submitted", True)
    response = await tech.put(url, {"answers": [], "submit": False})
    assert_problem(response, 422, "assessment_incomplete")


async def test_what_cant_be_scored(crew: Crew, api: AsUser, db_session: AsyncSession) -> None:
    _, view, bids = await _assessing(
        crew, api, db_session, {"Technical": [crew.tech1], "Commercial": [crew.commercial]}
    )
    sections = sections_by_title(view)
    commercial = sections["Commercial"]
    price = next(q for q in commercial["questions"] if q["type"] == "price")
    other = score_questions(sections["Technical"])[0]
    http = await api(crew.commercial)
    url = _assessment_url(crew, bids[0], commercial, "assessment")

    assert_problem(
        await http.put(url, {"answers": [{"question_id": price["id"], "score": 5}]}),
        422,
        "not_assessable",
    )
    assert_problem(
        await http.put(url, {"answers": [{"question_id": other["id"], "score": 5}]}),
        422,
        "unknown_question",
    )
    # Another section: 403 not_section_assessor (a real section of the call).
    tech_url = _assessment_url(crew, bids[0], sections["Technical"], "assessment")
    assert_problem(await http.get(tech_url), 403, "not_section_assessor")
    assert_problem(
        await http.put(tech_url, {"answers": [], "submit": False}), 403, "not_section_assessor"
    )
    # A call manager who doesn't assess the section: also not_section_assessor.
    assert_problem(await (await api(crew.owner)).get(tech_url), 403, "not_section_assessor")


async def test_assessing_only_while_assessing_and_not_rejected(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner = await api(crew.owner)
    await start(owner, crew)
    view = await open_call(owner, crew)
    bid = await add_bid(owner, crew, "Northwind")
    view = await assign(owner, crew, view, {"Technical": [crew.tech1]})
    technical = sections_by_title(view)["Technical"]
    tech = await api(crew.tech1)
    url = _assessment_url(crew, bid, technical, "assessment")

    assert ok(await tech.get(url))["can_edit"] is False
    assert_problem(
        await tech.put(url, {"answers": [], "submit": False}), 409, "bid_call_not_assessing"
    )
    await to_assessing(owner, crew)
    ok(await owner.put(call_url(crew, f"/bids/{bid['id']}/rejection"), {"reason": "x"}))
    # A rejected bid left the assessor's queue.
    assert_problem(await tech.put(url, {"answers": [], "submit": False}), 404, "not_found")


# --- Blind (role matrix 3a) -----------------------------------------------------------------------
async def test_a_section_is_hidden_until_you_submit_it(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    _, view, bids = await _assessing(crew, api, db_session, {"Technical": [crew.tech1, crew.tech2]})
    technical = sections_by_title(view)["Technical"]
    await ai_assessment(db_session, crew, view, bids[0]["id"], {"Technical": [2, 2]})
    tech1, tech2 = await api(crew.tech1), await api(crew.tech2)
    await submit(tech1, crew, bids[0]["id"], technical, [5, 5])
    url = _assessment_url(crew, bids[0], technical, "assessments")

    # A draft doesn't lift it.
    await submit(tech2, crew, bids[0]["id"], technical, [1, 1], final=False)
    hidden = ok(await tech2.get(url))
    assert hidden == {
        "bid_id": bids[0]["id"],
        "section": {"id": technical["id"], "title": "Technical"},
        "hidden": True,
        "assessments": [],
        "ai": [],
        "questions": [],
        "section_score": None,
    }
    shown = ok(await tech1.get(url))
    assert shown["hidden"] is False
    assert [a["assessor"]["id"] for a in shown["assessments"]] == [str(crew.tech1.id)]
    assert shown["ai"][0]["scores"][0]["score"] == 2  # the AI's scores, even left out
    assert shown["section_score"] == 100.0  # 5, 5: only included AI scores count
    # Drafts are private to their author.
    assert all(a["assessor"]["id"] != str(crew.tech2.id) for a in shown["assessments"])
    # A member: 403; the owner, who doesn't assess it: sees it.
    assert_problem(await (await api(crew.member)).get(url), 403, "forbidden")
    assert ok(await (await api(crew.owner)).get(url))["hidden"] is False


async def test_a_rejection_never_ends_blindness(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, view, bids = await _assessing(
        crew, api, db_session, {"Technical": [crew.owner, crew.tech1]}
    )
    technical = sections_by_title(view)["Technical"]
    await submit(await api(crew.tech1), crew, bids[0]["id"], technical, 4)
    url = _assessment_url(crew, bids[0], technical, "assessments")
    assert ok(await owner.get(url))["hidden"] is True

    ok(await owner.put(call_url(crew, f"/bids/{bids[0]['id']}/rejection"), {"reason": "x"}))
    assert ok(await owner.get(url))["hidden"] is True
    ok(await owner.delete(call_url(crew, f"/bids/{bids[0]['id']}/rejection")))
    assert ok(await owner.get(url))["hidden"] is True


async def test_a_manager_who_owes_anything_sees_no_ranks(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, view, bids = await _assessing(
        crew, api, db_session, {"Technical": [crew.tech1], "Delivery": [crew.owner]}
    )
    sections = sections_by_title(view)
    tech = await api(crew.tech1)
    for bid in bids:
        await submit(tech, crew, bid["id"], sections["Technical"], 4)
    await submit(owner, crew, bids[0]["id"], sections["Delivery"], 4)
    ai = await ai_assessment(
        db_session, crew, view, bids[1]["id"], {"Technical": [1, 1], "Delivery": [1, 1]}
    )

    comparison = ok(await owner.get(call_url(crew, "/comparison")))

    assert comparison["ranking_hidden"] is True
    assert {row["rank"] for row in comparison["rows"]} == {None}
    second = next(row for row in comparison["rows"] if row["bid"]["id"] == bids[1]["id"])
    delivery = next(c for c in second["sections"] if c["section_id"] == sections["Delivery"]["id"])
    assert (delivery["hidden"], delivery["score"], second["total"], second["total_hidden"]) == (
        True,
        None,
        None,
        True,
    )
    # The AI's Delivery scores of that bid are left out for them, and they can't include it.
    listed = ok(await owner.get(call_url(crew, f"/bids/{bids[1]['id']}/ai-assessments")))
    assert listed["items"][0]["hidden_section_ids"] == [sections["Delivery"]["id"]]
    scored = {s["question_id"] for s in listed["items"][0]["scores"]}
    assert not scored & {q["id"] for q in sections["Delivery"]["questions"]}
    url = call_url(crew, f"/bids/{bids[1]['id']}/ai-assessments/{ai}/include-in-totals")
    assert_problem(await owner.put(url, {"include": True}), 404, "not_found")
    # Another manager who assesses nothing sees the ranking.
    admin = ok(await (await api(crew.admin)).get(call_url(crew, "/comparison")))
    assert admin["ranking_hidden"] is False


async def test_assessors_dont_see_the_comparison(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    await _assessing(crew, api, db_session, {"Technical": [crew.tech1]})

    assert_problem(
        await (await api(crew.tech1)).get(call_url(crew, "/comparison")), 403, "forbidden"
    )
    assert_problem(
        await (await api(crew.viewer)).get(call_url(crew, "/comparison")), 403, "forbidden"
    )


# --- c28 live (review M6) ------------------------------------------------------------------------
async def test_an_assessor_who_left_the_private_project_holds_nothing(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    """Even while they research the idea (a guest researcher, column R)."""
    _, _, bids = await _assessing(crew, api, db_session, {"Technical": [crew.tech1, crew.tech2]})
    await db_session.execute(
        update(Project)
        .where(Project.id == crew.project.id)
        .values(research_step=ResearchStep.BEFORE_PROPOSAL)
    )
    await db_session.commit()
    await set_researcher(db_session, crew.idea, crew.tech1)
    await db_session.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == crew.project.id, ProjectMember.user_id == crew.tech1.id
        )
    )
    await db_session.commit()
    tech = await api(crew.tech1)

    for path in ("", "/bids", f"/bids/{bids[0]['id']}"):
        assert_problem(await tech.get(call_url(crew, path)), 404, "not_found")
    detail = ok(await tech.get(f"/ideas/{crew.key}"))  # they see the idea as its researcher
    assert detail["bid_call"] is None
    assert detail["permissions"]["can_view_bid_call"] is False
    # Their unsubmitted assessments aren't expected any more.
    owner_view = ok(await (await api(crew.owner)).get(call_url(crew)))
    technical = sections_by_title(owner_view)["Technical"]
    leaver = next(a for a in technical["assessors"] if a["user"]["id"] == str(crew.tech1.id))
    assert leaver["can_assess"] is False
    assert owner_view["call"]["progress"] == {"submitted": 0, "total": 2}


async def test_a_deactivated_assessor_stops_counting(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    owner, view, bids = await _assessing(
        crew, api, db_session, {"Technical": [crew.tech1, crew.tech2]}
    )
    technical = sections_by_title(view)["Technical"]
    tech2 = await api(crew.tech2)
    await submit(tech2, crew, bids[0]["id"], technical, 4)
    await db_session.execute(update(User).where(User.id == crew.tech2.id).values(is_active=False))
    await db_session.commit()

    progress = ok(await owner.get(call_url(crew)))["call"]["progress"]

    # tech1 owes both bids (2), tech2's one submitted assessment still counts (1 of 1).
    assert progress == {"submitted": 1, "total": 3}


async def test_a_finished_call_ends_everyones_blindness(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    """Review ACC-4 (lead default, to confirm): once the call is awarded or cancelled nobody
    can score any more (409 ``bid_call_finished`` for everyone), so nobody is pending: a
    manager who still owed a section sees the ranking and the report's numbers, and an
    assessor who never submitted sees their section's scores. An agent stays blind (rule 6)."""
    owner, view, bids = await _assessing(
        crew, api, db_session, {"Technical": [crew.tech1, crew.tech2], "Delivery": [crew.owner]}
    )
    sections = sections_by_title(view)
    tech1 = await api(crew.tech1)
    for bid in bids:
        await submit(tech1, crew, bid["id"], sections["Technical"], 4)
    tech2 = await api(crew.tech2)
    technical_url = _assessment_url(crew, bids[0], sections["Technical"], "assessments")
    assert ok(await tech2.get(technical_url))["hidden"] is True
    assert ok(await owner.get(call_url(crew, "/comparison")))["ranking_hidden"] is True

    ok(await owner.post(call_url(crew, "/award"), {"bid_id": bids[0]["id"]}))

    comparison = ok(await owner.get(call_url(crew, "/comparison")))
    assert comparison["ranking_hidden"] is False
    assert all(not cell["hidden"] for row in comparison["rows"] for cell in row["sections"])
    shown = ok(await tech2.get(technical_url))
    assert shown["hidden"] is False
    assert [a["assessor"]["id"] for a in shown["assessments"]] == [str(crew.tech1.id)]
    report = await owner.get(call_url(crew, "/report/markdown"))
    assert report.status_code == 200
    assert "Hidden until you submit" not in report.text
    # Still nobody can score: the call is finished.
    answers = [{"question_id": q["id"], "score": 2} for q in score_questions(sections["Technical"])]
    assessment = _assessment_url(crew, bids[0], sections["Technical"], "assessment")
    response = await tech2.put(assessment, {"answers": answers, "submit": True})
    assert_problem(response, 409, "bid_call_finished")


async def test_leaving_the_private_project_ends_unsubmitted_assignments(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    """Review ACC-5 (lead default, to confirm), as Phase 8b clears a researcher: removing
    someone from the private project removes their assignments where they submitted nothing
    (their drafts go with them), audited ``left_project``; an assignment with a submitted
    assessment stays (its scores count). Added back, they get no bids until asked again."""
    from app.models.activity import AuditLog
    from app.models.bid import BidSectionAssessor

    _, view, bids = await _assessing(
        crew, api, db_session, {"Technical": [crew.tech1, crew.tech2], "Delivery": [crew.tech1]}
    )
    sections = sections_by_title(view)
    tech1 = await api(crew.tech1)
    await submit(tech1, crew, bids[0]["id"], sections["Technical"], 4)
    await submit(tech1, crew, bids[0]["id"], sections["Delivery"], 3, final=False)  # a draft
    admin = await api(crew.admin)
    members = f"/projects/{crew.project.slug}/members"

    response = await admin.delete(f"{members}/{crew.tech1.id}")
    assert response.status_code == 204, response.text

    held = set(
        await db_session.scalars(
            select(BidSectionAssessor.section_id).where(BidSectionAssessor.user_id == crew.tech1.id)
        )
    )
    assert held == {UUID(sections["Technical"]["id"])}  # submitted: kept; Delivery: removed
    drafts = await db_session.scalar(
        select(func.count()).where(
            BidAssessment.assessor_id == crew.tech1.id,
            BidAssessment.section_id == UUID(sections["Delivery"]["id"]),
        )
    )
    assert drafts == 0
    entry = (
        await db_session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "bid_call.assessors_change")
            .order_by(AuditLog.created_at.desc())
        )
    ).first()
    assert entry is not None
    assert entry.actor_id == crew.admin.id
    assert entry.details["reason"] == "left_project"
    assert entry.details["removed"] == {sections["Delivery"]["id"]: [str(crew.tech1.id)]}
    # tech2, still a member, keeps everything.
    assert ok(await (await api(crew.tech2)).get(call_url(crew, "/bids")))

    # Added back as a member: Delivery isn't theirs any more.
    added = await admin.post(members, {"user_id": str(crew.tech1.id), "role": "member"})
    assert added.status_code == 201, added.text
    again = ok(await tech1.get(call_url(crew, "/bids")))
    first = next(bid for bid in again["items"] if bid["id"] == bids[0]["id"])
    assert [s["section"]["title"] for s in first["my_sections"]] == ["Technical"]
    # Changing a role keeps one: nothing more is removed.
    before = await db_session.scalar(select(func.count()).select_from(BidSectionAssessor))
    patch = await admin.patch(f"{members}/{crew.tech2.id}", {"role": "viewer"})
    assert patch.status_code == 200, patch.text
    after = await db_session.scalar(select(func.count()).select_from(BidSectionAssessor))
    assert before == after


async def test_an_edit_after_submitting_is_audited(
    crew: Crew, api: AsUser, db_session: AsyncSession
) -> None:
    """Review L7: an assessor sees the others' scores once they submit, so a later change
    is audited (``bid_assessment.submit`` with ``edited: true`` and which questions changed:
    ids only, never a score). Saving the same answers again records nothing."""
    from app.models.activity import AuditLog

    _, view, bids = await _assessing(crew, api, db_session, {"Technical": [crew.tech1]})
    technical = sections_by_title(view)["Technical"]
    q1, _ = score_questions(technical)
    tech = await api(crew.tech1)
    await submit(tech, crew, bids[0]["id"], technical, [1, 4])

    async def entries() -> list[AuditLog]:
        return list(
            await db_session.scalars(
                select(AuditLog)
                .where(AuditLog.action == "bid_assessment.submit")
                .order_by(AuditLog.created_at, AuditLog.id)
                .execution_options(populate_existing=True)
            )
        )

    assert [e.details.get("edited", False) for e in await entries()] == [False]
    await submit(tech, crew, bids[0]["id"], technical, [5, 4], final=False)
    await submit(tech, crew, bids[0]["id"], technical, [5, 4])  # the same again

    found = await entries()
    assert [e.details.get("edited", False) for e in found] == [False, True]
    edit = found[-1]
    assert edit.actor_id == crew.tech1.id
    assert edit.details["changed_question_ids"] == [q1["id"]]
    assert edit.details["bid_id"] == bids[0]["id"]
    assert "score" not in json.dumps(edit.details).replace("_ids", "")
