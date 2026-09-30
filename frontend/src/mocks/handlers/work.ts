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
import { failValidation, queryEnum, queryLimit, route } from '@/mocks/http'

export const workHandlers = [
  route('get', '/me/work', ({ db, user }) => {
    const due = evaluationsDue(db, user)
    const owned = ownedGroups(db, user)
    return {
      evaluations_due: due,
      owned,
      recent: recentIdeas(db, user),
      counts: {
        evaluations_due: due.length,
        evaluations_overdue: due.filter((row) => row.overdue).length,
        owned_open: owned
          .filter((group) => group.status !== 'closed')
          .reduce((sum, group) => sum + group.count, 0),
      },
    }
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
