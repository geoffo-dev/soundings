/**
 * Phase 8b fixtures (contract-phase8b §11, adapted to the mock's people):
 *
 * - **TOOL-7** ("Service health dashboard", Internal Tools is private, in Research,
 *   one required item open): **Ivan Petrov**, who has no role in any project, is its
 *   researcher, asked by Bob (the owner) and due in 3 days. Ivan is its **guest**
 *   (role matrix column R): he sees that one idea, never its scores or the project;
 *   his inbox has an unread "Asked to research". With the knob
 *   `soundings-mock-projects=private` every project is private, so Ivan has no
 *   projects at all (the shell's empty state).
 * - **TOOL-10** (in Research, complete): **Dave Okafor**, a member, researches it
 *   (asked by Farid, no due date).
 * - **GREEN-3** (Shortlisted, the status before Research in Sustainability, one
 *   required item open): **Alice** researches it, asked by Carol, due **2 days ago**:
 *   the overdue row of Alice's "Research to do" (her items are read, so her Phase 3
 *   unread count stays five).
 * - **GREEN-1** (Evaluating, nobody assigned): a research due date in 9 days, so its
 *   owner Carol does the research "as owner".
 * - Everything else: nobody assigned (the owner does the research).
 */
import type { MockDb, MockIdea, PROJECTS as ProjectsMap, USERS as UsersMap } from './db'

type Users = typeof UsersMap
type Projects = typeof ProjectsMap

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

export function seedPhase8b(
  db: MockDb,
  ctx: { users: Users; projects: Projects; nextId: (kind: number | string) => string },
): void {
  const { users, nextId } = ctx
  const now = db.now
  const iso = (ms: number) => new Date(ms).toISOString()
  // 17:00 local, `days` calendar days from today (like evaluation due dates).
  const daysAhead = (days: number) => {
    const date = new Date(now)
    date.setDate(date.getDate() + days)
    return date.setHours(17, 0, 0, 0)
  }
  const idea = (key: string): MockIdea => {
    const [projectKey = '', number = ''] = key.split('-')
    const found = db.ideas.find(
      (i) =>
        db.projects.find((p) => p.id === i.project_id)?.key === projectKey &&
        i.number === Number(number),
    )
    if (!found) throw new Error(`fixture idea ${key} missing`)
    return found
  }
  const event = (
    target: MockIdea,
    type: 'researcher_changed' | 'research_due_date_changed',
    actor: string,
    at: number,
    payload: Record<string, unknown>,
  ) => {
    db.events.push({
      id: nextId(7),
      idea_id: target.id,
      actor_id: actor,
      type,
      payload,
      comment_id: null,
      created_at: iso(at),
    })
    if (iso(at) > target.last_activity_at) target.last_activity_at = iso(at)
  }

  const assign = (
    key: string,
    researcher: string,
    by: string,
    hoursAgo: number,
    due: number | null,
    outside: boolean,
  ) => {
    const target = idea(key)
    const at = now - hoursAgo * HOUR
    target.researcher_id = researcher
    target.research_assigned_at = iso(at)
    db.watchers.add(`${target.id}:${researcher}`)
    event(target, 'researcher_changed', by, at, {
      from_researcher_id: null,
      to_researcher_id: researcher,
      handed_back: false,
    })
    if (due !== null) {
      target.research_due_at = iso(due)
      event(target, 'research_due_date_changed', by, at + MINUTE, {
        from_due_at: null,
        to_due_at: iso(due),
      })
    }
    db.audit.push({
      id: nextId('b'),
      created_at: iso(at),
      actor_id: by,
      action: 'idea.researcher_change',
      target_type: 'idea',
      target_id: target.id,
      project_id: target.project_id,
      details: {
        rule: 'idea.assign_researcher',
        from_user_id: null,
        to_user_id: researcher,
        reason: 'assigned',
        outside_project: outside,
        auth_method: 'sso',
      },
    })
    return { target, at }
  }

  const notice = (
    to: string,
    target: MockIdea,
    type: 'researcher_assigned' | 'research_reminder',
    actor: string | null,
    at: number,
    payload: Record<string, unknown>,
    read: boolean,
  ) => {
    db.notifications.push({
      id: nextId('c'),
      user_id: to,
      type,
      idea_id: target.id,
      actor_id: actor,
      comment_id: null,
      payload,
      dedupe_key: `${type}:${target.id}:${iso(at).slice(0, 10)}`,
      email_mode: 'immediate',
      email_id: null,
      created_at: iso(at),
      read_at: read ? iso(at + 30 * MINUTE) : null,
    })
  }

  // TOOL-7: Ivan, the guest researcher (no role in the private Internal Tools).
  const tool7 = assign('TOOL-7', users.ivan, users.bob, 20, daysAhead(3), true)
  notice(
    users.ivan,
    tool7.target,
    'researcher_assigned',
    users.bob,
    tool7.at,
    { due_at: tool7.target.research_due_at },
    false,
  )

  // TOOL-10: Dave, a member, no due date (complete, so not in his "Research to do").
  assign('TOOL-10', users.dave, users.farid, 40, null, false)

  // GREEN-3: Alice, overdue (due 2 days ago).
  const green3 = assign('GREEN-3', users.alice, users.carol, 6 * 24, daysAhead(-2), false)
  notice(
    users.alice,
    green3.target,
    'researcher_assigned',
    users.carol,
    green3.at,
    { due_at: green3.target.research_due_at },
    true,
  )
  notice(
    users.alice,
    green3.target,
    'research_reminder',
    null,
    daysAhead(-4) - 9 * HOUR,
    { due_at: green3.target.research_due_at, days_before: 2, as_owner: false },
    true,
  )

  // GREEN-1: nobody assigned, a research due date: its owner (Carol) does it.
  const green1 = idea('GREEN-1')
  green1.research_due_at = iso(daysAhead(9))
  event(green1, 'research_due_date_changed', users.carol, now - 3 * DAY, {
    from_due_at: null,
    to_due_at: green1.research_due_at,
  })

  db.events.sort((a, b) => a.created_at.localeCompare(b.created_at))
  db.audit.sort((a, b) => a.created_at.localeCompare(b.created_at))
}
