import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import { getDb, resetDb, USERS } from '@/mocks/db'
import { unsubscribeToken } from '@/mocks/notifications'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

/**
 * The Phase 3 mock (contract-phase3): the fan-out, preferences, the inbox,
 * unsubscribe links and Admin → Email, over HTTP like the screens use them.
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
  endSession()
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

async function inbox() {
  const { data } = await api.GET('/api/v1/me/notifications', { params: { query: { limit: 100 } } })
  return data?.items ?? []
}

describe('the inbox', () => {
  it('lists Alice’s notifications newest first with five unread, and never a score', async () => {
    await signIn(USERS.alice)
    const items = await inbox()
    expect(items.length).toBeGreaterThanOrEqual(10)
    const times = items.map((item) => item.created_at)
    expect([...times].sort().reverse()).toEqual(times)
    // Every type, Phase 8b's two included (read: the unread count stays five).
    expect(new Set(items.map((item) => item.type)).size).toBe(9)
    const { data: summary } = await api.GET('/api/v1/me/notifications/summary')
    expect(summary).toEqual({ unread_count: 5, email_available: true, email_trouble: false })
    expect(JSON.stringify(items)).not.toMatch(/"score|aggregate|recommendation/)
  })

  it('hides notifications about ideas the user can no longer view', async () => {
    await signIn(USERS.emma) // no role in the private Internal Tools project
    const items = await inbox()
    expect(items.map((item) => item.idea.key)).not.toContain('TOOL-2')
    expect(items.length).toBe(1)
  })

  it('marks one read (idempotent), all of one idea, then all', async () => {
    await signIn(USERS.alice)
    const first = (await inbox()).find((item) => item.read_at === null)
    if (!first) throw new Error('expected an unread notification')
    for (let i = 0; i < 2; i++) {
      const { response } = await api.POST('/api/v1/me/notifications/{notification_id}/read', {
        params: { path: { notification_id: first.id } },
      })
      expect(response.status).toBe(204)
    }
    const { data: afterIdea } = await api.POST('/api/v1/me/notifications/read-all', {
      params: { query: { idea: 'cust-1' } },
    })
    expect(afterIdea?.unread_count).toBe(2) // CUST-2's comment and TOOL-2's evaluations
    const { data: afterAll } = await api.POST('/api/v1/me/notifications/read-all', {})
    expect(afterAll?.unread_count).toBe(0)
    const unread = await api.GET('/api/v1/me/notifications', {
      params: { query: { unread: true } },
    })
    expect(unread.data?.items).toEqual([])
  })

  it('answers 404 for someone else’s notification', async () => {
    await signIn(USERS.alice)
    const mine = (await inbox())[0]
    await signIn(USERS.bob)
    const error = await rejection(
      api.POST('/api/v1/me/notifications/{notification_id}/read', {
        params: { path: { notification_id: mine?.id ?? '' } },
      }),
    )
    expect(error.status).toBe(404)
  })
})

describe('the fan-out', () => {
  it('invites an evaluator in-app and by email, never the actor', async () => {
    await signIn(USERS.alice) // owner of CUST-5
    await api.POST('/api/v1/ideas/{idea}/evaluators', {
      params: { path: { idea: 'CUST-5' } },
      body: { user_ids: [USERS.bob, USERS.alice] },
    })
    const db = getDb()
    const sent = db.notifications.filter(
      (n) =>
        n.type === 'evaluator_invited' &&
        n.created_at > new Date(Date.now() - 60_000).toISOString(),
    )
    expect(sent.map((n) => n.user_id)).toEqual([USERS.bob])
    expect(sent[0]?.email_mode).toBe('immediate')
    expect(db.outbox.find((row) => row.id === sent[0]?.email_id)?.status).toBe('queued')
    // The invitation carries the due date the request set (fan-out after the last write).
    expect(sent[0]?.payload.due_at).toBe(
      db.ideas.find((i) => i.title.startsWith('Loyalty'))?.evaluation_due_at,
    )

    await signIn(USERS.bob)
    const invite = (await inbox())[0]
    expect(invite).toMatchObject({ type: 'evaluator_invited', idea: { key: 'CUST-5' } })
  })

  it('writes no outbox rows when SMTP isn’t configured', async () => {
    resetDb({ email: 'off' })
    await signIn(USERS.alice)
    const before = getDb().outbox.length
    await api.POST('/api/v1/ideas/{idea}/evaluators', {
      params: { path: { idea: 'CUST-5' } },
      body: { user_ids: [USERS.bob] },
    })
    const db = getDb()
    expect(db.outbox.length).toBe(before)
    expect(db.notifications.at(-1)).toMatchObject({ user_id: USERS.bob, email_mode: 'off' })
    const { data } = await api.GET('/api/v1/me/notifications/summary')
    expect(data?.email_available).toBe(false)
  })

  it('follows the preference: digest types wait, off types aren’t emailed', async () => {
    await signIn(USERS.carol) // owner of CUST-7, which Bob watches as an evaluator
    await api.POST('/api/v1/ideas/{idea}/status', {
      params: { path: { idea: 'CUST-7' } },
      body: { status: 'shortlisted' },
    })
    const changed = getDb().notifications.filter(
      (n) =>
        n.type === 'status_changed' &&
        n.actor_id === USERS.carol &&
        n.dedupe_key.startsWith('status_changed:7'),
    )
    const alice = changed.find((n) => n.user_id === USERS.alice)
    const bob = changed.find((n) => n.user_id === USERS.bob)
    expect(alice).toMatchObject({ email_mode: 'digest', email_id: null })
    expect(bob).toMatchObject({ email_mode: 'off', email_id: null }) // Bob turned status emails off
    expect(changed.some((n) => n.user_id === USERS.carol)).toBe(false)
  })
})

describe('@mentions in comments', () => {
  const token = (id: string, label: string) => `@[${label}](user:${id})`

  it('rewrites labels to current names and notifies people with a project role', async () => {
    await signIn(USERS.alice)
    const { data } = await api.POST('/api/v1/ideas/{idea}/comments', {
      params: { path: { idea: 'CUST-2' } },
      body: {
        body_md: `${token(USERS.bob, 'The CEO')} and ${token(USERS.ivan, 'Ivan')} and ${token(USERS.jonas, 'Jonas')}, thoughts?`,
      },
    })
    const body = data?.type === 'comment' ? data.comment.body_md : ''
    expect(body).toContain(token(USERS.bob, 'Bob Chen')) // impersonation fixed
    expect(body).toContain('@Jonas') // inactive: plain text
    expect(body).not.toContain(`user:${USERS.jonas}`)
    const mentions = getDb().notifications.filter(
      (n) =>
        n.type === 'mention' &&
        n.actor_id === USERS.alice &&
        n.created_at > new Date(Date.now() - 60_000).toISOString(),
    )
    // Ivan has no role in Customer Innovation: no notification.
    expect(mentions.map((n) => n.user_id)).toEqual([USERS.bob])
  })

  it('refuses more than 20 people', async () => {
    await signIn(USERS.alice)
    const ids = Array.from(
      { length: 21 },
      (_, i) => `20000000-0000-4000-8000-${String(i).padStart(12, '0')}`,
    )
    const error = await rejection(
      api.POST('/api/v1/ideas/{idea}/comments', {
        params: { path: { idea: 'CUST-2' } },
        body: { body_md: ids.map((id) => token(id, 'x')).join(' ') },
      }),
    )
    expect(error).toMatchObject({ status: 422, code: 'too_many_mentions' })
  })
})

describe('email preferences', () => {
  it('shows every type with its default, and choosing the default clears the choice', async () => {
    await signIn(USERS.alice)
    const { data } = await api.GET('/api/v1/me/notification-preferences')
    expect(data?.items.map((item) => item.type)).toEqual([
      'owner_assigned',
      'evaluator_invited',
      'evaluation_reminder',
      'evaluations_complete',
      'status_changed',
      'comment',
      'mention',
      'researcher_assigned',
      'research_reminder',
    ])
    expect(data?.items.find((item) => item.type === 'researcher_assigned')?.default_mode).toBe(
      'immediate',
    )
    expect(data?.items.find((item) => item.type === 'comment')).toEqual({
      type: 'comment',
      mode: 'immediate',
      default_mode: 'digest',
    })
    await api.PATCH('/api/v1/me/notification-preferences', { body: { comment: 'digest' } })
    expect(getDb().notificationPrefs[USERS.alice]).toEqual({})
    const error = await rejection(
      api.PATCH('/api/v1/me/notification-preferences', {
        body: { comment: 'weekly' as 'off' },
      }),
    )
    expect(error.status).toBe(422)
  })
})

describe('unsubscribe links', () => {
  it('needs no session; GET changes nothing, POST turns the type off (idempotent)', async () => {
    const token = unsubscribeToken(USERS.alice, 'mention')
    const { data: info } = await api.GET('/api/v1/unsubscribe', { params: { query: { token } } })
    expect(info).toEqual({
      scope: 'mention',
      types: ['mention'],
      unsubscribed: false,
      email_hint: 'a•••@example.com',
    })
    for (let i = 0; i < 2; i++) {
      const { data } = await api.POST('/api/v1/unsubscribe', { params: { query: { token } } })
      expect(data?.unsubscribed).toBe(true)
    }
    expect(getDb().notificationPrefs[USERS.alice]?.mention).toBe('off')
  })

  it('digest: turns off what is in the digest now; only an all-scoped link turns off everything', async () => {
    const token = unsubscribeToken(USERS.alice, 'digest')
    const { data } = await api.POST('/api/v1/unsubscribe', { params: { query: { token } } })
    expect(data).toMatchObject({ scope: 'digest', types: ['status_changed'], unsubscribed: true })
    const widened = await rejection(
      api.POST('/api/v1/unsubscribe', { params: { query: { token, all: true } } }),
    )
    expect(widened.status).toBe(403)
    expect(widened.code).toBe('insufficient_scope')
    const { data: all } = await api.POST('/api/v1/unsubscribe', {
      params: { query: { token: unsubscribeToken(USERS.alice, 'all') } },
    })
    expect(all).toMatchObject({ scope: 'all', unsubscribed: true })
    expect(all?.types).toHaveLength(9)
  })

  it('answers 404 for forged, truncated or inactive users’ tokens, 422 for junk', async () => {
    const good = unsubscribeToken(USERS.alice, 'comment')
    const [payload] = good.split('.')
    for (const token of [
      `${payload ?? ''}.bW9jay0x`,
      good.slice(0, -2),
      unsubscribeToken(USERS.jonas, 'all'),
    ]) {
      const error = await rejection(
        api.GET('/api/v1/unsubscribe', { params: { query: { token } } }),
      )
      expect(error.status).toBe(404)
    }
    const junk = await rejection(
      api.GET('/api/v1/unsubscribe', { params: { query: { token: 'short' } } }),
    )
    expect(junk.status).toBe(422)
  })
})

describe('Admin → Email', () => {
  it('is for platform admins only', async () => {
    await signIn(USERS.alice)
    expect((await rejection(api.GET('/api/v1/admin/email'))).status).toBe(403)
    expect((await rejection(api.GET('/api/v1/admin/email/outbox'))).status).toBe(403)
  })

  it('shows the settings without secrets, and the outbox with retryable failures', async () => {
    await signIn(USERS.priya)
    const { data: config } = await api.GET('/api/v1/admin/email')
    expect(config).toMatchObject({ configured: true, username_set: true, password_set: true })
    expect(JSON.stringify(config)).not.toMatch(/password"\s*:\s*"/)
    const { data: failed } = await api.GET('/api/v1/admin/email/outbox', {
      params: { query: { status: ['failed'] } },
    })
    expect(failed?.items.map((email) => email.retryable)).toEqual([true, true, false])
    const old = failed?.items.find((email) => !email.retryable)
    const error = await rejection(
      api.POST('/api/v1/admin/email/outbox/{email_id}/retry', {
        params: { path: { email_id: old?.id ?? '' } },
      }),
    )
    expect(error).toMatchObject({ status: 409, code: 'email_not_retryable' })
    const recent = failed?.items[0]
    const { data: retried } = await api.POST('/api/v1/admin/email/outbox/{email_id}/retry', {
      params: { path: { email_id: recent?.id ?? '' } },
    })
    expect(retried).toMatchObject({ status: 'queued', attempts: 0, retryable: false })
    const { data: all } = await api.POST('/api/v1/admin/email/outbox/retry-failed', {})
    expect(all?.retried).toBe(1)
  })

  it('queues a test email (202), refuses lists and .invalid, and throttles at 5 per 10 minutes', async () => {
    await signIn(USERS.priya)
    const { data, response } = await api.POST('/api/v1/admin/email/test', { body: { to: null } })
    expect(response.status).toBe(202)
    expect(data).toMatchObject({ type: 'test', status: 'queued', max_attempts: 1 })
    for (const to of [
      'a@example.com,b@example.com',
      'Ops <ops@example.com>',
      'x@soundings.invalid',
    ]) {
      const error = await rejection(api.POST('/api/v1/admin/email/test', { body: { to } }))
      expect(error.status).toBe(422)
    }
    for (let i = 0; i < 4; i++)
      await api.POST('/api/v1/admin/email/test', { body: { to: 'ops@example.com' } })
    const limited = await rejection(
      api.POST('/api/v1/admin/email/test', { body: { to: 'ops@example.com' } }),
    )
    expect(limited).toMatchObject({ status: 429, code: 'too_many_attempts' })
    expect(limited.retryAfterSeconds).toBeGreaterThan(0)
    // Audited without the address.
    const audit = getDb().audit.filter((entry) => entry.action === 'email.test_send')
    expect(audit).toHaveLength(5)
    expect(JSON.stringify(audit)).not.toContain('ops@example.com')
  })

  it('answers 409 smtp_not_configured when email is off, and flags trouble for admins only', async () => {
    resetDb({ email: 'off' })
    await signIn(USERS.priya)
    const error = await rejection(api.POST('/api/v1/admin/email/test', { body: {} }))
    expect(error).toMatchObject({ status: 409, code: 'smtp_not_configured' })

    resetDb({ email: 'failing' })
    await signIn(USERS.priya)
    expect((await api.GET('/api/v1/me/notifications/summary')).data?.email_trouble).toBe(true)
    await signIn(USERS.alice)
    expect((await api.GET('/api/v1/me/notifications/summary')).data?.email_trouble).toBe(false)
  })
})
