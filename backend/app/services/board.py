"""The list and the board (contract section 3.9): filters, sorts and keyset cursors.

This is the one idea query builder for growing idea lists: ``list_ideas``, the
board, "load more" of a board column and of a My work group all page with the same
:class:`IdeaSort` and cursor format, so a board column's ``next_cursor`` works with
``list_ideas?status=<column>``.

Blind evaluation: ``sort=score`` orders by :func:`app.authz.visible_aggregate_score`
(null for a pending evaluator, so the idea sorts with the unscored ones, last in both
directions) and the cursor carries that **masked** value, never the raw score. The
``high_disagreement`` filter uses :func:`app.authz.visible_high_disagreement`.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Row,
    Select,
    String,
    and_,
    bindparam,
    column,
    exists,
    func,
    or_,
    select,
    true,
    tuple_,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import (
    viewable_ideas,
    visible_aggregate_score,
    visible_high_disagreement,
    visible_last_activity,
)
from app.domain.idea_keys import parse_idea_key
from app.domain.labels import resolved_labels
from app.domain.principal import Principal
from app.domain.scoring import MAX_SCORE, MIN_SCORE
from app.models.enums import IdeaStatus, ProjectRole, Resolution
from app.models.idea import Idea, IdeaEvaluator, IdeaTag
from app.models.project import Project, Tag
from app.pagination import InvalidCursorProblem, decode_cursor, encode_cursor
from app.schemas.ideas import Board, BoardColumn, IdeaPage, IdeaSort, ResolutionCounts
from app.schemas.research import CANONICAL_STATUS_ORDER, lifecycle
from app.services.summaries import (
    IDEA_COLUMNS,
    IdeaData,
    IdeaRow,
    build_summaries,
    summary_columns,
)
from app.services.users import escape_like

__all__ = [
    "LIFECYCLE",
    "IdeaFilter",
    "Sort",
    "board_statement",
    "count_ideas",
    "fetch_page",
    "get_board",
    "idea_filter_clauses",
    "list_ideas",
    "page_statement",
    "pages_by_status",
]

LIFECYCLE: Final = CANONICAL_STATUS_ORDER
"""Every status in the canonical order (Research after New, closed last): views across
projects (My work's owned groups). A project's board uses its own lifecycle
(:func:`app.schemas.research.lifecycle`): Research only while its step is on."""

OwnerFilter = UUID | Literal["me", "none"]


@dataclass(frozen=True, slots=True)
class IdeaFilter:
    """The list's filters; they combine with AND, values within one filter with OR."""

    statuses: Sequence[IdeaStatus] = ()
    resolutions: Sequence[Resolution] = ()
    owner: OwnerFilter | None = None
    tags: Sequence[str] = ()
    needs_evaluators: bool = False
    high_disagreement: bool = False
    q: str | None = None


# --- Sorts and cursors ---------------------------------------------------------------------
# Cursors are not signed, so decoded values are kept to what the columns hold: anything
# else would reach PostgreSQL and fail there (numeric overflow, a 500).
_MAX_INT: Final = 2**31 - 1


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("a score is a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("not a decimal") from exc
    if not number.is_finite() or not MIN_SCORE <= number <= MAX_SCORE:
        raise ValueError("not an aggregate score")
    return number


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("a timestamp is a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamps carry an offset")
    try:
        parsed.astimezone(UTC)
    except OverflowError as exc:  # e.g. 0001-01-01T00:00+05:00
        raise ValueError("timestamp out of range") from exc
    return parsed


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("not an integer")
    if not 0 <= value <= _MAX_INT:
        raise ValueError("not a vote count")
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("not a string")
    return value


@dataclass(frozen=True, slots=True)
class _Field:
    column: Callable[[Principal], ColumnElement[Any]]
    decode: Callable[[object], Any]
    nullable: bool = False


_FIELDS: Final[dict[str, _Field]] = {
    "score": _Field(visible_aggregate_score, _decimal, nullable=True),
    "updated": _Field(lambda _: Idea.last_activity_at.expression, _datetime),
    "created": _Field(lambda _: Idea.created_at.expression, _datetime),
    "votes": _Field(lambda _: Idea.vote_count.expression, _int),
    "title": _Field(lambda _: func.lower(Idea.title), _str),
}


@dataclass(frozen=True, slots=True)
class Sort:
    """``score``, ``updated`` (``last_activity_at``), ``created``, ``votes`` or ``title``
    (case-insensitive); ``-`` = descending. Ties break on ``id`` in the same direction;
    null (unscored or hidden) scores come last in both directions."""

    token: IdeaSort
    guests: bool = False
    """Phase 8b guest review L1: the list may show ideas the viewer sees as their guest
    researcher (``researched_ideas``: MCP ``search_ideas``), so ``updated`` sorts on
    :func:`app.authz.visible_last_activity`, the value those ideas show. Project-scoped
    lists never show one and keep the column (and its indexes)."""

    @property
    def descending(self) -> bool:
        return self.token.startswith("-")

    @property
    def _field(self) -> _Field:
        return _FIELDS[self.token.lstrip("-")]

    def value(self, principal: Principal) -> ColumnElement[Any]:
        """The sort value as the viewer may see it (masked for ``score``; for
        ``updated`` where the list may show a guest's ideas)."""
        if self.guests and self.token.lstrip("-") == "updated":
            return visible_last_activity(principal)
        return self._field.column(principal)

    def order_by(
        self, value: ColumnElement[Any], *, tie: ColumnElement[UUID] | Any = Idea.id
    ) -> list[ColumnElement[Any]]:
        if self.descending:
            first, last = value.desc(), tie.desc()
        else:
            first, last = value.asc(), tie.asc()
        return [first.nulls_last() if self._field.nullable else first, last]

    def after(self, value: ColumnElement[Any], cursor: str) -> ColumnElement[bool]:
        """Rows after the cursor's position in this order (keyset)."""
        position, last_id = self.decode(cursor)
        beyond = operator.lt if self.descending else operator.gt
        if not self._field.nullable:
            return beyond(tuple_(value, Idea.id), tuple_(position, last_id))  # type: ignore[no-any-return]
        if position is None:  # already among the nulls, which come last
            return and_(value.is_(None), beyond(Idea.id, last_id))
        return or_(
            value.is_(None),
            beyond(value, position),
            and_(value == position, beyond(Idea.id, last_id)),
        )

    def encode(self, value: Any, idea_id: UUID) -> str:
        if isinstance(value, Decimal):
            value = str(value)
        return encode_cursor({"sort": self.token, "v": value, "id": idea_id})

    def decode(self, cursor: str) -> tuple[Any, UUID]:
        """The cursor's (value, id); 400 ``invalid_cursor`` if malformed or from
        another sort."""
        data = decode_cursor(cursor)
        try:
            if data.get("sort") != self.token or set(data) != {"sort", "v", "id"}:
                raise ValueError("foreign cursor")
            value = data["v"]
            decoded = None if value is None and self._field.nullable else self._field.decode(value)
            return decoded, UUID(_str(data["id"]))
        except (ValueError, TypeError) as exc:
            raise InvalidCursorProblem from exc


# --- Filters ------------------------------------------------------------------------------
def _has_any_tag(names: Sequence[str]) -> ColumnElement[bool]:
    return exists(
        select(1)
        .select_from(IdeaTag)
        .join(Tag, Tag.id == IdeaTag.tag_id)
        .where(
            IdeaTag.idea_id == Idea.id,
            or_(*(func.lower(Tag.name) == func.lower(name) for name in names)),
        )
    )


def _text_matches(project: Project, q: str) -> ColumnElement[bool]:
    pattern = f"%{escape_like(q)}%"
    matches: list[ColumnElement[bool]] = [
        Idea.title.ilike(pattern, escape="\\"),
        Idea.summary.ilike(pattern, escape="\\"),
    ]
    key = parse_idea_key(q)
    if key is not None and key.project_key == project.key:
        matches.append(Idea.number == key.number)
    return or_(*matches)


def idea_filter_clauses(
    principal: Principal, project: Project, filters: IdeaFilter
) -> list[ColumnElement[bool]]:
    """``WHERE`` clauses for the project's ideas the principal can view, filtered."""
    clauses: list[ColumnElement[bool]] = [Idea.project_id == project.id, viewable_ideas(principal)]
    if filters.statuses:
        clauses.append(Idea.status.in_(list(filters.statuses)))
    if filters.resolutions:
        clauses.append(Idea.resolution.in_(list(filters.resolutions)))
    if filters.owner == "me":
        clauses.append(Idea.owner_id == principal.user_id)
    elif filters.owner == "none":
        clauses.append(Idea.owner_id.is_(None))
    elif isinstance(filters.owner, UUID):
        clauses.append(Idea.owner_id == filters.owner)
    if filters.tags:
        clauses.append(_has_any_tag(filters.tags))
    if filters.needs_evaluators:
        clauses.append(Idea.status != IdeaStatus.CLOSED)
        clauses.append(~exists().where(IdeaEvaluator.idea_id == Idea.id))
    if filters.high_disagreement:
        clauses.append(visible_high_disagreement(principal))
    if filters.q:
        clauses.append(_text_matches(project, filters.q))
    return clauses


# --- Queries ------------------------------------------------------------------------------
def page_statement(
    principal: Principal,
    where: Sequence[ColumnElement[bool]],
    sort: Sort,
    *,
    cursor: str | None,
    limit: int,
) -> Select[Any]:
    """``SELECT`` of one keyset page (``limit + 1`` rows): the idea, its summary columns
    and the (masked) ``sort_value`` the next cursor is built from."""
    value = sort.value(principal).label("sort_value")
    statement = select(*IDEA_COLUMNS, *summary_columns(principal), value).where(*where)
    if cursor:
        statement = statement.where(sort.after(sort.value(principal), cursor))
    return statement.order_by(*sort.order_by(value)).limit(limit + 1)


def _page(rows: Sequence[Row[Any]], sort: Sort, limit: int) -> tuple[list[IdeaRow], str | None]:
    """``limit + 1`` fetched rows -> the page's rows and the cursor after the last."""
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        next_cursor = sort.encode(page[-1].sort_value, page[-1].id)
    return [IdeaRow.of(IdeaData.of_row(row), row) for row in page], next_cursor


async def fetch_page(
    db: AsyncSession,
    principal: Principal,
    where: Sequence[ColumnElement[bool]],
    sort: Sort,
    *,
    cursor: str | None,
    limit: int,
) -> tuple[list[IdeaRow], str | None]:
    """One keyset page of ideas in ``sort`` order, with their summary columns."""
    statement = page_statement(principal, where, sort, cursor=cursor, limit=limit)
    return _page((await db.execute(statement)).all(), sort, limit)


async def count_ideas(db: AsyncSession, where: Sequence[ColumnElement[bool]]) -> int:
    return int(await db.scalar(select(func.count()).select_from(Idea).where(*where)) or 0)


async def list_ideas(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    role: ProjectRole | None,
    filters: IdeaFilter,
    sort: Sort,
    *,
    cursor: str | None,
    limit: int,
) -> IdeaPage:
    """A page of the project's ideas (``project.view`` is checked by the caller)."""
    where = idea_filter_clauses(principal, project, filters)
    rows, next_cursor = await fetch_page(db, principal, where, sort, cursor=cursor, limit=limit)
    items = await build_summaries(
        db,
        principal,
        rows,
        projects={project.id: project},
        roles={project.id: role} if role else {},
    )
    return IdeaPage(items=items, next_cursor=next_cursor, total=await count_ideas(db, where))


def board_statement(
    principal: Principal,
    where: Sequence[ColumnElement[bool]],
    sort: Sort,
    *,
    limit: int,
    statuses: Sequence[IdeaStatus] = LIFECYCLE,
) -> Select[Any]:
    """The first ``limit + 1`` ideas of every status, in one statement.

    ``LATERAL`` runs the list's keyset page once per status (in the default order an
    index range scan that stops after ``limit + 1`` rows), so the board is one round
    trip and one plan. Measured at 10k ideas it beats both five separate queries and
    one ``row_number() OVER (PARTITION BY status)`` query (which sorts every idea).
    """
    columns = (
        func.unnest(bindparam("board_statuses", [s.value for s in statuses], type_=ARRAY(String())))
        .table_valued(column("status", String()), with_ordinality="position")
        .render_derived("board_column")
    )
    page = page_statement(
        principal, [*where, Idea.status == columns.c.status], sort, cursor=None, limit=limit
    ).lateral("page")
    return (
        select(page)
        .select_from(columns)
        .join(page, true())
        .order_by(columns.c.position, *sort.order_by(page.c.sort_value, tie=page.c.id))
    )


async def pages_by_status(
    db: AsyncSession,
    principal: Principal,
    where: Sequence[ColumnElement[bool]],
    sort: Sort,
    limit: int,
    statuses: Sequence[IdeaStatus] = LIFECYCLE,
) -> dict[IdeaStatus, tuple[list[IdeaRow], str | None]]:
    """The first keyset page of every status in ``statuses`` (:func:`board_statement`,
    one round trip): the board's columns and My work's owned groups."""
    by_status: dict[IdeaStatus, list[Row[Any]]] = {status: [] for status in statuses}
    statement = board_statement(principal, where, sort, limit=limit, statuses=statuses)
    for row in await db.execute(statement):
        by_status[IdeaStatus(row.status)].append(row)
    return {status: _page(rows, sort, limit) for status, rows in by_status.items()}


async def get_board(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    role: ProjectRole | None,
    filters: IdeaFilter,
    sort: Sort,
    *,
    limit: int,
) -> Board:
    """One column per status of the project's lifecycle (five, or six with the research
    step: :func:`app.schemas.research.lifecycle`), in its order: counts, the first
    ``limit`` ideas, a cursor (the same keyset cursor as ``list_ideas?status=<column>``)."""
    columns_of = lifecycle(project.research_step)
    where = idea_filter_clauses(principal, project, filters)
    counts: dict[tuple[IdeaStatus, Resolution | None], int] = {
        (status, resolution): count
        for status, resolution, count in await db.execute(
            select(Idea.status, Idea.resolution, func.count())
            .where(*where)
            .group_by(Idea.status, Idea.resolution)
        )
    }
    pages = await pages_by_status(db, principal, where, sort, limit, statuses=columns_of)
    summaries = await build_summaries(
        db,
        principal,
        [row for rows, _ in pages.values() for row in rows],
        projects={project.id: project},
        roles={project.id: role} if role else {},
    )
    by_id = {summary.id: summary for summary in summaries}
    labels = resolved_labels(project.status_labels)
    columns = []
    for status in columns_of:
        rows, next_cursor = pages.get(status, ([], None))
        by_resolution = {r: counts.get((status, r), 0) for r in Resolution}
        columns.append(
            BoardColumn(
                status=status,
                label=labels[status.value],
                count=sum(n for (s, _), n in counts.items() if s is status),
                resolution_counts=(
                    ResolutionCounts(
                        accepted=by_resolution[Resolution.ACCEPTED],
                        rejected=by_resolution[Resolution.REJECTED],
                        parked=by_resolution[Resolution.PARKED],
                    )
                    if status is IdeaStatus.CLOSED
                    else None
                ),
                items=[by_id[row.idea.id] for row in rows],
                next_cursor=next_cursor,
            )
        )
    return Board(columns=columns)
