import {
  evaluationsDue,
  ideaSummary,
  ownedFingerprint,
  ownedGroups,
  ownedIdeas,
  paginate,
  recentIdeas,
  search,
  STATUSES,
} from '@/mocks/domain'
import type { MockDb, MockUser } from '@/mocks/db'
import { failValidation, queryEnum, queryLimit, route } from '@/mocks/http'

/** My work lists the first 50 evaluations due; "Show more" pages on (contract-phase7 C1). */
const WORK_DUE_SHOWN = 50

function workCounts(db: MockDb, user: MockUser) {
  const due = evaluationsDue(db, user)
  return {
    evaluations_due: due.length,
    evaluations_overdue: due.filter((row) => row.overdue).length,
    owned_open: ownedGroups(db, user)
      .filter((group) => group.status !== 'closed')
      .reduce((sum, group) => sum + group.count, 0),
  }
}

export const workHandlers = [
  route('get', '/me/work', ({ db, user }) => {
    const due = evaluationsDue(db, user)
    const { page, next_cursor } = paginate(due, null, WORK_DUE_SHOWN, `due:${user.id}`)
    return {
      evaluations_due: page,
      evaluations_due_next_cursor: next_cursor,
      owned: ownedGroups(db, user),
      recent: recentIdeas(db, user),
      counts: workCounts(db, user),
    }
  }),

  route('get', '/me/work/counts', ({ db, user }) => workCounts(db, user)),

  route('get', '/me/evaluations-due', ({ url, db, user }) => {
    const { page, next_cursor } = paginate(
      evaluationsDue(db, user),
      url.searchParams.get('cursor'),
      queryLimit(url),
      `due:${user.id}`,
    )
    return { items: page, next_cursor }
  }),

  route('get', '/me/owned-ideas', ({ url, db, user }) => {
    const statuses = queryEnum(url, 'status', STATUSES)
    const limit = queryLimit(url)
    const ideas = ownedIdeas(db, user, statuses)
    const { page, next_cursor } = paginate(
      ideas,
      url.searchParams.get('cursor'),
      limit,
      ownedFingerprint(user, statuses),
    )
    return {
      items: page.map((idea) => ideaSummary(db, idea, user)),
      next_cursor,
      total: ideas.length,
    }
  }),

  route('get', '/search', ({ url, db, user }) => {
    const q = url.searchParams.get('q') ?? ''
    if (q.trim().length < 1 || q.length > 200) {
      failValidation([
        { loc: ['query', 'q'], msg: 'Search text is 1–200 characters', type: 'string_too_short' },
      ])
    }
    return search(db, user, q, queryLimit(url, 8, 20))
  }),
]
