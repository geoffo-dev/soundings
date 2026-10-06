import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import { extractGroupValues, normaliseIdpValue, testMapping } from '@/mocks/access'
import { GROUPS } from '@/mocks/access-fixtures'
import { MOCK_AUTH_STORAGE_KEY } from '@/mocks/auth-config'
import { getDb, resetDb, USERS } from '@/mocks/db'
import { effectiveRole, findUser } from '@/mocks/domain'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

/** Phase 2 mock rules (docs/api/contract-phase2.md): the bits the screens rely on. */

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
  localStorage.removeItem(MOCK_AUTH_STORAGE_KEY)
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

const PROJECT = { cust: '20000000-0000-4000-8000-000000000001' }

describe('IdP values and the groups claim (§3.5)', () => {
  it.each([
    ['/Innovation/Admins', 'innovation/admins'],
    ['  /viewers/ ', 'viewers'],
    ['//', ''],
    ['abc-123', 'abc-123'],
  ])('normalises %j to %j', (input, output) => {
    expect(normaliseIdpValue(input)).toBe(output)
  })

  it('reads a top-level claim name first, then a dotted path', () => {
    expect(extractGroupValues({ 'a.b': ['/X'], a: { b: ['/Y'] } }, 'a.b').values).toEqual(['x'])
    expect(extractGroupValues({ realm_access: { roles: ['Ops'] } }, 'realm_access.roles')).toEqual({
      claim_found: true,
      values: ['ops'],
      ignored_count: 0,
    })
    expect(extractGroupValues({}, 'groups')).toEqual({
      claim_found: false,
      values: [],
      ignored_count: 0,
    })
    expect(extractGroupValues({ groups: ['/a', 3, '/', '/A'] }, 'groups')).toEqual({
      claim_found: true,
      values: ['a'],
      ignored_count: 2,
    })
  })
})

describe('the mapping test (§3.12)', () => {
  it('adds matching groups for a user with no memberships', () => {
    const result = testMapping(getDb(), { groups: ['/innovation/members', '/nope'] }, null)
    expect(result.values).toEqual(['innovation/members', 'nope'])
    expect(result.groups).toEqual([
      expect.objectContaining({ effect: 'add', matched_values: ['innovation/members'] }),
    ])
    expect(result.project_roles.map((r) => [r.project.key, r.role])).toEqual([['CUST', 'member']])
  })

  it('removes managed and keeps additive synced memberships that no longer match', () => {
    const db = getDb()
    const kofi = findUser(db, USERS.kofi) ?? null
    const result = testMapping(db, { groups: [] }, kofi)
    expect(result.groups.map((g) => [g.group.name, g.effect])).toEqual([
      ['Innovation members', 'remove'],
      ['Tools members', 'remove'],
    ])
    expect(result.project_roles).toEqual([])
    const grace = findUser(db, USERS.grace) ?? null
    const additive = testMapping(db, { groups: [] }, grace)
    expect(additive.groups).toEqual([
      expect.objectContaining({ effect: 'keep', matched_values: [], sync_mode: 'additive' }),
    ])
  })
})

describe('roles through groups (§3.7)', () => {
  it('gives Kofi access only through groups, and Phase 1 roles stay as they were', () => {
    const db = getDb()
    expect(effectiveRole(db, PROJECT.cust, USERS.kofi)).toBe('member')
    expect(effectiveRole(db, PROJECT.cust, USERS.emma)).toBe('viewer')
    expect(effectiveRole(db, PROJECT.cust, USERS.ivan)).toBeNull()
  })

  it('lists everyone with access and why', async () => {
    await signIn(USERS.alice)
    const { data } = await api.GET('/api/v1/projects/{slug}/access', {
      params: { path: { slug: 'internal-tools' } },
    })
    const kofi = data?.items.find((entry) => entry.user.id === USERS.kofi)
    expect(kofi?.sources).toEqual([
      { kind: 'group', role: 'member', group: { id: GROUPS.toolsMembers, name: 'Tools members' } },
    ])
    const alice = data?.items.find((entry) => entry.user.id === USERS.alice)
    expect(alice?.role).toBe('admin')
    expect(alice?.sources.map((s) => s.kind)).toEqual(['direct', 'group'])
  })

  it('grants a group, guards the last admin, and answers the documented codes', async () => {
    await signIn(USERS.alice)
    const slug = 'internal-tools'
    const added = await api.POST('/api/v1/projects/{slug}/groups', {
      params: { path: { slug } },
      body: { group_id: GROUPS.contractors, role: 'admin' },
    })
    expect(added.response.status).toBe(201)
    const again = await rejection(
      api.POST('/api/v1/projects/{slug}/groups', {
        params: { path: { slug } },
        body: { group_id: GROUPS.contractors, role: 'member' },
      }),
    )
    expect(again).toMatchObject({ status: 409, code: 'already_granted' })
    const unknown = await rejection(
      api.POST('/api/v1/projects/{slug}/groups', {
        params: { path: { slug } },
        body: { group_id: '90000000-0000-4000-8000-0000000000ff', role: 'member' },
      }),
    )
    expect(unknown).toMatchObject({ status: 422, code: 'group_not_found' })
    // Make the tools group the only admin source: then it can't be demoted.
    await api.PATCH('/api/v1/projects/{slug}/groups/{group_id}', {
      params: { path: { slug, group_id: GROUPS.toolsMembers } },
      body: { role: 'admin' },
    })
    await api.PATCH('/api/v1/projects/{slug}/members/{user_id}', {
      params: { path: { slug, user_id: USERS.alice } },
      body: { role: 'member' },
    })
    const last = await rejection(
      api.DELETE('/api/v1/projects/{slug}/groups/{group_id}', {
        params: { path: { slug, group_id: GROUPS.toolsMembers } },
      }),
    )
    expect(last).toMatchObject({ status: 409, code: 'last_admin' })
  })

  it('counts members through groups', async () => {
    await signIn(USERS.alice)
    const { data } = await api.GET('/api/v1/projects/{slug}', {
      params: { path: { slug: 'internal-tools' } },
    })
    // Five direct, Kofi and Lena through Tools members, and Phase 6's Market scout (a viewer).
    expect(data?.member_count).toBe(8)
  })
})

describe('sign-in configuration (§3.1, §3.8)', () => {
  it('offers SSO and the dev login by default, break-glass only without SSO', async () => {
    expect((await api.GET('/api/v1/auth/config')).data).toEqual({
      sso: true,
      dev_login: true,
      break_glass: false,
    })
    localStorage.setItem(MOCK_AUTH_STORAGE_KEY, 'sso,break_glass')
    expect((await api.GET('/api/v1/auth/config')).data?.break_glass).toBe(false)
    localStorage.setItem(MOCK_AUTH_STORAGE_KEY, 'break_glass')
    expect((await api.GET('/api/v1/auth/config')).data).toEqual({
      sso: false,
      dev_login: false,
      break_glass: true,
    })
  })

  it('throttles break-glass failures with Retry-After, then signs in', async () => {
    localStorage.setItem(MOCK_AUTH_STORAGE_KEY, 'break_glass')
    const attempt = (password: string) =>
      api.POST('/api/v1/auth/break-glass', { body: { username: 'break-glass', password } })
    for (let i = 0; i < 5; i++) {
      expect(await rejection(attempt('wrong'))).toMatchObject({
        status: 401,
        code: 'invalid_credentials',
      })
    }
    const limited = await rejection(attempt('correct horse battery staple'))
    expect(limited).toMatchObject({ status: 429, code: 'too_many_attempts' })
    expect(limited.retryAfterSeconds).toBeGreaterThan(800)

    resetDb()
    const { data } = await attempt('correct horse battery staple')
    expect(data?.email).toBe('break-glass@soundings.invalid')
    expect(data?.auth_method).toBe('break_glass')
  })

  it('says how each session signed in', async () => {
    const { data: people } = await api.GET('/api/v1/auth/dev/users')
    expect(people?.every((person) => person.auth_method === null)).toBe(true)
    expect(people?.some((person) => person.email.endsWith('.invalid'))).toBe(false)
    await signIn(USERS.alice)
    expect((await api.GET('/api/v1/auth/me')).data?.auth_method).toBe('dev_login')
  })

  it('ends sessions whose method is no longer available', async () => {
    await signIn(USERS.alice)
    expect((await api.GET('/api/v1/auth/me')).data?.id).toBe(USERS.alice)
    localStorage.setItem(MOCK_AUTH_STORAGE_KEY, 'sso')
    expect(await rejection(api.GET('/api/v1/auth/me'))).toMatchObject({ status: 401 })
  })
})

describe('admin (§3.4, §3.5, §3.11)', () => {
  it('is for platform admins only', async () => {
    await signIn(USERS.alice)
    expect(await rejection(api.GET('/api/v1/admin/users'))).toMatchObject({
      status: 403,
      code: 'forbidden',
    })
  })

  it('pre-creates users with external IDs and guards c17 and c18', async () => {
    await signIn(USERS.priya)
    const created = await api.POST('/api/v1/admin/users', {
      body: {
        email: 'nia.lee@example.com',
        display_name: 'Nia Lee',
        is_platform_admin: false,
        external_ids: [{ kind: 'employee_no', value: 'E2001' }],
      },
    })
    expect(created.data).toMatchObject({ has_identity: false, external_ids: [{ value: 'E2001' }] })
    const taken = await rejection(
      api.POST('/api/v1/admin/users', {
        body: {
          email: 'other@example.com',
          display_name: 'Other',
          is_platform_admin: false,
          external_ids: [{ kind: 'employee_no', value: 'e2001' }],
        },
      }),
    )
    expect(taken).toMatchObject({ status: 409, code: 'external_id_taken' })
    const self = await rejection(
      api.PATCH('/api/v1/admin/users/{user_id}', {
        params: { path: { user_id: USERS.priya } },
        body: { is_platform_admin: false },
      }),
    )
    expect(self).toMatchObject({ status: 403, code: 'cannot_change_self' })
    const pending = await api.GET('/api/v1/admin/users', {
      params: { query: { has_identity: false } },
    })
    expect(pending.data?.items.map((u) => u.display_name)).toEqual([
      'Break-glass admin',
      // Phase 6: AI agents' service accounts never sign in.
      'Idea evaluator',
      'Lena Novak',
      'Market scout',
      'Nia Lee',
      // Phase 5: an AI agent's service account never signs in.
      'Research agent',
    ])
  })

  it('records admin changes in the audit log, newest first', async () => {
    await signIn(USERS.priya)
    await api.PATCH('/api/v1/admin/groups/{group_id}', {
      params: { path: { group_id: GROUPS.contractors } },
      body: { description: 'Agencies and freelancers.' },
    })
    const { data } = await api.GET('/api/v1/admin/audit', { params: { query: { limit: 2 } } })
    expect(data?.items[0]).toMatchObject({
      action: 'group.update',
      target_label: 'Contractors',
      details: { fields: ['description'], rule: 'platform.manage_groups' },
    })
    expect(data?.next_cursor).toBeTruthy()
  })
})
