import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import { getDb, PROJECTS, resetDb, USERS } from '@/mocks/db'
import { API_KEY_PATTERN } from '@/mocks/api-keys'
import { API_KEYS, PHASE5_USERS, SUGGESTIONS } from '@/mocks/phase5-fixtures'
import { server } from '@/mocks/server'
import { endSession, startSession } from '@/mocks/session'

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

const inDays = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString()

describe('your API keys', () => {
  it('lists your keys that aren’t revoked, newest first, with their state', async () => {
    await signIn(USERS.alice)
    const { data } = await api.GET('/api/v1/me/api-keys')
    expect(data?.items.map((key) => [key.name, key.state])).toEqual([
      ['Claude Desktop', 'active'],
      ['Weekly report script', 'active'],
      ['Old laptop', 'expired'],
    ])
    expect(data?.items[0]).toMatchObject({
      prefix: 'sdg_Cl4uDeD3sk7p',
      scopes: ['read', 'evaluate', 'mcp'],
      restricted: true,
      projects: [{ name: 'Customer Innovation' }],
    })
    expect(JSON.stringify(data)).not.toMatch(/secret/)
    expect(data).toMatchObject({ max_keys: 25, can_create: true })
  })

  it('creates a key once: the secret only in the 201, read added to write', async () => {
    await signIn(USERS.alice)
    const { data, response } = await api.POST('/api/v1/me/api-keys', {
      body: {
        name: '  Claude Code ',
        scopes: ['mcp', 'write'],
        expires_at: inDays(30),
        project_ids: [PROJECTS.cust],
      },
    })
    expect(response.status).toBe(201)
    expect(data?.secret).toMatch(API_KEY_PATTERN)
    expect(data?.secret.startsWith(data.key.prefix)).toBe(true)
    expect(data?.key).toMatchObject({ name: 'Claude Code', scopes: ['read', 'write', 'mcp'] })
    const list = await api.GET('/api/v1/me/api-keys')
    expect(JSON.stringify(list.data)).not.toContain(data?.secret)
    const audit = getDb().audit.at(-1)
    expect(audit).toMatchObject({ action: 'api_key.create', target_id: USERS.alice })
    expect(JSON.stringify(audit)).not.toContain(data?.secret)
  })

  it('refuses bad input in the contract’s order', async () => {
    await signIn(USERS.alice)
    const create = (body: Record<string, unknown>) =>
      rejection(api.POST('/api/v1/me/api-keys', { body: body as never }))
    expect(await create({ name: 'x', scopes: [] })).toMatchObject({ status: 422 })
    expect(await create({ name: 'x', scopes: ['read'], expires_at: inDays(400) })).toMatchObject({
      status: 422,
      code: 'validation_error',
    })
    expect(
      await create({ name: 'x', scopes: ['read'], expires_at: '2030-01-01T00:00:00' }),
    ).toMatchObject({ status: 422 })
    expect(
      await create({ name: 'x', scopes: ['read'], project_ids: [PROJECTS.tool.replace('2', '9')] }),
    ).toMatchObject({ status: 422, code: 'invalid_project' })
    expect(await create({ name: 'claude desktop', scopes: ['read'] })).toMatchObject({
      status: 409,
      code: 'api_key_name_taken',
    })
  })

  it('refuses a private project you can’t view as invalid_project', async () => {
    await signIn(USERS.ivan) // no roles: Internal Tools is private
    const error = await rejection(
      api.POST('/api/v1/me/api-keys', {
        body: { name: 'x', scopes: ['read'], project_ids: [PROJECTS.tool] },
      }),
    )
    expect(error).toMatchObject({ status: 422, code: 'invalid_project' })
  })

  it('stops at 25 keys', async () => {
    await signIn(USERS.alice)
    for (let i = 0; i < 22; i++) {
      await api.POST('/api/v1/me/api-keys', { body: { name: `Key ${i}`, scopes: ['read'] } })
    }
    const { data } = await api.GET('/api/v1/me/api-keys')
    expect(data).toMatchObject({ can_create: false })
    expect(
      await rejection(
        api.POST('/api/v1/me/api-keys', { body: { name: 'One more', scopes: ['read'] } }),
      ),
    ).toMatchObject({ status: 409, code: 'too_many_api_keys' })
  })

  it('revokes your own key (idempotent), never someone else’s', async () => {
    await signIn(USERS.alice)
    const revoke = (keyId: string) =>
      api.DELETE('/api/v1/me/api-keys/{key_id}', { params: { path: { key_id: keyId } } })
    expect((await revoke(API_KEYS.claudeDesktop)).response.status).toBe(204)
    expect((await revoke(API_KEYS.claudeDesktop)).response.status).toBe(204)
    expect(await rejection(revoke(API_KEYS.grafana))).toMatchObject({ status: 404 })
    const { data } = await api.GET('/api/v1/me/api-keys')
    expect(data?.items.map((key) => key.name)).not.toContain('Claude Desktop')
    // The name is free again.
    const again = await api.POST('/api/v1/me/api-keys', {
      body: { name: 'Claude Desktop', scopes: ['read'] },
    })
    expect(again.response.status).toBe(201)
  })

  it('never lets the break-glass account create a key (c20)', async () => {
    startSession(USERS.breakGlass) // the dev login doesn't offer it
    expect((await api.GET('/api/v1/me/api-keys')).data).toMatchObject({
      items: [],
      can_create: false,
    })
    expect(
      await rejection(api.POST('/api/v1/me/api-keys', { body: { name: 'x', scopes: ['read'] } })),
    ).toMatchObject({ status: 403, code: 'break_glass_account' })
  })
})

describe('admin API keys', () => {
  it('lists every key with its owner, filters and a total', async () => {
    await signIn(USERS.priya)
    const all = await api.GET('/api/v1/admin/api-keys')
    expect(all.data?.total).toBe(8) // Phase 6 adds Idea evaluator's key
    const agent = all.data?.items.find((key) => key.owner.id === PHASE5_USERS.agent)
    expect(agent).toMatchObject({ owner_is_service_account: true, created_by: { id: USERS.priya } })
    const dormant = await api.GET('/api/v1/admin/api-keys', {
      params: { query: { state: 'dormant' } },
    })
    expect(dormant.data?.items.map((key) => key.owner.display_name)).toEqual(['Mateo Rossi'])
    const byPrefix = await api.GET('/api/v1/admin/api-keys', {
      params: { query: { q: 'sdg_J1r4SyncB0b2' } },
    })
    expect(byPrefix.data?.items.map((key) => key.name)).toEqual(['Jira sync'])
    // A prefix matches exactly, not as part of one.
    const partial = await api.GET('/api/v1/admin/api-keys', {
      params: { query: { q: 'sdg_J1r4' } },
    })
    expect(partial.data?.total).toBe(0)
    const byUser = await api.GET('/api/v1/admin/api-keys', {
      params: { query: { user_id: USERS.alice } },
    })
    expect(byUser.data?.total).toBe(3)
  })

  it('is for platform admins only and revokes any key', async () => {
    await signIn(USERS.alice)
    expect(await rejection(api.GET('/api/v1/admin/api-keys'))).toMatchObject({ status: 403 })
    endSession()
    await signIn(USERS.priya)
    const { response } = await api.DELETE('/api/v1/admin/api-keys/{key_id}', {
      params: { path: { key_id: API_KEYS.agent } },
    })
    expect(response.status).toBe(204)
    expect(getDb().audit.at(-1)).toMatchObject({
      action: 'api_key.revoke',
      target_id: PHASE5_USERS.agent,
      details: { rule: 'api_key.manage_any', prefix: 'sdg_R3s3archAg3n' },
    })
  })

  it('revokes every key of someone deactivated', async () => {
    await signIn(USERS.priya)
    await api.PATCH('/api/v1/admin/users/{user_id}', {
      params: { path: { user_id: USERS.alice } },
      body: { is_active: false },
    })
    const { data } = await api.GET('/api/v1/admin/api-keys', {
      params: { query: { user_id: USERS.alice } },
    })
    expect(data?.total).toBe(0)
    const revokes = getDb().audit.filter(
      (entry) => entry.action === 'api_key.revoke' && entry.details.reason === 'deactivated',
    )
    expect(revokes).toHaveLength(3)
  })
})

describe('proposal suggestions', () => {
  const list = (idea = 'CUST-3') =>
    api.GET('/api/v1/ideas/{idea}/proposal/suggestions', { params: { path: { idea } } })
  const accept = (id: string, base: number) =>
    api.POST('/api/v1/ideas/{idea}/proposal/suggestions/{suggestion_id}/accept', {
      params: { path: { idea: 'CUST-3', suggestion_id: id } },
      body: { base_version: base },
    })
  const discard = (id: string) =>
    api.POST('/api/v1/ideas/{idea}/proposal/suggestions/{suggestion_id}/discard', {
      params: { path: { idea: 'CUST-3', suggestion_id: id } },
    })

  it('lists pending ones in section order with who may decide', async () => {
    await signIn(USERS.alice) // owner of CUST-3
    const { data } = await list()
    expect(data?.items.map((s) => [s.section_key, s.source, s.section_changed])).toEqual([
      ['summary', 'mcp', false],
      ['summary', 'ai', false],
      ['problem', 'api', true],
      ['benefits', 'ai', false],
    ])
    expect(data?.permissions).toEqual({ can_suggest: true, can_decide: true })
    endSession()
    await signIn(USERS.emma) // viewer in CUST
    expect((await list()).data?.permissions).toEqual({ can_suggest: false, can_decide: false })
    expect(await rejection(list('CUST-4'))).toMatchObject({ status: 404 }) // no proposal
  })

  it('accepts as a versioned save, with proposal_conflict for a stale base', async () => {
    await signIn(USERS.alice)
    const stale = await rejection(accept(SUGGESTIONS.carolSummary, 2))
    expect(stale).toMatchObject({ status: 409, code: 'proposal_conflict' })
    expect((stale.problem as { current?: { version: number } }).current?.version).toBe(3)
    const { data } = await accept(SUGGESTIONS.carolSummary, 3)
    expect(data?.suggestion.status).toBe('accepted')
    expect(data?.section).toMatchObject({ key: 'summary', version: 4 })
    expect(await rejection(accept(SUGGESTIONS.carolSummary, 4))).toMatchObject({
      code: 'suggestion_not_pending',
    })
    // The other Summary suggestion stays, now behind the section.
    const after = await list()
    expect(after.data?.items.find((s) => s.id === SUGGESTIONS.agentSummary)?.section_changed).toBe(
      true,
    )
  })

  it('discards (idempotent), never an accepted one; only writers decide', async () => {
    await signIn(USERS.bob) // member, not the owner
    expect(await rejection(discard(SUGGESTIONS.agentBenefits))).toMatchObject({ status: 403 })
    endSession()
    await signIn(USERS.alice)
    expect((await discard(SUGGESTIONS.agentBenefits)).data?.status).toBe('discarded')
    expect((await discard(SUGGESTIONS.agentBenefits)).data?.status).toBe('discarded')
    await accept(SUGGESTIONS.bobProblem, 3)
    expect(await rejection(discard(SUGGESTIONS.bobProblem))).toMatchObject({
      code: 'suggestion_not_pending',
    })
  })

  it('creates one pending suggestion per author and section', async () => {
    await signIn(USERS.carol)
    const create = (body_md: string, base_version?: number) =>
      api.POST('/api/v1/ideas/{idea}/proposal/suggestions', {
        params: { path: { idea: 'CUST-3' } },
        body: { section_key: 'summary', body_md, base_version },
      })
    const first = await create('A shorter summary.')
    expect(first.response.status).toBe(201)
    expect(first.data).toMatchObject({ source: 'api', base_version: 3, status: 'pending' })
    const mine = (await list()).data?.items.filter((s) => s.author?.id === USERS.carol)
    expect(mine?.map((s) => s.body_md)).toEqual(['A shorter summary.'])
    expect(await rejection(create('Too new', 9))).toMatchObject({ status: 422 })
    expect(await rejection(create('   '))).toMatchObject({ status: 422 })
  })
})
