import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import openapi from '@/api/generated/openapi.json'
import { resetDb, USERS } from '@/mocks/db'
import { handlers } from '@/mocks/handlers'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  // Keep these tests fast and deterministic.
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

describe('coverage', () => {
  it('has a handler for every operation in the OpenAPI contract', () => {
    const normalise = (path: string) => path.replace(/\{[^}]+\}|:[A-Za-z]+/g, ':p')
    const handled = new Set(
      handlers.map((handler) => {
        const info = handler.info as { method?: string; path?: string }
        return `${String(info.method)} ${normalise(String(info.path).replace('*', ''))}`
      }),
    )
    const missing: string[] = []
    for (const [path, operations] of Object.entries(openapi.paths)) {
      for (const [method, operation] of Object.entries(operations as Record<string, unknown>)) {
        if (!['get', 'post', 'put', 'patch', 'delete'].includes(method)) continue
        const key = `${method.toUpperCase()} ${normalise(path)}`
        if (!handled.has(key)) {
          missing.push(`${(operation as { operationId: string }).operationId} (${key})`)
        }
      }
    }
    expect(missing).toEqual([])
  })
})

describe('auth and CSRF', () => {
  it('answers 401 without a session and signs in with the dev login', async () => {
    expect((await rejection(api.GET('/api/v1/auth/me'))).code).toBe('unauthorized')
    const { data: users } = await api.GET('/api/v1/auth/dev/users')
    expect(users?.[0]?.is_platform_admin).toBe(true)
    await signIn(USERS.alice)
    const { data: me } = await api.GET('/api/v1/auth/me')
    expect(me?.display_name).toBe('Alice Anders')
  })

  it('rejects writes without the CSRF header', async () => {
    await signIn(USERS.alice)
    document.cookie = 'soundings_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
    const error = await rejection(
      api.PUT('/api/v1/ideas/{idea}/watch', { params: { path: { idea: 'CUST-6' } } }),
    )
    expect(error).toMatchObject({ status: 403, code: 'csrf_failed' })
  })

  it('rejects inactive users at dev login', async () => {
    const error = await rejection(
      api.POST('/api/v1/auth/dev/login', { body: { user_id: USERS.jonas } }),
    )
    expect(error).toMatchObject({ status: 422, code: 'user_not_found' })
  })
})

describe('blind evaluation over HTTP', () => {
  it('masks list, board, detail and evaluations until the evaluator submits', async () => {
    await signIn(USERS.alice)
    const list = await api.GET('/api/v1/projects/{slug}/ideas', {
      params: { path: { slug: 'customer-innovation' }, query: { sort: '-score', limit: 200 } },
    })
    const row = list.data?.items.find((item) => item.key === 'CUST-1')
    expect(row).toMatchObject({ score: null, score_hidden: true, high_disagreement: false })
    const evaluations = await api.GET('/api/v1/ideas/{idea}/evaluations', {
      params: { path: { idea: 'cust-1' } },
    })
    expect(evaluations.data).toEqual({ items: [], score_hidden: true })

    const { data: project } = await api.GET('/api/v1/projects/{slug}', {
      params: { path: { slug: 'customer-innovation' } },
    })
    const scores = (project?.rubric ?? []).map((criterion) => ({
      criterion_id: criterion.id,
      score: 4,
      comment: '',
    }))
    const saved = await api.PUT('/api/v1/ideas/{idea}/evaluations/me', {
      params: { path: { idea: 'CUST-1' } },
      body: { scores, recommendation: 'go', comment: '', submit: true },
    })
    expect(saved.data?.state).toBe('submitted')
    const { data: detail } = await api.GET('/api/v1/ideas/{idea}', {
      params: { path: { idea: 'CUST-1' } },
    })
    expect(detail?.score_hidden).toBe(false)
    expect(detail?.aggregate?.count).toBe(3)
    const after = await api.GET('/api/v1/ideas/{idea}/evaluations', {
      params: { path: { idea: 'CUST-1' } },
    })
    expect(after.data?.items).toHaveLength(3)
  })

  it('issues score-sorted cursors that hold no score', async () => {
    await signIn(USERS.alice)
    const { data } = await api.GET('/api/v1/projects/{slug}/ideas', {
      params: { path: { slug: 'customer-innovation' }, query: { sort: '-score', limit: 2 } },
    })
    const decoded = atob(data?.next_cursor ?? '')
    expect(decoded).not.toMatch(/\d\.\d/)
    const bad = await rejection(
      api.GET('/api/v1/projects/{slug}/ideas', {
        params: { path: { slug: 'customer-innovation' }, query: { cursor: 'nonsense' } },
      }),
    )
    expect(bad).toMatchObject({ status: 400, code: 'invalid_cursor' })
  })

  it('never lets a pending evaluator remove themselves', async () => {
    await signIn(USERS.alice) // admin of Internal Tools, pending on TOOL-1
    const error = await rejection(
      api.DELETE('/api/v1/ideas/{idea}/evaluators/{user_id}', {
        params: { path: { idea: 'TOOL-1', user_id: USERS.alice } },
      }),
    )
    expect(error).toMatchObject({ status: 403, code: 'cannot_remove_self' })
    const submitted = await rejection(
      api.DELETE('/api/v1/ideas/{idea}/evaluators/{user_id}', {
        params: { path: { idea: 'TOOL-1', user_id: USERS.bob } },
      }),
    )
    expect(submitted).toMatchObject({ status: 409, code: 'evaluator_has_submitted' })
  })

  it('lists every gap when a submission is incomplete', async () => {
    await signIn(USERS.alice)
    const error = await rejection(
      api.PUT('/api/v1/ideas/{idea}/evaluations/me', {
        params: { path: { idea: 'CUST-7' } },
        body: { scores: [], comment: '', submit: true },
      }),
    )
    expect(error.code).toBe('evaluation_incomplete')
    expect(error.problem?.errors).toHaveLength(6) // five criteria + recommendation
  })
})

describe('ideas', () => {
  it('creates an idea with the next key and records the event', async () => {
    await signIn(USERS.bob)
    const { data, response } = await api.POST('/api/v1/projects/{slug}/ideas', {
      params: { path: { slug: 'customer-innovation' } },
      body: {
        title: 'Returns by locker',
        summary: 'Drop returns at a parcel locker.',
        description_md: '',
        tags: ['Returns', 'lockers'],
      },
    })
    expect(response.status).toBe(201)
    expect(data?.key).toBe('CUST-21')
    expect(data?.tags).toEqual(['lockers', 'returns']) // existing spelling kept
    const { data: activity } = await api.GET('/api/v1/ideas/{idea}/activity', {
      params: { path: { idea: 'CUST-21' } },
    })
    expect(activity?.items[0]?.type).toBe('idea_created')
  })

  it('follows the check order: 404 before 403, 403 before 409', async () => {
    await signIn(USERS.ivan) // no memberships
    const hidden = await rejection(
      api.GET('/api/v1/ideas/{idea}', { params: { path: { idea: 'TOOL-1' } } }),
    )
    expect(hidden.status).toBe(404) // private project
    const denied = await rejection(
      api.POST('/api/v1/ideas/{idea}/status', {
        params: { path: { idea: 'CUST-1' } },
        body: { status: 'shortlisted' },
      }),
    )
    expect(denied.status).toBe(403)
  })

  it('undoes a status change exactly with the inverse call', async () => {
    await signIn(USERS.alice)
    const move = await api.POST('/api/v1/ideas/{idea}/status', {
      params: { path: { idea: 'CUST-2' } },
      body: { status: 'closed', resolution: 'parked' },
    })
    expect(move.data).toMatchObject({
      status: 'closed',
      resolution: 'parked',
      status_label: 'Parked',
    })
    const back = await api.POST('/api/v1/ideas/{idea}/status', {
      params: { path: { idea: 'CUST-2' } },
      body: { status: 'evaluating' },
    })
    expect(back.data).toMatchObject({ status: 'evaluating', resolution: null })
  })

  it('computes My work for the signed-in user', async () => {
    await signIn(USERS.alice)
    const { data } = await api.GET('/api/v1/me/work')
    expect(data?.counts.evaluations_due).toBe(4)
    expect(data?.counts.evaluations_overdue).toBe(1)
    expect(data?.evaluations_due[0]?.overdue).toBe(true)
    expect(data?.evaluations_due.at(-1)?.due_at).toBeNull()
    expect(data?.owned.map((group) => group.status)).toEqual([
      'new',
      'evaluating',
      'shortlisted',
      'proposal',
      'closed',
    ])
  })
})
