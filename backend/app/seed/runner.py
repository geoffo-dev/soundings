"""Play :mod:`app.seed.content` through the application services.

Every change goes through the same service functions and authorisation checks as the
API (so watchers, activity, audit entries, vote counts and cached aggregates are right
by construction), acting as the person the story says did it.

**Backdating.** The services stamp rows with the current time. The story is a list of
steps with a time in the past; the steps run in time order, each followed by a shift
of every timestamp the step wrote (``>=`` the moment the step started) back to the
step's time, keeping their order within the step. Evaluation due dates are the one
future-facing value a step writes; they are set explicitly instead. Everything runs in
one transaction: a failure leaves the database as it was.

**Notifications.** Each step is one unit of work: its activity events fan out to the
in-app inbox right after it (so the notifications are backdated with it), in-app only
(``email_mode = off``, no outbox rows: seeding never sends mail). Older notifications
are marked read and a few people get non-default email preferences, so the demo inbox
and Settings -> Notifications look lived in.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import (
    DateTime,
    Interval,
    Select,
    bindparam,
    case,
    exists,
    func,
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import Rule, load_project, require
from app.config import DatabaseSettings
from app.domain.principal import Principal
from app.models import (
    Base,
    Comment,
    Evaluation,
    EvaluationStatus,
    Idea,
    IdeaEvaluator,
    IdeaStatus,
    IdeaVote,
    Project,
    ProjectRole,
    Resolution,
    User,
)
from app.models.base import utcnow
from app.models.enums import NotificationMode, NotificationType
from app.models.group import Group, GroupMembership
from app.models.notification import Notification
from app.models.user import UserExternalId
from app.notifications import fanout
from app.notifications import preferences as notification_preferences
from app.schemas.admin_users import ExternalIdIn, ExternalIdsReplace
from app.schemas.comments import CommentCreate
from app.schemas.evaluations import MyEvaluationIn, MyScoreIn
from app.schemas.groups import GroupCreate, GroupMemberAdd, ProjectGroupGrantAdd
from app.schemas.ideas import EvaluatorsAdd, IdeaCreate, StatusChange
from app.schemas.projects import MemberAdd, ProjectCreate, ProjectUpdate
from app.schemas.rubric import RubricUpdate
from app.seed.content import (
    GROUPS,
    IDEAS,
    PEOPLE,
    PROJECTS,
    GroupSeed,
    IdeaSeed,
    Person,
    ProjectSeed,
    Review,
)
from app.services import (
    admin_groups,
    admin_users,
    comments,
    evaluations,
    ideas,
    project_groups,
    projects,
    votes,
)
from app.services.scoring import active_criteria

__all__ = [
    "SeedRefused",
    "SeedReport",
    "check_allowed",
    "check_reset_allowed",
    "seed_demo_data",
    "wipe_app_data",
]

logger = logging.getLogger("soundings.seed")

DEMO_ID_NAMESPACE: Final = uuid.UUID("1f0c7a52-5d1e-4c1b-9d1e-50d1a6e0de70")
"""Users get uuid5(namespace, email) ids, so they are the same after every reseed."""

_LOCK_KEY: Final = 0x5EED_50D1
"""Advisory lock: concurrent seeds (two hook Jobs) run one after the other."""

_MARGIN: Final = timedelta(minutes=5)
"""The latest step happens at least this long before the seed runs."""

_FUTURE_COLUMNS: Final = frozenset({"ideas.evaluation_due_at"})
"""Timestamps a step sets to a future value on purpose: never shifted."""

_READ_AFTER: Final = timedelta(days=3)
"""Demo notifications older than this are read (an hour or two after they arrived)."""

DEMO_PREFERENCES: Final = {
    "bob": {NotificationType.COMMENT: NotificationMode.OFF},
    "carol": {
        NotificationType.STATUS_CHANGED: NotificationMode.IMMEDIATE,
        NotificationType.MENTION: NotificationMode.DIGEST,
    },
}
"""A few people who changed their email preferences (Settings -> Notifications)."""


class SeedRefused(Exception):
    """Seeding is not allowed here (production, or a reset of a database with real
    people, without ``--force``)."""


@dataclass
class SeedReport:
    """What the seed did. ``skipped`` explains why nothing was written."""

    skipped: str | None = None
    users: int = 0
    groups: int = 0
    projects: int = 0
    ideas: int = 0
    evaluations_submitted: int = 0
    evaluations_draft: int = 0
    evaluators_pending: int = 0
    comments: int = 0
    votes: int = 0

    def summary(self) -> str:
        if self.skipped:
            return self.skipped
        return (
            f"Seeded {self.users} users, {self.projects} projects and {self.ideas} ideas: "
            f"{self.evaluations_submitted} submitted evaluations, {self.evaluations_draft} "
            f"drafts, {self.evaluators_pending} evaluators yet to start, {self.comments} "
            f"comments and {self.votes} votes; {self.groups} groups."
        )


def check_allowed(settings: DatabaseSettings, *, force: bool = False) -> None:
    """Demo data is for development and demos: refuse production unless forced."""
    if settings.is_production and not force:
        raise SeedRefused(
            "Refusing to seed demo data: SOUNDINGS_ENVIRONMENT is production. "
            "Use --force if you really mean it."
        )


async def check_reset_allowed(db: AsyncSession, *, force: bool = False) -> None:
    """``--reset`` empties every table, so without ``--force`` it only runs on a
    database whose people are all demo people (by email, so SSO sign-ins of the demo
    accounts count) or that has none: a development, demo or e2e database.

    The environment check alone fails open: ``SOUNDINGS_ENVIRONMENT`` defaults to
    development, so a hand-run ``seed --reset`` pointed at a real database would
    otherwise wipe it.
    """
    if force:
        return
    demo_emails = [person.email.lower() for person in PEOPLE]
    if await db.scalar(select(exists().where(func.lower(User.email).not_in(demo_emails)))):
        raise SeedRefused(
            "Refusing to --reset: the database has people who are not in the demo data, "
            "so it may hold real data. Use --force if you really mean to delete everything."
        )


async def wipe_app_data(db: AsyncSession) -> None:
    """Empty every application table (not the migration history or the job queue)."""
    preparer = db.get_bind().dialect.identifier_preparer
    tables = ", ".join(preparer.format_table(table) for table in Base.metadata.sorted_tables)
    await db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


async def seed_demo_data(
    db: AsyncSession, *, reset: bool = False, force: bool = False, now: datetime | None = None
) -> SeedReport:
    """Load the demo data in the caller's transaction (the caller commits).

    Without ``reset`` a database that already has projects is left alone (a Helm hook
    re-running on upgrade is a no-op). ``reset`` wipes application data first, if
    :func:`check_reset_allowed` (``force`` skips that check).
    """
    await db.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))
    if reset:
        await check_reset_allowed(db, force=force)
        await wipe_app_data(db)
    elif await db.scalar(select(exists().where(Project.id.is_not(None)))):
        return SeedReport(
            skipped=(
                "The database already has projects, so no demo data was loaded. "
                "Use --reset to replace everything with the demo data."
            )
        )
    player = _Player(db, now or utcnow())
    await player.play()
    return await _report(db)


async def _report(db: AsyncSession) -> SeedReport:
    async def count(statement: Select[int]) -> int:
        return int(await db.scalar(statement) or 0)

    evaluations_by_status = select(func.count()).select_from(Evaluation)
    pending = (
        select(func.count())
        .select_from(IdeaEvaluator)
        .where(
            ~exists().where(
                Evaluation.idea_id == IdeaEvaluator.idea_id,
                Evaluation.evaluator_id == IdeaEvaluator.user_id,
            )
        )
    )
    return SeedReport(
        users=await count(select(func.count()).select_from(User)),
        groups=await count(select(func.count()).select_from(Group)),
        projects=await count(select(func.count()).select_from(Project)),
        ideas=await count(select(func.count()).select_from(Idea)),
        evaluations_submitted=await count(
            evaluations_by_status.where(Evaluation.status == EvaluationStatus.SUBMITTED)
        ),
        evaluations_draft=await count(
            evaluations_by_status.where(Evaluation.status == EvaluationStatus.DRAFT)
        ),
        evaluators_pending=await count(pending),
        comments=await count(select(func.count()).select_from(Comment)),
        votes=await count(select(func.count()).select_from(IdeaVote)),
    )


# --- Backdating ----------------------------------------------------------------------------
def _retime_statement() -> Select[int]:
    """Shift every timestamp written since ``:mark`` by ``:delta``, in one statement
    (a data-modifying CTE per table).

    Derived from the models, so tables added in later phases are covered too.
    """
    mark = bindparam("mark", type_=DateTime(timezone=True))
    delta = bindparam("delta", type_=Interval())
    updates = []
    for table in Base.metadata.sorted_tables:
        columns = [
            column
            for column in table.columns
            if isinstance(column.type, DateTime)
            and f"{table.name}.{column.name}" not in _FUTURE_COLUMNS
        ]
        if columns:
            updates.append(
                update(table)
                .where(or_(*(column >= mark for column in columns)))
                .values(
                    {
                        column.name: case((column >= mark, column + delta), else_=column)
                        for column in columns
                    }
                )
                .returning(literal(1))
                .cte(f"retime_{table.name}")
            )
    return select(literal(1)).add_cte(*updates)


# --- The story ---------------------------------------------------------------------------
Action = Callable[[], Awaitable[None]]


@dataclass(order=True)
class _Step:
    at: datetime
    order: int
    label: str = field(compare=False)
    action: Action = field(compare=False)


class _Player:
    def __init__(self, db: AsyncSession, now: datetime) -> None:
        self.db = db
        self.now = now
        self.steps: list[_Step] = []
        self.user_ids: dict[str, uuid.UUID] = {}
        self.slugs: dict[str, str] = {project.key: project.slug for project in PROJECTS}
        self.stewards: dict[str, str] = {project.key: project.admin for project in PROJECTS}
        self.windows = {project.key: project.default_evaluation_days for project in PROJECTS}
        self.criteria: dict[str, list[uuid.UUID]] = {}
        self.keys: dict[int, str] = {}

    # -- helpers --------------------------------------------------------------------------
    def days_ago(self, days: float) -> datetime:
        return self.now - timedelta(days=days)

    def add(self, at: datetime, label: str, action: Action) -> None:
        if at > self.now - _MARGIN:
            raise ValueError(f"seed content: {label!r} would happen in the future")
        self.steps.append(_Step(at, len(self.steps), label, action))

    async def principal(self, username: str) -> Principal:
        user = await self.db.get(User, self.user_ids[username])
        assert user is not None  # noqa: S101 - created by _users
        return Principal(user=user)

    async def load(self, username: str, index: int) -> tuple[Principal, ideas.LoadedIdea]:
        principal = await self.principal(username)
        loaded = await ideas.load_idea(self.db, principal, self.keys[index], for_update=True)
        return principal, loaded

    async def criteria_of(self, project_key: str) -> list[uuid.UUID]:
        if project_key not in self.criteria:
            slug = self.slugs[project_key]
            project_id = await self.db.scalar(select(Project.id).where(Project.slug == slug))
            assert project_id is not None  # noqa: S101 - created by an earlier step
            rubric = (await active_criteria(self.db, [project_id]))[project_id]
            self.criteria[project_key] = [criterion.id for criterion in rubric]
        return self.criteria[project_key]

    # -- playing --------------------------------------------------------------------------
    async def play(self) -> None:
        await self._users()
        self._preferences()
        for project in PROJECTS:
            self._project(project)
        for person in PEOPLE:
            self._external_id(person)
        for group in GROUPS:
            self._group(group)
        for index, idea in enumerate(IDEAS):
            self._idea(index, idea)
        retime = _retime_statement()
        for step in sorted(self.steps):
            mark = utcnow()
            try:
                await step.action()
                await self.db.flush()
                # The step's notifications, in-app only (no settings: no email).
                await fanout.fan_out(self.db, settings=None)
            except Exception as exc:
                exc.add_note(f"seed step: {step.label}")
                raise
            await self.db.execute(retime, {"mark": mark, "delta": step.at - mark})
            # Drop every loaded object: the next step reads the backdated values.
            self.db.expunge_all()
        await self._inbox()
        logger.info("demo data loaded", extra={"steps": len(self.steps)})

    async def _inbox(self) -> None:
        """Read what is older than a few days; set the demo email preferences."""
        await self.db.execute(
            update(Notification)
            .where(Notification.created_at < self.now - _READ_AFTER)
            .values(read_at=Notification.created_at + timedelta(minutes=90))
            .execution_options(synchronize_session=False)
        )

    async def _users(self) -> None:
        """People are not created through the API (sign-in creates them from Phase 2);
        existing accounts with the same email are reused."""
        for person in PEOPLE:
            user = await self.db.scalar(
                select(User).where(func.lower(User.email) == person.email.lower())
            )
            if user is None:
                joined = self.days_ago(person.joined_days_ago)
                user = User(
                    id=uuid.uuid5(DEMO_ID_NAMESPACE, person.email),
                    email=person.email,
                    display_name=person.name,
                    created_at=joined,
                    updated_at=joined,
                )
                self.db.add(user)
            user.is_active = True
            user.is_platform_admin = user.is_platform_admin or person.platform_admin
            self.user_ids[person.username] = user.id
        await self.db.flush()

    def _project(self, seed: ProjectSeed) -> None:
        created = self.days_ago(seed.created_days_ago)
        platform_admin = self._platform_admin()

        async def create() -> None:
            principal = await self.principal(platform_admin)
            require(principal, Rule.PROJECT_CREATE)
            body = ProjectCreate(
                name=seed.name,
                slug=seed.slug,
                key=seed.key,
                description=seed.description,
                visibility=seed.visibility,
                admin_user_id=self.user_ids[seed.admin],
            )
            await projects.create_project(self.db, principal, body)

        self.add(created, f"create project {seed.key}", create)

        if seed.status_labels or seed.default_evaluation_days != 7:

            async def configure() -> None:
                principal = await self.principal(seed.admin)
                project, resource = await load_project(
                    self.db, principal, seed.slug, Rule.PROJECT_EDIT_SETTINGS, for_update=True
                )
                body = ProjectUpdate.model_validate(
                    {
                        "default_evaluation_days": seed.default_evaluation_days,
                        "status_labels": dict(seed.status_labels) or None,
                    }
                )
                await projects.update_project(self.db, principal, project, resource, body)

            self.add(created + timedelta(minutes=10), f"configure {seed.key}", configure)

        if seed.rubric is not None:
            rubric = seed.rubric

            async def customise_rubric() -> None:
                principal = await self.principal(seed.admin)
                project, _ = await load_project(
                    self.db, principal, seed.slug, Rule.PROJECT_EDIT_RUBRIC, for_update=True
                )
                current = (await active_criteria(self.db, [project.id]))[project.id]
                by_name = {criterion.name: criterion.id for criterion in current}
                body = RubricUpdate.model_validate(
                    {
                        "criteria": [
                            {
                                "id": by_name.get(criterion.name),
                                "name": criterion.name,
                                "description": criterion.description,
                                "weight": criterion.weight,
                                "inverted": criterion.inverted,
                                "guidance": dict(criterion.guidance),
                            }
                            for criterion in rubric
                        ]
                    }
                )
                await projects.replace_rubric(self.db, principal, project, body)

            self.add(created + timedelta(minutes=20), f"rubric {seed.key}", customise_rubric)

        for position, (username, role) in enumerate(seed.members):

            async def add_member(username: str = username, role: ProjectRole = role) -> None:
                principal = await self.principal(seed.admin)
                project, _ = await load_project(
                    self.db, principal, seed.slug, Rule.PROJECT_MANAGE_MEMBERS, for_update=True
                )
                body = MemberAdd.model_validate({"user_id": self.user_ids[username], "role": role})
                await projects.add_member(self.db, principal, project, body)

            at = created + timedelta(hours=1 + 6 * position)
            self.add(at, f"add {username} to {seed.key}", add_member)

    def _preferences(self) -> None:
        for position, (username, changes) in enumerate(DEMO_PREFERENCES.items()):

            async def choose(
                username: str = username,
                changes: dict[NotificationType, NotificationMode] = changes,
            ) -> None:
                await notification_preferences.update(self.db, self.user_ids[username], changes)

            self.add(self.days_ago(20 - position), f"email preferences of {username}", choose)

    def _platform_admin(self) -> str:
        return next(person.username for person in PEOPLE if person.platform_admin)

    def _external_id(self, person: Person) -> None:
        """The platform admin records the person's employee number (as pre-creating
        them for SSO would), unless they or someone else already has it."""
        if person.employee_no is None:
            return
        employee_no = person.employee_no

        async def set_external_id() -> None:
            principal = await self.principal(self._platform_admin())
            require(principal, Rule.PLATFORM_MANAGE_USERS)
            user_id = self.user_ids[person.username]
            existing = await self.db.scalar(
                select(UserExternalId.user_id).where(
                    or_(
                        (UserExternalId.user_id == user_id)
                        & (UserExternalId.kind == "employee_no"),
                        (UserExternalId.kind == "employee_no")
                        & (func.lower(UserExternalId.value) == employee_no.lower()),
                    )
                )
            )
            if existing is not None:
                return
            user = await self.db.get(User, user_id)
            assert user is not None  # noqa: S101 - created by _users
            body = ExternalIdsReplace(
                external_ids=[ExternalIdIn(kind="employee_no", value=employee_no)]
            )
            await admin_users.replace_external_ids(self.db, principal, user, body)

        at = self.days_ago(48) + timedelta(minutes=10 * PEOPLE.index(person))
        self.add(at, f"employee number of {person.username}", set_external_id)

    def _group(self, seed: GroupSeed) -> None:
        """Create the group (reusing one with the same name), add its manual members,
        then each project's admin grants it a role."""
        created = self.days_ago(seed.created_days_ago)

        async def group_id() -> uuid.UUID | None:
            found: uuid.UUID | None = await self.db.scalar(
                select(Group.id).where(func.lower(Group.name) == seed.name.lower())
            )
            return found

        async def create() -> None:
            principal = await self.principal(self._platform_admin())
            require(principal, Rule.PLATFORM_MANAGE_GROUPS)
            if await group_id() is not None:
                return
            body = GroupCreate(
                name=seed.name,
                description=seed.description,
                sync_mode=seed.sync_mode,
                idp_values=list(seed.idp_values),
            )
            await admin_groups.create_group(self.db, principal, body)

        self.add(created, f"create group {seed.name}", create)

        for position, username in enumerate(seed.members):

            async def add_member(username: str = username) -> None:
                principal = await self.principal(self._platform_admin())
                require(principal, Rule.PLATFORM_MANAGE_GROUPS)
                found = await group_id()
                assert found is not None  # noqa: S101 - created by an earlier step
                user_id = self.user_ids[username]
                if await self.db.get(GroupMembership, (found, user_id)) is not None:
                    return
                group = await admin_groups.get_group(self.db, found)
                body = GroupMemberAdd(user_id=user_id)
                await admin_groups.add_member(self.db, principal, group, body)

            at = created + timedelta(minutes=20 + 10 * position)
            self.add(at, f"add {username} to group {seed.name}", add_member)

        for position, (project_key, role) in enumerate(seed.grants):

            async def add_grant(project_key: str = project_key, role: ProjectRole = role) -> None:
                steward = self.stewards[project_key]
                principal = await self.principal(steward)
                project, _ = await load_project(
                    self.db,
                    principal,
                    self.slugs[project_key],
                    Rule.PROJECT_MANAGE_MEMBERS,
                    for_update=True,
                )
                found = await group_id()
                assert found is not None  # noqa: S101 - created by an earlier step
                body = ProjectGroupGrantAdd(group_id=found, role=role)
                await project_groups.add_grant(self.db, principal, project, body)

            at = created + timedelta(hours=2 + position)
            self.add(at, f"grant {seed.name} a role in {project_key}", add_grant)

    def _idea(self, index: int, seed: IdeaSeed) -> None:
        # A deterministic time of day per idea (within 2.5 hours either way), so ideas
        # are not all submitted at the same minute of the day.
        submitted = self.days_ago(seed.age) + timedelta(minutes=(index * 97) % 300 - 150)
        label = f"{seed.project} {seed.title!r}"

        def after(days: float) -> datetime:
            return submitted + timedelta(days=days)

        async def create() -> None:
            principal = await self.principal(seed.submitter)
            project, _ = await load_project(
                self.db, principal, self.slugs[seed.project], Rule.IDEA_CREATE
            )
            body = IdeaCreate(
                title=seed.title,
                summary=seed.summary,
                description_md=seed.description,
                tags=list(seed.tags),
            )
            idea = await ideas.create_idea(self.db, principal, project, body)
            self.keys[index] = f"{project.key}-{idea.number}"

        self.add(submitted, f"submit {label}", create)

        if seed.owner is not None:
            owner = seed.owner
            steward = self.stewards[seed.project]

            async def take_ownership() -> None:
                if seed.volunteered or owner == steward:
                    principal, loaded = await self.load(owner, index)
                    await ideas.volunteer(self.db, principal, loaded)
                else:
                    principal, loaded = await self.load(steward, index)
                    await ideas.set_owner(self.db, principal, loaded, self.user_ids[owner])

            self.add(after(seed.owner_after), f"owner of {label}", take_ownership)

        for remark in seed.remarks:

            async def comment(author: str = remark.author, body: str = remark.body) -> None:
                principal, loaded = await self.load(author, index)
                await comments.create_comment(
                    self.db, principal, loaded, CommentCreate(body_md=body)
                )

            self.add(after(remark.after), f"comment on {label}", comment)

        for position, voter in enumerate(seed.voters):

            async def vote(voter: str = voter) -> None:
                principal, loaded = await self.load(voter, index)
                await votes.set_vote(self.db, principal, loaded, voted=True)

            share = (position + 1) / (len(seed.voters) + 1)
            self.add(after(seed.age * share * 0.9), f"{voter} votes for {label}", vote)

        if seed.reviews:
            self._evaluation(index, seed, label, after(seed.invite_after))

    def _evaluation(self, index: int, seed: IdeaSeed, label: str, invited: datetime) -> None:
        owner = seed.owner
        if owner is None:
            raise ValueError(f"seed content: {label} has evaluators but no owner")
        window = timedelta(days=self.windows[seed.project])

        async def invite() -> None:
            principal, loaded = await self.load(owner, index)
            people = [review.evaluator for review in seed.reviews] + list(seed.dropped)
            body = EvaluatorsAdd(user_ids=[self.user_ids[person] for person in people])
            first = loaded.idea.evaluation_due_at is None
            await evaluations.add_evaluators(self.db, principal, loaded, body)
            if first:  # the default window, counted from the (backdated) invitation
                loaded.idea.evaluation_due_at = invited + window

        self.add(invited, f"invite evaluators to {label}", invite)
        self._status(index, owner, invited + timedelta(minutes=15), IdeaStatus.EVALUATING, label)

        for person in seed.dropped:

            async def drop(person: str = person) -> None:
                principal, loaded = await self.load(owner, index)
                await evaluations.remove_evaluator(
                    self.db, principal, loaded, self.user_ids[person]
                )

            self.add(invited + timedelta(days=1), f"remove {person} from {label}", drop)

        if seed.due_extension is not None:
            extended_after, new_window = seed.due_extension

            async def extend() -> None:
                principal, loaded = await self.load(owner, index)
                due = invited + timedelta(days=new_window)
                await evaluations.set_due_date(self.db, principal, loaded, due)

            self.add(invited + timedelta(days=extended_after), f"extend {label}", extend)

        last = invited
        for position, review in enumerate(seed.reviews):
            if not review.scores:
                continue
            at = invited + timedelta(days=review.after or 0.7 + 1.3 * position)
            self._review(index, seed.project, review, review.scores, at, label)
            last = max(last, at)
            if review.revised is not None:
                revised_at = at + timedelta(days=review.revised_after)
                self._review(index, seed.project, review, review.revised, revised_at, label)
                last = max(last, revised_at)

        self._decide(index, seed, owner, last, label)

    def _review(
        self, index: int, project: str, review: Review, scores: str, at: datetime, label: str
    ) -> None:
        async def save() -> None:
            principal, loaded = await self.load(review.evaluator, index)
            criteria = await self.criteria_of(project)
            if len(scores) != len(criteria):
                raise ValueError(f"seed content: {label} needs {len(criteria)} scores")
            body = MyEvaluationIn(
                scores=[
                    MyScoreIn(criterion_id=criterion, score=int(digit))
                    for criterion, digit in zip(criteria, scores, strict=True)
                    if digit != "-"
                ],
                recommendation=review.recommendation,
                comment=review.comment,
                submit=not review.draft,
            )
            await evaluations.save_my_evaluation(self.db, principal, loaded, body)

        self.add(at, f"{review.evaluator} evaluates {label}", save)

    def _decide(self, index: int, seed: IdeaSeed, owner: str, last: datetime, label: str) -> None:
        """Status changes after the evaluations, up to the idea's final status."""
        final = (seed.status, seed.resolution)
        stages = [IdeaStatus.SHORTLISTED, IdeaStatus.PROPOSAL, IdeaStatus.CLOSED]
        path: list[tuple[IdeaStatus, Resolution | None]]
        if seed.status not in stages:
            path = []
        elif seed.resolution is Resolution.REJECTED:
            path = [final]  # rejected straight from evaluating
        elif seed.resolution is Resolution.PARKED:
            path = [(IdeaStatus.SHORTLISTED, None), final]
        else:
            path = [(status, None) for status in stages[: stages.index(seed.status)]] + [final]
        at = last + timedelta(days=1)
        for status, resolution in path:
            if status is IdeaStatus.SHORTLISTED:

                async def close_evaluation() -> None:
                    principal, loaded = await self.load(owner, index)
                    await evaluations.set_evaluation_closed(self.db, principal, loaded, closed=True)

                self.add(
                    at - timedelta(minutes=30), f"close evaluation of {label}", close_evaluation
                )
            self._status(index, owner, at, status, label, resolution)
            at += timedelta(days=3 if status is IdeaStatus.SHORTLISTED else 2.5)

    def _status(
        self,
        index: int,
        owner: str,
        at: datetime,
        status: IdeaStatus,
        label: str,
        resolution: Resolution | None = None,
    ) -> None:
        async def change() -> None:
            principal, loaded = await self.load(owner, index)
            body = StatusChange(status=status, resolution=resolution)
            await ideas.change_status(self.db, principal, loaded, body)

        self.add(at, f"{label} -> {status}", change)
