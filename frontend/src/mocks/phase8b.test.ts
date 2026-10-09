import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import { getDb, resetDb, USERS } from '@/mocks/db'
import { RESEARCH_ITEMS } from '@/mocks/phase8-fixtures'
import { guestAccess } from '@/mocks/researchers'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

/*
 * Phase 8b in the mock (contract-phase8b): the researcher, the guest researcher's
 * access (role matrix column R, table L), "Research to do" and the inbox. Ivan has
 * no role anywhere and researches TOOL-7 (the private Internal Tools); Alice
 * researches GREEN-3 (overdue); Dave researches TOOL-10.
 */

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
})
afterEach(() => {
  server.resetHandlers()
  endSession()
})
afterAll(() => server.close())

async function signIn(userId: string) {
  await api.POST('/api/v1/auth/dev/login', { body: { user_id: userId } })
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('expected the request to fail')
}

const idea = (key: string) => ({ params: { path: { idea: key } } })
const assign = (key: string, researcher_id: string | null, due_at: string | null = null) =>
  api.PUT('/api/v1/ideas/{idea}/research/assignment', {
    ...idea(key),
    body: { researcher_id, due_at },
  })
const handBack = (key: string) => api.DELETE('/api/v1/ideas/{idea}/research/assignment', idea(key))

describe('the guest researcher (column R)', () => {
  it('sees the one idea without scores, the evaluation area or the project', async () => {
    await signIn(USERS.ivan)
    const { data } = await api.GET('/api/v1/ideas/{idea}', idea('TOOL-7'))
    expect(data).toMatchObject({
      key: 'TOOL-7',
      score: null,
      aggregate: null,
      score_hidden: true,
      high_disagreement: false,
      evaluators: [],
      evaluator_progress: { submitted: 0, total: 0 },
      evaluation_due_at: null,
      evaluation_open: false,
      researcher: { id: USERS.ivan },
    })
    expect(data?.research_due_at).not.toBeNull()
    expect(data?.permissions).toMatchObject({
      can_view_project: false,
      can_comment: true,
      can_answer_research: true,
      can_hand_back_research: true,
      can_vote: false,
      can_change_status: false,
      can_assign_researcher: false,
      can_edit: false,
    })
    // Another idea of the project, and the project itself: 404, as if they didn't exist.
    expect((await rejection(api.GET('/api/v1/ideas/{idea}', idea('TOOL-8')))).status).toBe(404)
    const project = await rejection(
      api.GET('/api/v1/projects/{slug}', { params: { path: { slug: 'internal-tools' } } }),
    )
    expect(project.status).toBe(404)
  })

  it('reaches only the routes table L allows (deny by default)', async () => {
    await signIn(USERS.ivan)
    for (const path of [
      '/api/v1/ideas/{idea}/evaluations',
      '/api/v1/ideas/{idea}/evaluations/me',
      '/api/v1/ideas/{idea}/proposal',
      '/api/v1/ideas/{idea}/ai-runs',
      '/api/v1/ideas/{idea}/submission',
    ] as const) {
      const error = await rejection(api.GET(path, idea('TOOL-7')))
      expect(error.status, path).toBe(404)
    }
    expect(guestAccess('GET', '/api/v1/ideas/TOOL-7/proposal/markdown')).toBe('hidden')
    expect(guestAccess('GET', '/api/v1/ideas/TOOL-7/research')).toBe('view')
    expect(guestAccess('POST', '/api/v1/ideas/TOOL-7/comments')).toBe('rule')
    expect(guestAccess('POST', '/api/v1/ideas/TOOL-7/something-new')).toBe('hidden')
    // Writes R may attempt answer 403 (R sees the idea).
    const vote = await rejection(api.PUT('/api/v1/ideas/{idea}/vote', idea('TOOL-7')))
    expect(vote.status).toBe(403)
    const reassign = await rejection(assign('TOOL-7', USERS.bob))
    expect(reassign.status).toBe(403)
  })

  it('reads the feed without evaluation events, and comments and answers', async () => {
    await signIn(USERS.ivan)
    const feed = await api.GET('/api/v1/ideas/{idea}/activity', idea('TOOL-7'))
    const types = new Set(feed.data?.items.map((item) => item.type))
    for (const hidden of ['evaluator_added', 'evaluation_submitted', 'due_date_changed']) {
      expect(types.has(hidden as never)).toBe(false)
    }
    expect(types.has('researcher_changed')).toBe(true)
    const status = feed.data?.items.find((item) => item.type === 'status_changed')
    expect(status && 'to_label' in status && status.to_label).toBe('Research')
    const comment = await api.POST('/api/v1/ideas/{idea}/comments', {
      ...idea('TOOL-7'),
      body: { body_md: 'Spoke to the ops team today.' },
    })
    expect(comment.response.status).toBe(201)
    const answered = await api.PUT('/api/v1/ideas/{idea}/research/items/{item_id}', {
      params: { path: { idea: 'TOOL-7', item_id: RESEARCH_ITEMS.toolConsulted } },
      body: { answer: 'Ops (Marta), 8 Oct: they want it.' },
    })
    expect(answered.data?.progress.required_open).toBe(0)
    expect(answered.data?.permissions).toMatchObject({
      can_answer: true,
      can_override: false,
      can_assign: false,
      can_hand_back: true,
    })
  })

  it('finds the idea in search and Similar ideas lists no other idea of the project', async () => {
    await signIn(USERS.ivan)
    const found = await api.GET('/api/v1/search', { params: { query: { q: 'health' } } })
    expect(found.data?.ideas.map((i) => i.key)).toEqual(['TOOL-7'])
    expect(found.data?.projects).toEqual([])
    const similar = await api.GET('/api/v1/ideas/{idea}/similar-ideas', idea('TOOL-7'))
    expect(similar.data?.items.map((i) => i.key).filter((key) => key.startsWith('TOOL'))).toEqual(
      [],
    )
  })

  it('loses access the moment the research is handed back', async () => {
    await signIn(USERS.ivan)
    expect((await handBack('TOOL-7')).response.status).toBe(204)
    expect((await rejection(api.GET('/api/v1/ideas/{idea}', idea('TOOL-7')))).status).toBe(404)
    const inbox = await api.GET('/api/v1/me/notifications')
    expect(inbox.data?.items).toEqual([])
    const audit = getDb().audit.at(-1)
    expect(audit).toMatchObject({
      action: 'idea.researcher_change',
      details: { reason: 'handed_back' },
    })
  })

  it('has no projects with every project private, and My work lists the research', async () => {
    resetDb({ projects: 'private' })
    await signIn(USERS.ivan)
    expect((await api.GET('/api/v1/projects')).data).toEqual([])
    const work = await api.GET('/api/v1/me/work')
    expect(work.data?.research_to_do.map((row) => [row.idea.key, row.can_view_project])).toEqual([
      ['TOOL-7', false],
    ])
    expect(work.data?.counts).toMatchObject({ research_to_do: 1, research_overdue: 0 })
    expect(work.data?.owned).toEqual([])
    expect(work.data?.recent).toEqual([])
  })
})

describe('assigning the research', () => {
  it('assigns, notifies the new researcher once a day, audits and is idempotent', async () => {
    await signIn(USERS.alice) // TOOL admin
    const due = new Date(Date.now() + 3 * 86_400_000).toISOString()
    const first = await assign('TOOL-5', USERS.dave, due)
    expect(first.data?.assignment).toMatchObject({
      researcher: { id: USERS.dave },
      researcher_in_project: true,
      due_at: due,
    })
    const events = getDb().events.length
    await assign('TOOL-5', USERS.dave, due)
    expect(getDb().events.length).toBe(events)
    const asked = getDb().notifications.filter(
      (n) => n.user_id === USERS.dave && n.type === 'researcher_assigned',
    )
    expect(asked).toHaveLength(1)
    expect(asked[0]?.payload).toEqual({ due_at: due })
  })

  it('refuses the ineligible (422) and, for an owner in a private project, outsiders (403)', async () => {
    await signIn(USERS.alice)
    const agent = getDb().users.find((u) => u.is_service_account)
    const refused = await rejection(assign('TOOL-5', agent?.id ?? USERS.jonas))
    expect(refused).toMatchObject({ status: 422, code: 'researcher_not_eligible' })
    const inactive = await rejection(assign('TOOL-5', USERS.jonas))
    expect(inactive.code).toBe('researcher_not_eligible')
    endSession()
    await signIn(USERS.bob) // TOOL-7's owner, a member (not an admin)
    const outsider = await rejection(assign('TOOL-7', USERS.emma))
    expect(outsider).toMatchObject({ status: 403, code: 'outside_researcher_needs_admin' })
    const research = await api.GET('/api/v1/ideas/{idea}/research', idea('TOOL-7'))
    expect(research.data?.permissions).toMatchObject({
      can_assign: true,
      can_assign_outside_researcher: false,
    })
    // A member is fine (Dave has a role in Internal Tools).
    expect((await assign('TOOL-7', USERS.dave)).data?.assignment.researcher?.id).toBe(USERS.dave)
  })

  it('ends the assignment on close, step off and when the researcher loses their role', async () => {
    await signIn(USERS.alice)
    await api.POST('/api/v1/ideas/{idea}/status', {
      ...idea('TOOL-10'),
      body: { status: 'closed', resolution: 'parked' },
    })
    const tool10 = getDb().ideas.find((i) => i.researcher_id === USERS.kofi)
    expect(tool10).toBeUndefined()
    // Grace (a direct viewer) researches TOOL-5; removing her from Internal Tools ends it (S1 b).
    await assign('TOOL-5', USERS.grace)
    await api.DELETE('/api/v1/projects/{slug}/members/{user_id}', {
      params: { path: { slug: 'internal-tools', user_id: USERS.grace } },
    })
    expect(getDb().ideas.some((i) => i.researcher_id === USERS.grace)).toBe(false)
    expect(getDb().audit.at(-1)?.details).toMatchObject({ reason: 'left_project' })
  })
})

describe('My work: Research to do', () => {
  it('lists Alice’s overdue research first, with the counts', async () => {
    await signIn(USERS.alice)
    const { data } = await api.GET('/api/v1/me/work')
    expect(data?.research_to_do[0]).toMatchObject({
      idea: { key: 'GREEN-3' },
      overdue: true,
      as_owner: false,
      can_view_project: true,
      progress: { required_open: 1 },
    })
    expect(data?.counts.research_overdue).toBe(1)
    expect(data?.owned.every((group) => group.ideas.length <= 10)).toBe(true)
  })

  it('lists an owner’s idea with a research due date as their own', async () => {
    await signIn(USERS.carol)
    const { data } = await api.GET('/api/v1/me/research-to-do')
    expect(data?.items.map((row) => [row.idea.key, row.as_owner])).toContainEqual(['GREEN-1', true])
  })
})
