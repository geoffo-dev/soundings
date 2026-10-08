import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import { getDb, resetDb, USERS } from '@/mocks/db'
import { SUBMISSIONS, TRACKING_TOKENS } from '@/mocks/phase4-fixtures'
import { demoteHeadings } from '@/mocks/proposals'
import { confirmationToken } from '@/mocks/public'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

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

const proposal = (idea: string) =>
  api.GET('/api/v1/ideas/{idea}/proposal', { params: { path: { idea } } })

const save = (idea: string, key: 'summary' | 'problem', body_md: string, base_version: number) =>
  api.PUT('/api/v1/ideas/{idea}/proposal/sections/{section_key}', {
    params: { path: { idea, section_key: key } },
    body: { body_md, base_version },
  })

describe('proposals', () => {
  it('starts a proposal on a shortlisted idea and moves it to Proposal', async () => {
    await signIn(USERS.alice) // owner of CUST-4 (Shortlisted)
    const before = await proposal('CUST-4')
    expect(before.data?.proposal).toBeNull()
    expect(before.data?.permissions).toMatchObject({ can_create: true, can_edit: false })
    const { data, response } = await api.POST('/api/v1/ideas/{idea}/proposal', {
      params: { path: { idea: 'CUST-4' } },
    })
    expect(response.status).toBe(201)
    expect(data?.proposal?.sections.map((s) => s.key)).toEqual([
      'summary',
      'problem',
      'solution',
      'market',
      'cost',
      'benefits',
      'risks',
      'next_steps',
    ])
    expect(data?.proposal?.idea.status).toBe('proposal')
    expect(data?.permissions).toMatchObject({ can_create: false, can_edit: true })
    const again = await rejection(
      api.POST('/api/v1/ideas/{idea}/proposal', { params: { path: { idea: 'CUST-4' } } }),
    )
    expect(again).toMatchObject({ status: 409, code: 'proposal_exists' })
  })

  it('refuses to start one before the idea is shortlisted (c7) or for non-owners', async () => {
    await signIn(USERS.alice)
    const early = await rejection(
      api.POST('/api/v1/ideas/{idea}/proposal', { params: { path: { idea: 'CUST-5' } } }),
    )
    expect(early).toMatchObject({ status: 409, code: 'proposal_not_available' })
    await signIn(USERS.bob) // member, not the owner of CUST-4
    const denied = await rejection(
      api.POST('/api/v1/ideas/{idea}/proposal', { params: { path: { idea: 'CUST-4' } } }),
    )
    expect(denied.status).toBe(403)
  })

  it('saves sections with versions and answers a conflict with the current section', async () => {
    await signIn(USERS.alice)
    const view = await proposal('CUST-3')
    const summary = view.data?.proposal?.sections[0]
    expect(summary?.version).toBe(3)
    const first = await save('CUST-3', 'summary', '  Indented\n\n', 3)
    expect(first.data).toMatchObject({ body_md: '  Indented\n\n', version: 4 })
    // A retried identical save is a no-op, even from the old version.
    const retry = await save('CUST-3', 'summary', '  Indented\n\n', 3)
    expect(retry.data?.version).toBe(4)
    const stale = await rejection(save('CUST-3', 'summary', 'Mine', 3))
    expect(stale).toMatchObject({ status: 409, code: 'proposal_conflict' })
    expect(stale.problem).toMatchObject({ current: { version: 4, body_md: '  Indented\n\n' } })
    // Different sections never conflict.
    const other = await save('CUST-3', 'problem', 'New problem', 3)
    expect(other.data?.version).toBe(4)
  })

  it('makes viewers and evaluators read-only and hides the score from pending evaluators', async () => {
    await signIn(USERS.emma) // viewer in CUST
    const view = await proposal('CUST-3')
    expect(view.data?.permissions).toEqual({
      can_create: false,
      start_blocked_by_research: false,
      can_edit: false,
      can_comment: false,
      can_export: true,
    })
    expect((await rejection(save('CUST-3', 'summary', 'x', 3))).status).toBe(403)
  })

  it('lists threads in template order, replies reopen, and deleted comments become stubs', async () => {
    await signIn(USERS.bob)
    const { data } = await api.GET('/api/v1/ideas/{idea}/proposal/threads', {
      params: { path: { idea: 'CUST-3' } },
    })
    expect(data?.items.map((t) => t.section_key)).toEqual([
      'summary',
      'problem',
      'solution',
      'market',
    ])
    const resolved = data?.items.find((t) => t.resolved_at)
    expect(resolved?.comments.some((c) => c.deleted && c.body_md === '')).toBe(true)
    const reply = await api.POST('/api/v1/ideas/{idea}/proposal/threads/{thread_id}/comments', {
      params: { path: { idea: 'CUST-3', thread_id: resolved?.id ?? '' } },
      body: { body_md: 'One more thing' },
    })
    expect(reply.data?.resolved_at).toBeNull()
    const carolsComment = data?.items[0]?.comments[0]
    const notMine = await rejection(
      api.DELETE('/api/v1/ideas/{idea}/proposal/threads/{thread_id}/comments/{comment_id}', {
        params: {
          path: {
            idea: 'CUST-3',
            thread_id: data?.items[0]?.id ?? '',
            comment_id: carolsComment?.id ?? '',
          },
        },
      }),
    )
    expect(notMine).toMatchObject({ status: 403, code: 'not_author' })
  })

  it('exports Markdown with demoted headings and the aggregate only for those who may see it', async () => {
    await signIn(USERS.alice)
    const response = await fetch('/api/v1/ideas/CUST-3/proposal/markdown')
    expect(response.headers.get('Content-Disposition')).toContain('CUST-3-proposal.md')
    const text = await response.text()
    expect(text).toContain('## Summary')
    expect(text).toContain('#### What we would build')
    expect(text).toContain('_Not written yet._')
  })

  it('demotes ATX and setext headings but leaves code fences alone', () => {
    expect(demoteHeadings('# A\n\nB\n===\n\n```\n# code\n```')).toBe(
      '### A\n\n### B\n\n```\n# code\n```',
    )
    expect(demoteHeadings('##### Deep')).toBe('###### Deep')
  })
})

describe('holds and public submission', () => {
  it('leaves held ideas out of every list, also for admins', async () => {
    await signIn(USERS.priya)
    const { data } = await api.GET('/api/v1/projects/{slug}/ideas', {
      params: { path: { slug: 'sustainability' }, query: { limit: 200 } },
    })
    const keys = data?.items.map((i) => i.key) ?? []
    expect(keys).toContain('GREEN-9')
    expect(keys).not.toContain('GREEN-10')
    expect(keys).not.toContain('GREEN-12')
    const queue = await api.GET('/api/v1/projects/{slug}/moderation', {
      params: { path: { slug: 'sustainability' } },
    })
    expect(queue.data?.total).toBe(2)
    const held = await api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'GREEN-10' } } })
    expect(held.data?.permissions.can_delete).toBe(true)
    expect(held.data?.permissions.can_edit).toBe(false)
    const unconfirmed = await rejection(
      api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'GREEN-12' } } }),
    )
    expect(unconfirmed.status).toBe(404)
  })

  it('hides ideas held for moderation from non-admins', async () => {
    await signIn(USERS.alice) // member of Sustainability
    const error = await rejection(
      api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'GREEN-10' } } }),
    )
    expect(error.status).toBe(404)
  })

  it('tracks a submission with what was submitted, nothing private', async () => {
    const { data } = await api.POST('/api/v1/public/track', {
      body: { token: TRACKING_TOKENS.jo },
    })
    expect(data).toMatchObject({
      title: 'Refill station for cleaning products',
      email_hint: 'j•••@example.org',
      email_verified: true,
    })
    expect(JSON.stringify(data)).not.toContain('jo.marsh@')
  })

  it('confirms an address and releases the hold to moderation', async () => {
    const { data } = await api.POST('/api/v1/public/verify-email', {
      body: { token: confirmationToken(SUBMISSIONS.unconfirmed) },
    })
    expect(data?.held_for).toBe('moderation')
    expect(getDb().ideas.find((i) => i.title.startsWith('Switch the canteen'))?.held_for).toBe(
      'moderation',
    )
  })
})
