"""A large Soundings instance for the Phase 7 performance check, in about a minute.

On top of the demo story (``soundings seed --reset --force`` first: its people, projects,
rubrics and dev logins), bulk SQL adds:

* people up to ``users`` (default 50 active people; ``perf01@example.com`` ...), all
  members of every demo project and of a new private project **Big Ideas**
  (``/p/big-ideas``, key ``BIG``, created through the service as Alice);
* ``big_ideas`` (10,000) ideas in Big Ideas and ``other_ideas`` (2,000) spread over the
  demo projects, with realistic titles, summaries, descriptions, statuses, owners,
  tags, due dates and votes;
* 3-5 evaluators on every idea past ``new`` (about 35,000 assignments) and about 30,000
  evaluations (submitted or draft, scored on the project's rubric); one person
  (``perf01``, "Pat Pending") owes 1,000 evaluations in Big Ideas and never submits,
  so blind masking is in every query;
* about 31,000 comments (each with its feed event; one idea in a hundred has 60) and
  the rest of the activity feed (created, owner, status, evaluator added, evaluation
  submitted: about 120,000 events in all), watchers;
* about 20,000 notifications (invited, comment, status changed; most older ones read)
  and about 60,000 audit entries;
* Phase 8: in the demo projects with a research step (Internal Tools, Sustainability), a
  third of the ideas at the step's place in Research and about half of every checklist
  answered;

then recomputes every cached aggregate through ``app.services.scoring`` and runs
``ANALYZE``. Every count is deterministic (``hashtext``), so runs compare.

Usage (from ``backend/``, ``SOUNDINGS_DATABASE_URL`` pointing at a throwaway database)::

    uv run soundings seed --reset --force
    uv run python -m tests.perf.seed_large [--scale 0.1]

``tests/perf/stack.sh`` does both, with the API and worker; ``test_perf_large.py`` calls
:func:`seed_large` on its test database.
"""

# ruff: noqa: E501, SIM905 - SQL reads best unwrapped; word lists as text

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.domain.principal import Principal
from app.models.enums import ResearchStep
from app.models.project import Project
from app.models.user import User
from app.schemas.projects import ProjectCreate
from app.services.projects import create_project
from app.services.scoring import recompute_aggregates

__all__ = ["BIG_KEY", "BIG_SLUG", "PENDING_EMAIL", "Size", "seed_large"]

BIG_SLUG = "big-ideas"
BIG_KEY = "BIG"
PENDING_EMAIL = "perf01@example.com"
"""Pat Pending: assigned 1,000 Big Ideas evaluations, submits none (My work, blind)."""


@dataclass(frozen=True, slots=True)
class Size:
    users: int = 50
    big_ideas: int = 10_000
    other_ideas: int = 2_000
    pending_due: int = 1_000

    def scaled(self, factor: float) -> Size:
        return Size(
            users=self.users,
            big_ideas=max(10, int(self.big_ideas * factor)),
            other_ideas=max(3, int(self.other_ideas * factor)),
            pending_due=max(1, int(self.pending_due * factor)),
        )


FIRST = (
    "Nora Liam Maya Omar Ines Theo Lena Ravi Ana Felix Yara Jonas Mila Arjun Sofia Hugo "
    "Leila Noah Chloe Tariq Elena Kofi Ivy Marco Saanvi Owen Freya Malik Aiko Ben Rosa "
    "Emil Dara Luca Hana Joel Nia Pablo"
).split()
LAST = (
    "Okoro Silva Novak Haddad Larsen Tanaka Moreau Patel Kowalski Byrne Costa Weber Ali "
    "Jensen Rossi Nakamura Fischer Mensah Duarte Lindgren Petrov Quinn Achebe Vargas "
    "Ivanova Shah Dubois Keller Sato Murphy Reyes Berg Osei Kaur Romano Hall Abebe Ortiz"
).split()

USERS = """
INSERT INTO users (id, email, display_name, last_seen_at, created_at, updated_at)
SELECT gen_random_uuid(),
       'perf' || lpad(n::text, 2, '0') || '@example.com',
       CASE WHEN n = 1 THEN 'Pat Pending'
            ELSE (CAST(:first AS text[]))[1 + (n - 1) % cardinality(CAST(:first AS text[]))]
                 || ' ' || (CAST(:last AS text[]))[1 + (n * 7) % cardinality(CAST(:last AS text[]))]
       END,
       now() - (n % 12) * interval '1 hour',
       now() - interval '300 days' + n * interval '1 day',
       now()
FROM generate_series(1, :count) AS n
ON CONFLICT DO NOTHING
"""

MEMBERS = """
INSERT INTO project_members (project_id, user_id, role, created_at, updated_at)
SELECT :project, u.id,
       CASE WHEN u.email IN ('perf02@example.com', 'perf03@example.com') THEN 'admin'
            WHEN u.email IN ('perf04@example.com', 'perf05@example.com') THEN 'viewer'
            ELSE 'member' END,
       now() - interval '200 days', now()
FROM users u
WHERE u.is_active AND NOT u.is_service_account AND NOT u.is_break_glass
ON CONFLICT DO NOTHING
"""

ACTIVE_MEMBERS = """
SELECT r.user_id FROM project_effective_roles r JOIN users u ON u.id = r.user_id
WHERE r.project_id = :project AND r.role IN ('admin', 'member')
  AND u.is_active AND NOT u.is_service_account AND u.email <> :pending
ORDER BY u.email
"""

TAGS = """
INSERT INTO tags (id, project_id, name, created_at)
SELECT gen_random_uuid(), :project, t.name, now() - interval '200 days'
FROM unnest(CAST(:names AS text[])) AS t(name)
ON CONFLICT DO NOTHING
"""

# Words for titles like "Self-service refunds for small businesses" (~7,000 combinations,
# so a word such as "pricing" matches about 1 idea in 25, as a real search would).
ADJECTIVES = (
    "Self-service|Faster|Simpler|Automated|Greener|Shared|Smarter|Cheaper|Offline|Mobile|"
    "Instant|Unified|Transparent|Proactive|Personal|Secure|Accessible|Flexible|Local|Live"
).split("|")
NOUNS = (
    "refunds|pricing|chat support|kiosks|billing|onboarding|returns|delivery slots|"
    "loyalty points|invoices|search|checkout|reviews|subscriptions|repairs|warranty claims|"
    "store maps|gift cards|product videos|trade-ins|bulk orders|appointments|feedback|"
    "parcel lockers|price alerts"
).split("|")
AUDIENCES = (
    "small businesses|new customers|field engineers|store staff|the call centre|"
    "partners|students|families|regular buyers|enterprise accounts|first-time visitors|"
    "warehouse teams|suppliers|older customers|remote workers"
).split("|")

IDEAS = """
INSERT INTO ideas (id, project_id, number, title, summary, description_md, status,
                   resolution, owner_id, submitted_by_id, evaluation_due_at,
                   last_activity_at, created_at, updated_at, vote_count, aggregate_count,
                   high_disagreement)
SELECT gen_random_uuid(), :project, :start + g.n - 1,
       (CAST(:adj AS text[]))[1 + h.a % cardinality(CAST(:adj AS text[]))] || ' '
           || (CAST(:noun AS text[]))[1 + h.b % cardinality(CAST(:noun AS text[]))] || ' for '
           || (CAST(:aud AS text[]))[1 + h.c % cardinality(CAST(:aud AS text[]))],
       'Today ' || (CAST(:aud AS text[]))[1 + h.c % cardinality(CAST(:aud AS text[]))]
           || ' wait too long for '
           || (CAST(:noun AS text[]))[1 + h.b % cardinality(CAST(:noun AS text[]))]
           || '. We could cut the wait from days to minutes and save about '
           || (10 + h.a % 90) || ' hours a week across the teams involved.',
       '## Problem' || chr(10) || chr(10) || repeat('People tell us the current process is '
           || 'slow, manual and hard to follow, and that it costs them time. ', 4)
           || chr(10) || chr(10) || '## Proposal' || chr(10) || chr(10)
           || '- Start with one region' || chr(10) || '- Measure the wait before and after'
           || chr(10) || '- Roll out if it halves' || chr(10) || chr(10)
           || repeat('We would reuse the existing platform and keep the old route '
           || 'open while people switch. ', 3),
       s.status,
       CASE WHEN s.status = 'closed' THEN (ARRAY['accepted', 'rejected', 'parked'])[1 + h.c % 3] END,
       CASE WHEN h.d % 8 <> 0
            THEN (CAST(:members AS uuid[]))[1 + h.a % cardinality(CAST(:members AS uuid[]))] END,
       (CAST(:members AS uuid[]))[1 + h.e % cardinality(CAST(:members AS uuid[]))],
       CASE WHEN s.status = 'evaluating' THEN now() + ((h.d % 21) - 7) * interval '1 day' END,
       t.created + (now() - t.created) * ((h.e % 1000) / 1000.0),
       t.created, now(), 0, 0, false
FROM generate_series(1, :count) AS g(n)
CROSS JOIN LATERAL (
    SELECT abs(hashtext(:salt || 'a' || g.n)) AS a, abs(hashtext(:salt || 'b' || g.n)) AS b,
           abs(hashtext(:salt || 'c' || g.n)) AS c, abs(hashtext(:salt || 'd' || g.n)) AS d,
           abs(hashtext(:salt || 'e' || g.n)) AS e
) AS h
CROSS JOIN LATERAL (
    SELECT (ARRAY['new', 'new', 'new', 'new', 'new', 'new', 'evaluating', 'evaluating',
                  'evaluating', 'evaluating', 'evaluating', 'evaluating', 'shortlisted',
                  'shortlisted', 'shortlisted', 'proposal', 'proposal', 'closed', 'closed',
                  'closed'])[1 + h.d % 20] AS status
) AS s
CROSS JOIN LATERAL (
    SELECT now() - interval '365 days' + (g.n::float / :count) * interval '360 days' AS created
) AS t
"""

# The ideas this run added (numbers >= :start), in a temp table the rest joins.
NEW_IDEAS = """
CREATE TEMP TABLE IF NOT EXISTS perf_new_ideas (id uuid PRIMARY KEY, project_id uuid,
    number int, status text, owner_id uuid, submitted_by_id uuid, created_at timestamptz,
    h int) ON COMMIT DROP;
INSERT INTO perf_new_ideas
SELECT id, project_id, number, status, owner_id, submitted_by_id, created_at,
       abs(hashtext(id::text))
FROM ideas WHERE project_id = :project AND number >= :start
"""

# Phase 8: in a project with the research step, a third of the ideas at the step's place
# (New before evaluation, Shortlisted before the proposal) are in Research, and every
# idea has about half of its checklist answered, so cards carry progress (contract-phase8
# section 3.6: one grouped statement per page).
RESEARCH = """
UPDATE ideas SET status = 'research'
FROM perf_new_ideas i
WHERE ideas.id = i.id AND i.project_id = :project AND i.h % 3 = 0
  AND i.status = CASE WHEN :step = 'before_evaluation' THEN 'new' ELSE 'shortlisted' END;
INSERT INTO research_answers (idea_id, item_id, answer, answered_by_id, answered_at,
                              updated_by_id, updated_at)
SELECT i.id, r.id, 'Asked the team that runs it about ' || lower(r.title) || ': no objections.',
       coalesce(i.owner_id, i.submitted_by_id), i.created_at + interval '1 day',
       coalesce(i.owner_id, i.submitted_by_id), i.created_at + interval '1 day'
FROM perf_new_ideas i
JOIN research_checklist_items r ON r.project_id = i.project_id AND r.archived_at IS NULL
WHERE i.project_id = :project AND (i.h + r.position) % 2 = 0
"""

IDEA_TAGS = """
INSERT INTO idea_tags (idea_id, tag_id)
SELECT i.id, t.id
FROM perf_new_ideas i
CROSS JOIN generate_series(0, 2) AS j
JOIN LATERAL (
    SELECT id FROM tags WHERE project_id = i.project_id ORDER BY name
    OFFSET (i.h + j * 7) % GREATEST((SELECT count(*) FROM tags WHERE project_id = i.project_id), 1)
    LIMIT 1
) AS t ON true
WHERE i.project_id = :project AND j < i.h % 4
ON CONFLICT DO NOTHING
"""

EVALUATORS = """
INSERT INTO idea_evaluators (idea_id, user_id, invited_by_id, invited_at)
SELECT i.id,
       (CAST(:members AS uuid[]))[1 + (i.h + j * 7) % cardinality(CAST(:members AS uuid[]))],
       i.owner_id, i.created_at + interval '2 days'
FROM perf_new_ideas i CROSS JOIN generate_series(0, 4) AS j
WHERE i.project_id = :project AND i.status <> 'new' AND j < 3 + i.h % 3
ON CONFLICT DO NOTHING
"""

PENDING_EVALUATOR = """
INSERT INTO idea_evaluators (idea_id, user_id, invited_by_id, invited_at)
SELECT i.id, :pending, i.owner_id, i.created_at + interval '2 days'
FROM perf_new_ideas i
WHERE i.project_id = :project AND i.status = 'evaluating'
ORDER BY i.number DESC
LIMIT :due
ON CONFLICT DO NOTHING
"""

EVALUATIONS = """
INSERT INTO evaluations (id, idea_id, evaluator_id, status, recommendation, comment,
                         submitted_at, include_in_aggregate, created_at, updated_at)
SELECT gen_random_uuid(), x.idea_id, x.user_id, x.state,
       CASE WHEN x.state = 'submitted' THEN (ARRAY['go', 'go', 'maybe', 'no'])[1 + x.h % 4] END,
       CASE WHEN x.h % 3 = 0 THEN 'Worth a pilot; the numbers need checking with finance.'
            ELSE '' END,
       CASE WHEN x.state = 'submitted' THEN x.invited_at + (1 + x.h % 6) * interval '1 day' END,
       true, x.invited_at + interval '1 day', now()
FROM (
    SELECT ie.idea_id, ie.user_id, ie.invited_at, abs(hashtext(ie.idea_id::text || ie.user_id::text)) AS h,
           i.status
    FROM idea_evaluators ie JOIN perf_new_ideas i ON i.id = ie.idea_id
    WHERE i.project_id = :project AND ie.user_id <> :pending
) AS raw
CROSS JOIN LATERAL (
    SELECT raw.idea_id, raw.user_id, raw.invited_at, raw.h,
           CASE WHEN raw.status = 'evaluating' THEN
                    CASE WHEN raw.h % 20 < 3 THEN NULL WHEN raw.h % 20 < 5 THEN 'draft'
                         ELSE 'submitted' END
                ELSE CASE WHEN raw.h % 20 = 0 THEN NULL WHEN raw.h % 20 = 1 THEN 'draft'
                          ELSE 'submitted' END
           END AS state
) AS x
WHERE x.state IS NOT NULL
"""

SCORES = """
INSERT INTO evaluation_scores (evaluation_id, criterion_id, score, comment)
SELECT e.id, c.id,
       LEAST(5, GREATEST(1, 1 + i.h % 5
           + CASE WHEN i.h % 9 = 0 THEN (abs(hashtext(e.id::text || c.id::text)) % 5) - 2
                  ELSE (abs(hashtext(e.id::text || c.id::text)) % 3) - 1 END)),
       CASE WHEN abs(hashtext(c.id::text || e.id::text)) % 5 = 0
            THEN 'Depends on the vendor quote.' ELSE '' END
FROM evaluations e
JOIN perf_new_ideas i ON i.id = e.idea_id
JOIN rubric_criteria c ON c.project_id = i.project_id AND c.archived_at IS NULL
WHERE i.project_id = :project
"""

COMMENTS = """
WITH made AS (
    INSERT INTO comments (id, idea_id, author_id, body_md, created_at, updated_at)
    SELECT gen_random_uuid(), i.id,
           (CAST(:members AS uuid[]))[1 + (i.h + j * 5) % cardinality(CAST(:members AS uuid[]))],
           (ARRAY['Could we try this in one store first?',
                  'We looked at something similar in 2023; the blocker was the **supplier API**.',
                  'Love it. Customers ask for this every week in the call centre.',
                  'What would it cost to run? I would like a rough monthly figure before we score it.',
                  'Linked the research notes from the last workshop: see the shared drive.'])[1 + (i.h + j) % 5],
           ts.at, ts.at
    FROM perf_new_ideas i
    CROSS JOIN LATERAL generate_series(1, CASE WHEN i.number % 100 = 0 THEN 60 ELSE i.h % 5 END) AS j
    CROSS JOIN LATERAL (
        SELECT i.created_at + (now() - i.created_at) * (j::float / (1 + CASE WHEN i.number % 100 = 0
               THEN 60 ELSE i.h % 5 END)) AS at
    ) AS ts
    WHERE i.project_id = :project
    RETURNING id, idea_id, author_id, created_at
)
INSERT INTO activity_events (id, project_id, idea_id, actor_id, type, comment_id, payload, created_at)
SELECT gen_random_uuid(), :project, made.idea_id, made.author_id, 'comment', made.id, '{}'::jsonb,
       made.created_at
FROM made
"""

EVENTS = """
INSERT INTO activity_events (id, project_id, idea_id, actor_id, type, payload, created_at)
SELECT gen_random_uuid(), :project, i.id, i.submitted_by_id, 'idea_created', '{}'::jsonb, i.created_at
FROM perf_new_ideas i WHERE i.project_id = :project
UNION ALL
SELECT gen_random_uuid(), :project, i.id, i.owner_id, 'owner_changed',
       jsonb_build_object('from_owner_id', NULL, 'to_owner_id', i.owner_id, 'volunteered', true),
       i.created_at + interval '1 hour'
FROM perf_new_ideas i WHERE i.project_id = :project AND i.owner_id IS NOT NULL
UNION ALL
SELECT gen_random_uuid(), :project, i.id, i.owner_id, 'status_changed',
       jsonb_build_object('from_status', 'new', 'from_resolution', NULL,
                          'to_status', i.status, 'to_resolution', d.resolution),
       i.created_at + interval '3 days'
FROM perf_new_ideas i JOIN ideas d ON d.id = i.id
WHERE i.project_id = :project AND i.status <> 'new'
UNION ALL
SELECT gen_random_uuid(), :project, ie.idea_id, ie.invited_by_id, 'evaluator_added',
       jsonb_build_object('evaluator_id', ie.user_id), ie.invited_at
FROM idea_evaluators ie JOIN perf_new_ideas i ON i.id = ie.idea_id
WHERE i.project_id = :project
UNION ALL
SELECT gen_random_uuid(), :project, e.idea_id, e.evaluator_id, 'evaluation_submitted',
       jsonb_build_object('evaluator_id', e.evaluator_id), e.submitted_at
FROM evaluations e JOIN perf_new_ideas i ON i.id = e.idea_id
WHERE i.project_id = :project AND e.status = 'submitted'
"""

WATCHERS = """
INSERT INTO idea_watchers (idea_id, user_id, created_at)
SELECT DISTINCT ON (w.idea_id, w.user_id) w.idea_id, w.user_id, w.at
FROM (
    SELECT i.id AS idea_id, i.owner_id AS user_id, i.created_at AS at
    FROM perf_new_ideas i WHERE i.project_id = :project AND i.owner_id IS NOT NULL
    UNION ALL
    SELECT i.id, i.submitted_by_id, i.created_at
    FROM perf_new_ideas i WHERE i.project_id = :project
    UNION ALL
    SELECT c.idea_id, c.author_id, c.created_at
    FROM comments c JOIN perf_new_ideas i ON i.id = c.idea_id WHERE i.project_id = :project
) AS w
ORDER BY w.idea_id, w.user_id, w.at
ON CONFLICT DO NOTHING
"""

VOTES = """
INSERT INTO idea_votes (idea_id, user_id, created_at)
SELECT i.id,
       (CAST(:members AS uuid[]))[1 + (i.h + j * 11) % cardinality(CAST(:members AS uuid[]))],
       i.created_at + j * interval '1 day'
FROM perf_new_ideas i CROSS JOIN generate_series(0, 7) AS j
WHERE i.project_id = :project AND j < (i.h / 7) % 8
ON CONFLICT DO NOTHING;
UPDATE ideas SET vote_count = v.n
FROM (SELECT iv.idea_id, count(*) AS n FROM idea_votes iv JOIN perf_new_ideas i ON i.id = iv.idea_id
      WHERE i.project_id = :project GROUP BY iv.idea_id) AS v
WHERE ideas.id = v.idea_id
"""

NOTIFICATIONS = """
INSERT INTO notifications (id, user_id, type, idea_id, actor_id, comment_id, payload, dedupe_key,
                           email_mode, read_at, created_at)
SELECT gen_random_uuid(), n.user_id, n.type, n.idea_id, n.actor_id, n.comment_id, n.payload,
       n.type || ':perf:' || n.ref, 'off',
       CASE WHEN n.at < now() - interval '7 days' AND abs(hashtext(n.ref)) % 10 < 8
            THEN n.at + interval '1 day' END,
       n.at
FROM (
    SELECT ie.user_id, 'evaluator_invited' AS type, ie.idea_id, ie.invited_by_id AS actor_id,
           NULL::uuid AS comment_id, jsonb_build_object('due_at', d.evaluation_due_at) AS payload,
           ie.idea_id::text AS ref, ie.invited_at AS at
    FROM idea_evaluators ie JOIN perf_new_ideas i ON i.id = ie.idea_id JOIN ideas d ON d.id = i.id
    WHERE i.project_id = :project AND (abs(hashtext(ie.user_id::text || ie.idea_id::text)) % 3 = 0
          OR ie.user_id = :pending)
    UNION ALL
    SELECT i.owner_id, 'comment', c.idea_id, c.author_id, c.id, '{}'::jsonb, c.id::text, c.created_at
    FROM comments c JOIN perf_new_ideas i ON i.id = c.idea_id
    WHERE i.project_id = :project AND i.owner_id IS NOT NULL AND i.owner_id <> c.author_id
          AND abs(hashtext(c.id::text)) % 4 = 0
    UNION ALL
    SELECT i.owner_id, 'status_changed', i.id, i.submitted_by_id, NULL, jsonb_build_object(
               'from_status', 'new', 'from_resolution', NULL, 'to_status', i.status,
               'to_resolution', d.resolution), i.id::text, i.created_at + interval '3 days'
    FROM perf_new_ideas i JOIN ideas d ON d.id = i.id
    WHERE i.project_id = :project AND i.status <> 'new' AND i.owner_id IS NOT NULL
          AND i.owner_id <> i.submitted_by_id AND i.h % 2 = 0
) AS n
ON CONFLICT DO NOTHING
"""

AUDIT = """
INSERT INTO audit_log (id, actor_id, action, target_type, target_id, project_id, details, created_at)
SELECT gen_random_uuid(), ie.invited_by_id, 'evaluator.add', 'user', ie.user_id, :project,
       jsonb_build_object('rule', 'evaluator.manage', 'idea_id', ie.idea_id), ie.invited_at
FROM idea_evaluators ie JOIN perf_new_ideas i ON i.id = ie.idea_id
WHERE i.project_id = :project AND ie.invited_by_id IS NOT NULL
UNION ALL
SELECT gen_random_uuid(), e.evaluator_id, 'evaluation.submit', 'idea', e.idea_id, :project,
       jsonb_build_object('rule', 'evaluation.submit_own', 'evaluation_id', e.id), e.submitted_at
FROM evaluations e JOIN perf_new_ideas i ON i.id = e.idea_id
WHERE i.project_id = :project AND e.status = 'submitted'
"""

SIGN_INS = """
INSERT INTO audit_log (id, actor_id, action, target_type, target_id, details, created_at)
SELECT gen_random_uuid(), u.id, 'session.sign_in', 'user', u.id,
       jsonb_build_object('auth_method', 'sso'), now() - d * interval '1 day' - interval '8 hours'
FROM users u CROSS JOIN generate_series(1, 40) AS d
WHERE u.email LIKE 'perf%@example.com'
"""

COUNTS = """
SELECT (SELECT count(*) FROM users WHERE is_active AND NOT is_service_account) AS users,
       (SELECT count(*) FROM ideas) AS ideas,
       (SELECT count(*) FROM ideas i JOIN projects p ON p.id = i.project_id
        WHERE p.slug = :big) AS big_ideas,
       (SELECT count(*) FROM idea_evaluators) AS assignments,
       (SELECT count(*) FROM evaluations) AS evaluations,
       (SELECT count(*) FROM evaluations WHERE status = 'submitted') AS submitted,
       (SELECT count(*) FROM evaluation_scores) AS scores,
       (SELECT count(*) FROM comments) AS comments,
       (SELECT count(*) FROM activity_events) AS activity_events,
       (SELECT count(*) FROM notifications) AS notifications,
       (SELECT count(*) FROM audit_log) AS audit_entries,
       (SELECT count(*) FROM idea_votes) AS votes,
       (SELECT count(*) FROM idea_watchers) AS watchers
"""


async def _execute(db: AsyncSession, sql: str, params: dict[str, Any]) -> None:
    for statement in sql.split(";\n"):
        if statement.strip():
            await db.execute(text(statement), params)


async def _members(db: AsyncSession, project_id: UUID) -> list[str]:
    rows = await db.execute(text(ACTIVE_MEMBERS), {"project": project_id, "pending": PENDING_EMAIL})
    return [str(row[0]) for row in rows]


async def _fill_project(
    db: AsyncSession, project: Project, count: int, pending: UUID, due: int
) -> None:
    members = await _members(db, project.id)
    start = project.next_idea_number
    tag_names = [f"{word}-{n}" for n in range(3) for word in ("ux", "cost", "ops", "data", "cx")]
    base: dict[str, Any] = {"project": project.id, "members": members, "pending": pending}
    await db.execute(text(TAGS), {"project": project.id, "names": tag_names})
    await db.execute(
        text(IDEAS),
        {
            **base,
            "start": start,
            "count": count,
            "salt": project.key,
            "adj": ADJECTIVES,
            "noun": NOUNS,
            "aud": AUDIENCES,
        },
    )
    await db.execute(
        text("UPDATE projects SET next_idea_number = :next WHERE id = :project"),
        {"next": start + count, "project": project.id},
    )
    await _execute(db, NEW_IDEAS, {"project": project.id, "start": start})
    for statement in (IDEA_TAGS, EVALUATORS):
        await db.execute(text(statement), base)
    if due:
        await db.execute(text(PENDING_EVALUATOR), {**base, "due": due})
    for statement in (EVALUATIONS, SCORES, COMMENTS, EVENTS, WATCHERS):
        await db.execute(text(statement), base)
    await _execute(db, VOTES, base)
    for statement in (NOTIFICATIONS, AUDIT):
        await db.execute(text(statement), base)
    if project.research_step is not ResearchStep.OFF:
        await _execute(db, RESEARCH, {"project": project.id, "step": project.research_step.value})


async def seed_large(db: AsyncSession, size: Size | None = None) -> dict[str, int]:
    """Add the large data set to a database holding the demo story; commits. Returns the
    row counts afterwards."""
    size = size or Size()
    alice = await db.scalar(select(User).where(User.email == "alice@example.com"))
    if alice is None:
        raise SystemExit("seed the demo data first: uv run soundings seed --reset --force")
    if await db.scalar(select(Project.id).where(Project.slug == BIG_SLUG)):
        raise SystemExit(f"{BIG_SLUG} exists already: reseed the demo data first (--reset)")
    existing = int(
        await db.scalar(text("SELECT count(*) FROM users WHERE NOT is_service_account")) or 0
    )
    await db.execute(
        text(USERS), {"count": max(size.users - existing, 1), "first": FIRST, "last": LAST}
    )
    await create_project(
        db,
        Principal(user=alice),
        ProjectCreate(
            name="Big Ideas",
            slug=BIG_SLUG,
            key=BIG_KEY,
            description="Every idea from the whole company: ten thousand of them.",
        ),
    )
    pending = await db.scalar(select(User.id).where(User.email == PENDING_EMAIL))
    assert pending is not None
    projects = list(await db.scalars(select(Project).order_by(Project.created_at)))
    big = next(project for project in projects if project.slug == BIG_SLUG)
    others = [project for project in projects if project.slug != BIG_SLUG]
    for project in projects:
        await db.execute(text(MEMBERS), {"project": project.id})
    await db.flush()
    await _fill_project(db, big, size.big_ideas, pending, size.pending_due)
    shares = [size.other_ideas // 2] + [size.other_ideas // (2 * max(len(others) - 1, 1))] * (
        len(others) - 1
    )
    for project, count in zip(others, shares, strict=True):
        await db.refresh(project)
        await _fill_project(db, project, count, pending, 0)
    await db.execute(text(SIGN_INS))
    for project in projects:
        await recompute_aggregates(db, project_id=project.id)
    await db.commit()
    counts = (await db.execute(text(COUNTS), {"big": BIG_SLUG})).mappings().one()
    return {key: int(value) for key, value in counts.items()}


async def _main(settings: Settings, size: Size) -> dict[str, int]:
    engine = create_engine(settings, application_name="soundings-perf-seed")
    try:
        async with create_sessionmaker(engine)() as db:
            counts = await seed_large(db, size)
        async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as connection:
            await connection.execute(text("VACUUM ANALYZE"))
        return counts
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scale", type=float, default=1.0, help="multiply idea counts")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    counts = asyncio.run(_main(get_settings(), Size().scaled(args.scale)))
    counts["seconds"] = round(time.perf_counter() - started)
    sys.stdout.write(json.dumps(counts, indent=2) + "\n")


if __name__ == "__main__":
    main()
