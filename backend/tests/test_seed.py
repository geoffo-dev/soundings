"""``soundings seed``: the demo data, played through the services (app/seed).

Two full seeds (about ten seconds each); the other checks reuse them.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

import pytest
from sqlalchemy import DateTime, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli, seed
from app.config import Settings
from app.models import (
    Base,
    Evaluation,
    EvaluationStatus,
    Idea,
    IdeaEvaluator,
    IdeaStatus,
    Project,
    ProjectMember,
    ProjectRole,
    Resolution,
    User,
)
from app.models.activity import AuditLog
from app.models.base import utcnow
from app.models.enums import GroupSyncMode
from app.models.group import Group, GroupIdpValue, GroupMembership, ProjectGroupGrant
from app.models.project import project_effective_roles
from app.models.user import UserExternalId
from app.seed import SeedRefused, SeedReport, check_allowed, check_reset_allowed, run_seed
from app.seed.content import GROUPS, IDEAS, PEOPLE, PROJECTS
from app.seed.public import CUST_BRANDING, GLOBAL_FOOTER, PUBLIC_IDEAS
from app.seed.runner import DEMO_ID_NAMESPACE
from app.services.scoring import recompute_aggregates
from tests.conftest import Login, make_settings
from tests.factories import make_project, make_user

API = "/api/v1"


# --- Guard rails (no database) ---------------------------------------------------------------
def test_refuses_production_unless_forced() -> None:
    production = make_settings(environment="production", secret_key="x" * 40)
    with pytest.raises(SeedRefused, match="production"):
        check_allowed(production)
    check_allowed(production, force=True)
    check_allowed(make_settings(environment="development"))


def test_cli_refuses_production_before_touching_the_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    production = make_settings(
        environment="production",
        secret_key="x" * 40,
        database_url="postgresql://u:p@nowhere.invalid/db",
    )
    monkeypatch.setattr(cli, "get_database_settings", lambda: production)

    assert cli.main(["seed", "--reset"]) == 1
    assert "production" in capsys.readouterr().err


async def test_reset_needs_force_unless_everyone_is_a_demo_person(
    db_session: AsyncSession,
) -> None:
    """``seed --reset`` without ``SOUNDINGS_ENVIRONMENT`` defaults to development, so
    the environment alone can't protect a real database: its people can."""
    await check_reset_allowed(db_session)  # empty
    for person in PEOPLE[:3]:
        db_session.add(
            User(
                id=uuid5(DEMO_ID_NAMESPACE, person.email),
                email=person.email,
                display_name=person.name,
            )
        )
    await db_session.commit()
    await check_reset_allowed(db_session)  # demo people only

    await make_user(db_session, "Real Person", email="real.person@example.org")
    with pytest.raises(SeedRefused, match="--force"):
        await check_reset_allowed(db_session)
    await check_reset_allowed(db_session, force=True)


def test_cli_refuses_a_reset_it_is_not_sure_about(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[bool, bool]] = []

    async def refusing_run_seed(
        settings: object, *, reset: bool = False, force: bool = False
    ) -> SeedReport:
        calls.append((reset, force))
        raise SeedRefused("Refusing to --reset: use --force")

    monkeypatch.setattr(cli, "get_database_settings", make_settings)
    monkeypatch.setattr(seed, "run_seed", refusing_run_seed)

    assert cli.main(["seed", "--reset"]) == 1
    assert calls == [(True, False)]
    assert "--force" in capsys.readouterr().err


def test_cli_seeds_and_prints_a_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[bool] = []

    async def fake_run_seed(
        settings: object, *, reset: bool = False, force: bool = False
    ) -> SeedReport:
        calls.append(reset)
        return SeedReport(users=12, projects=3, ideas=45)

    monkeypatch.setattr(cli, "get_database_settings", make_settings)
    monkeypatch.setattr(seed, "run_seed", fake_run_seed)

    assert cli.main(["seed", "--reset"]) == 0
    assert calls == [True]
    assert "Seeded 12 users, 3 projects and 45 ideas" in capsys.readouterr().out


def test_content_is_consistent() -> None:
    """Cheap checks on the story itself; the seed run below checks the rest."""
    usernames = {person.username for person in PEOPLE}
    assert len(usernames) == len(PEOPLE) == 12
    assert [person.username for person in PEOPLE if person.platform_admin] == ["alice"]
    roles = {
        project.key: {project.admin: ProjectRole.ADMIN, **dict(project.members)}
        for project in PROJECTS
    }
    assert Counter(idea.project for idea in IDEAS) == {"CUST": 20, "TOOLS": 13, "GREEN": 12}
    for idea in IDEAS:
        can_act = {
            user for user, role in roles[idea.project].items() if role is not ProjectRole.VIEWER
        }
        people = [idea.submitter, *idea.voters, *(remark.author for remark in idea.remarks)]
        people += [review.evaluator for review in idea.reviews] + list(idea.dropped)
        if idea.owner:
            people.append(idea.owner)
        assert set(people) <= can_act, idea.title
        assert idea.owner not in {review.evaluator for review in idea.reviews}, idea.title
        assert (idea.status is IdeaStatus.CLOSED) == (idea.resolution is not None), idea.title


# --- The seeded database ---------------------------------------------------------------------
async def _fingerprint(db: AsyncSession) -> list[tuple[object, ...]]:
    """What the demo shows, without ids and times (those move with every run)."""
    rows = await db.execute(
        select(
            Project.key,
            Idea.number,
            Idea.title,
            Idea.status,
            Idea.resolution,
            Idea.aggregate_score,
            Idea.aggregate_count,
            Idea.high_disagreement,
            Idea.vote_count,
            User.email,
        )
        .join(Project, Project.id == Idea.project_id)
        .outerjoin(User, User.id == Idea.owner_id)
        .order_by(Project.key, Idea.number)
    )
    return [tuple(row) for row in rows]


async def test_seed_tells_the_demo_story(
    settings: Settings, db_session: AsyncSession, login: Login
) -> None:
    # Someone who signed in before the seed keeps their account (matched by email).
    carol = (await make_user(db_session, "Carol C.", email="Carol@Example.com")).id

    report = await run_seed(settings)

    assert report.skipped is None
    assert (report.users, report.projects, report.ideas) == (12, 3, 48)
    assert report.evaluations_submitted > 60
    assert report.evaluations_draft >= 2
    assert report.evaluators_pending >= 8
    assert report.comments >= 30
    assert report.votes >= 100
    assert "Seeded 12 users" in report.summary()

    # People: deterministic ids, alice is the only platform admin.
    users = {user.email: user for user in await db_session.scalars(select(User))}
    alice = users["alice@example.com"]
    assert alice.id == uuid5(DEMO_ID_NAMESPACE, "alice@example.com")
    assert users["Carol@Example.com"].id == carol
    assert [user.email for user in users.values() if user.is_platform_admin] == [alice.email]

    # Projects: keys, visibility and roles as described, one customised rubric.
    projects = {project.key: project for project in await db_session.scalars(select(Project))}
    assert projects.keys() == {"CUST", "TOOLS", "GREEN"}
    assert projects["TOOLS"].status_labels == {"shortlisted": "Next up"}
    assert projects["GREEN"].default_evaluation_days == 14
    roles = Counter(await db_session.scalars(select(ProjectMember.role)))
    assert roles[ProjectRole.ADMIN] == 4
    assert roles[ProjectRole.VIEWER] == 5

    # Phase 2: alice, bob and carol carry the dev realm's employee numbers; five groups
    # are mapped to its groups and granted roles. Their manual members already hold the
    # granted role directly, so with the dev login nobody sees more than before.
    external_ids = dict(
        (
            await db_session.execute(
                select(User.email, UserExternalId.value)
                .join(UserExternalId, UserExternalId.user_id == User.id)
                .where(UserExternalId.kind == "employee_no")
            )
        ).all()
    )
    assert external_ids == {
        "alice@example.com": "E1001",
        "bob@example.com": "E1002",
        "Carol@Example.com": "E1003",
    }
    assert report.groups == len(GROUPS) == 5
    groups = {group.name: group for group in await db_session.scalars(select(Group))}
    mapped = dict(
        (await db_session.execute(select(GroupIdpValue.group_id, GroupIdpValue.value))).all()
    )
    assert {name: mapped.get(group.id) for name, group in groups.items()} == {
        "Innovation admins": "innovation/admins",
        "Innovation members": "innovation/members",
        "Tools team": "tools/members",
        "Viewers": "viewers",
        "Sustainability champions": None,
    }
    assert groups["Viewers"].sync_mode is GroupSyncMode.ADDITIVE
    grants = {
        (group_id, project_id): role
        for group_id, project_id, role in await db_session.execute(
            select(ProjectGroupGrant.group_id, ProjectGroupGrant.project_id, ProjectGroupGrant.role)
        )
    }
    assert len(grants) == 5
    assert grants[groups["Innovation admins"].id, projects["CUST"].id] == ProjectRole.ADMIN
    memberships = list(await db_session.scalars(select(GroupMembership)))
    assert len(memberships) == 8
    assert all(m.manual and not m.synced for m in memberships)
    effective = set((await db_session.execute(select(project_effective_roles))).all())
    direct = set(
        (
            await db_session.execute(
                select(ProjectMember.project_id, ProjectMember.user_id, ProjectMember.role)
            )
        ).all()
    )
    assert {(p, u, ProjectRole(r)) for p, u, r in effective} == {
        (p, u, ProjectRole(r)) for p, u, r in direct
    }
    audited = Counter(await db_session.scalars(select(AuditLog.action)))
    assert audited["user.external_ids_replace"] == 3
    assert audited["group.create"] == 5
    assert audited["group.member_add"] == 8
    assert audited["project.group_grant_add"] == 5

    # Ideas: every status and resolution, a few disagreements, some without an owner.
    ideas = list(await db_session.scalars(select(Idea)))
    assert {idea.status for idea in ideas} == set(IdeaStatus)
    assert {idea.resolution for idea in ideas} == {*Resolution, None}
    assert 2 <= sum(idea.high_disagreement for idea in ideas) <= 5
    assert sum(idea.owner_id is None for idea in ideas) >= 5
    scored = [idea.aggregate_score for idea in ideas if idea.aggregate_score is not None]
    assert min(scored) < Decimal("3.0") < Decimal("4.0") <= max(scored)

    # Evaluators: 2-5 on most evaluated ideas, a few that still need more.
    per_idea = Counter(await db_session.scalars(select(IdeaEvaluator.idea_id)))
    assert all(1 <= count <= 5 for count in per_idea.values())
    assert sum(count >= 2 for count in per_idea.values()) >= 0.85 * len(per_idea)

    # Due dates: some overdue, some upcoming, only on ideas with open evaluation.
    now = utcnow()
    due = [idea.evaluation_due_at for idea in ideas if idea.status is IdeaStatus.EVALUATING]
    assert any(at is not None and at < now for at in due)
    assert any(at is not None and at > now for at in due)

    # The cached aggregates are what a recompute gives.
    before = await _fingerprint(db_session)
    for project in projects.values():
        await recompute_aggregates(db_session, project_id=project.id)
    assert await _fingerprint(db_session) == before
    await db_session.rollback()
    users = {user.email: user for user in await db_session.scalars(select(User))}

    # Every timestamp is backdated: nothing happened in the last minutes or the future
    # (evaluation due dates and the account that existed before excepted).
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not isinstance(column.type, DateTime) or column.name in (
                "evaluation_due_at",
                "research_due_at",  # Phase 8b: TOOLS-12's is in 3 days
            ):
                continue
            latest = select(func.max(column))
            if table is User.__table__:
                latest = latest.where(User.id != carol)
            value = await db_session.scalar(latest)
            assert value is None or value < now - timedelta(minutes=4), column
    oldest = await db_session.scalar(select(func.min(Idea.created_at)))
    assert oldest is not None
    assert oldest < now - timedelta(days=30)

    # A second run leaves the data alone (a Helm hook on upgrade).
    again = await run_seed(settings)
    assert again.skipped is not None
    assert "--reset" in again.skipped
    assert await _fingerprint(db_session) == before

    # alice's My work: evaluations due (some overdue, one draft), owned ideas in several
    # statuses and recent activity.
    api = await login(users["alice@example.com"])
    work = (await api.get(f"{API}/me/work")).json()
    assert work["counts"]["evaluations_due"] == 5
    assert work["counts"]["evaluations_overdue"] == 2
    assert {item["state"] for item in work["evaluations_due"]} == {"invited", "draft"}
    assert len(work["owned"]) >= 4
    assert len(work["recent"]) == 20

    # Blind evaluation holds in the seeded data: alice still owes CUST-11, whose owner
    # sees a high-disagreement aggregate.
    blind = (await api.get(f"{API}/ideas/CUST-11")).json()
    assert blind["aggregate"] is None
    assert blind["score"] is None
    assert blind["score_hidden"] is True
    assert blind["high_disagreement"] is False
    hidden = (await api.get(f"{API}/ideas/CUST-11/evaluations")).json()
    assert hidden == {"items": [], "score_hidden": True}
    bob = await login(users["bob@example.com"])
    owner_view = (await bob.get(f"{API}/ideas/CUST-11")).json()
    assert owner_view["aggregate"]["count"] == 2
    assert owner_view["score"] is not None
    assert owner_view["high_disagreement"] is True

    # Phase 4: branding, Customer Innovation's public form and three public ideas,
    # numbered after every other demo idea (the demo's keys stay the same).
    assert (report.public_ideas, report.awaiting_moderation) == (3, 2)
    assert "3 ideas from the public form (2 waiting for review)" in report.summary()
    cust_keys = [
        f"CUST-{number}"
        for number, title in (
            await db_session.execute(
                select(Idea.number, Idea.title)
                .join(Project, Project.id == Idea.project_id)
                .where(Project.key == "CUST")
                .order_by(Idea.number)
            )
        ).all()
        if title in {public.title for public in PUBLIC_IDEAS}
    ]
    seeded = sum(idea.project == "CUST" for idea in IDEAS)
    assert cust_keys == [f"CUST-{seeded + n}" for n in (1, 2, 3)]
    await db_session.rollback()
    assert (await api.get(f"{API}/branding")).json()["app_name"] == "Soundings"
    global_branding = (await api.get(f"{API}/admin/branding")).json()
    assert global_branding["email_footer"] == GLOBAL_FOOTER
    project_branding = (await api.get(f"{API}/projects/customer-innovation/branding")).json()
    assert project_branding["primary_color"] == CUST_BRANDING["primary_color"]
    assert project_branding["logo"]["content_type"] == "image/svg+xml"
    assert project_branding["favicon"]["content_type"] == "image/svg+xml"
    logo = await api.get(project_branding["logo"]["url"])
    assert logo.status_code == 200
    assert logo.content.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns=')
    form = (await api.get(f"{API}/projects/customer-innovation/public-form")).json()
    assert (form["enabled"], form["moderation_required"]) == (True, True)
    assert form["awaiting_moderation"] == 2
    public = (await api.get(f"{API}/public/projects/customer-innovation")).json()
    assert public["branding"]["logo_url"] == project_branding["logo"]["url"]
    queue = (await api.get(f"{API}/projects/customer-innovation/moderation")).json()
    assert [item["title"] for item in queue["items"]] == [
        public.title for public in PUBLIC_IDEAS if public.approved_after is None
    ]
    approved = (await api.get(f"{API}/ideas/{cust_keys[0]}/submission")).json()
    assert approved["held_for"] is None
    assert approved["contact"] == {
        "email": "sam.okafor@example.org",
        "email_verified": True,
        "wants_updates": True,
    }
    assert audited["submission.approve"] == 1
    assert audited["branding.update"] == 1

    # The dev login lists the demo people, alice first.
    listed = (await api.get(f"{API}/auth/dev/users")).json()
    assert len(listed) == 12
    assert listed[0]["email"] == "alice@example.com"

    await _phase8_story(api, db_session)
    await _phase8b_story(login, users, db_session)


async def _phase8_story(api: Any, db: AsyncSession) -> None:
    """Phase 8 (contract-phase8 section 3.14): Internal Tools runs research before
    evaluation with a custom template, Sustainability before the proposal with Carbon
    impact, Customer Innovation keeps the defaults; two ideas in Research, the ideas past
    it answered, a proposal in each stepped project with the appendix."""
    steps = {
        slug: (await api.get(f"{API}/projects/{slug}/research")).json()
        for slug in ("customer-innovation", "internal-tools", "sustainability")
    }
    assert {slug: s["step"] for slug, s in steps.items()} == {
        "customer-innovation": "off",
        "internal-tools": "before_evaluation",
        "sustainability": "before_proposal",
    }
    assert [i["title"] for i in steps["internal-tools"]["items"]] == [
        "Not already being done elsewhere",
        "Departments or teams consulted",
        "Data protection considered",
    ]
    assert steps["internal-tools"]["ideas_in_research"] == 2
    templates = {
        slug: [
            s["key"]
            for s in (await api.get(f"{API}/projects/{slug}/proposal-template")).json()["sections"]
        ]
        for slug in ("customer-innovation", "internal-tools", "sustainability")
    }
    assert templates == {
        "customer-innovation": [
            "summary", "problem", "solution", "market", "cost", "benefits", "risks", "next_steps",
        ],
        "internal-tools": ["summary", "problem", "solution", "effort_rollout", "risks", "the_ask"],
        "sustainability": [
            "summary", "problem", "solution", "market", "cost", "benefits", "carbon_impact",
            "risks", "next_steps",
        ],
    }  # fmt: skip

    board = (await api.get(f"{API}/projects/internal-tools/board")).json()
    assert [c["status"] for c in board["columns"]] == [
        "new", "research", "evaluating", "shortlisted", "proposal", "closed",
    ]  # fmt: skip
    in_research = {card["title"]: card["research"] for card in board["columns"][1]["items"]}
    assert in_research == {
        "Internal status page for developer tooling": {
            "answered": 3, "total": 3, "required_open": 0,
        },
        "Chat command to request system access": {"answered": 1, "total": 3, "required_open": 1},
    }  # fmt: skip
    for column in board["columns"][2:5]:  # past Research: no badge, the checklist answered
        for card in column["items"]:
            assert card["research"] is None
            panel = (await api.get(f"{API}/ideas/{card['key']}/research")).json()
            assert panel["progress"]["required_open"] == 0, card["title"]
            owner = card["owner"]["id"]
            assert {i["answer"]["answered_by"]["id"] for i in panel["items"] if i["answer"]} == {
                owner
            }

    for slug, key in (("internal-tools", "effort_rollout"), ("sustainability", "carbon_impact")):
        [card] = [
            card
            for column in (await api.get(f"{API}/projects/{slug}/board")).json()["columns"]
            if column["status"] == "proposal"
            for card in column["items"]
        ]
        proposal = (await api.get(f"{API}/ideas/{card['key']}/proposal")).json()["proposal"]
        written = {s["key"]: s["body_md"] for s in proposal["sections"]}
        assert written[key], slug
        assert sum(bool(text) for text in written.values()) >= len(written) - 2, slug
        markdown = (await api.get(f"{API}/ideas/{card['key']}/proposal/markdown")).text
        assert "## Research and consultation" in markdown, slug
    green = (await api.get(f"{API}/projects/sustainability/board")).json()
    shortlisted = {c["title"]: c["research"] for c in green["columns"][2]["items"]}
    assert shortlisted["Heat pumps for the Bristol office"] == {
        "answered": 1,
        "total": 3,
        "required_open": 1,
    }
    await db.rollback()


async def _key(db: AsyncSession, title: str) -> str:
    row = (
        await db.execute(
            select(Project.key, Idea.number)
            .join(Project, Project.id == Idea.project_id)
            .where(Idea.title == title)
        )
    ).one()
    return f"{row[0]}-{row[1]}"


async def _phase8b_story(login: Login, users: dict[str, User], db: AsyncSession) -> None:
    """Phase 8b (contract-phase8b section 11): bob, not a member of the private Internal
    Tools, researches TOOLS-12 as its guest (due in 3 days, asked by dave); amara
    researches GREEN-6, which she owns (asked by alice); alice's GREEN-5 is overdue."""
    ids: dict[str, UUID] = dict((await db.execute(select(User.email, User.id))).all())
    tools12 = await _key(db, "Chat command to request system access")
    green6 = await _key(db, "Heat pumps for the Bristol office")
    green5 = await _key(db, "Move cloud workloads to a low-carbon region")
    assigned = set(await db.scalars(select(Idea.title).where(Idea.researcher_id.is_not(None))))
    await db.rollback()
    assert (tools12, green6, green5) == ("TOOLS-12", "GREEN-6", "GREEN-5")
    # Nothing else changes: TOOLS-11 keeps its owner doing the research.
    assert assigned == {
        "Chat command to request system access",
        "Heat pumps for the Bristol office",
        "Move cloud workloads to a low-carbon region",
    }

    def person(email: str) -> User:
        return User(id=ids[email])

    bob = await login(person("bob@example.com"))
    guest = (await bob.get(f"{API}/ideas/{tools12}")).json()
    assert guest["permissions"]["can_view_project"] is False
    assert guest["permissions"]["can_answer_research"] is True
    assert guest["researcher"]["id"] == str(ids["bob@example.com"])
    assert guest["score"] is None
    assert guest["evaluators"] == []
    due = datetime.fromisoformat(guest["research_due_at"])
    assert timedelta(days=2) < due - utcnow() < timedelta(days=4)
    assert (await bob.get(f"{API}/projects/internal-tools")).status_code == 404
    assert (await bob.get(f"{API}/ideas/{tools12}/proposal")).status_code == 404
    work = (await bob.get(f"{API}/me/work")).json()
    [item] = [i for i in work["research_to_do"] if i["idea"]["key"] == tools12]
    assert item["can_view_project"] is False
    assert item["progress"]["required_open"] == 1
    inbox = (await bob.get(f"{API}/me/notifications")).json()["items"]
    asked = [n for n in inbox if n["type"] == "researcher_assigned"]
    assert [n["idea"]["key"] for n in asked] == [tools12]
    assert asked[0]["actor"]["id"] == str(ids["dave@example.com"])

    amara = await login(person("amara@example.com"))
    panel = (await amara.get(f"{API}/ideas/{green6}/research")).json()
    assert panel["assignment"]["researcher"]["id"] == str(ids["amara@example.com"])
    inbox = (await amara.get(f"{API}/me/notifications")).json()["items"]
    assert [n["idea"]["key"] for n in inbox if n["type"] == "researcher_assigned"] == [green6]

    alice = await login(person("alice@example.com"))
    work = (await alice.get(f"{API}/me/work")).json()
    [late] = [i for i in work["research_to_do"] if i["idea"]["key"] == green5]
    assert late["overdue"] is True
    assert work["research_to_do"][0]["idea"]["key"] == green5  # overdue first
    assert work["counts"]["research_overdue"] >= 1


async def test_reset_replaces_existing_data(settings: Settings, db_session: AsyncSession) -> None:
    stranger = await make_user(db_session, "Stranger Danger", email="stranger@example.org")
    stranger_id = stranger.id
    await make_project(
        db_session, slug="old-project", key="OLD", members={stranger: ProjectRole.ADMIN}
    )

    skipped = await run_seed(settings)
    assert skipped.skipped is not None
    assert await db_session.scalar(select(func.count()).select_from(Idea)) == 0
    await db_session.rollback()  # end the read transaction: TRUNCATE waits for it
    # Someone who is not a demo person: --reset alone refuses (code review F8).
    with pytest.raises(SeedRefused, match="--force"):
        await run_seed(settings, reset=True)
    assert await db_session.scalar(select(User.email).where(User.id == stranger_id))
    await db_session.rollback()

    report = await run_seed(settings, reset=True, force=True)

    assert report.skipped is None
    assert (report.users, report.projects, report.ideas) == (12, 3, 48)
    emails = set(await db_session.scalars(select(User.email)))
    assert "stranger@example.org" not in emails
    assert await db_session.scalar(select(Project.id).where(Project.key == "OLD")) is None
    # The migration history and the job queue are not application data.
    assert await db_session.scalar(text("SELECT count(*) FROM alembic_version")) == 1
    submitted = await db_session.scalar(
        select(func.count())
        .select_from(Evaluation)
        .where(Evaluation.status == EvaluationStatus.SUBMITTED)
    )
    assert submitted == report.evaluations_submitted
