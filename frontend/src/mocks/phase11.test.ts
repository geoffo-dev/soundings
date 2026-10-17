import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { ApiError } from '@/api/errors'
import { getDb, resetDb, USERS } from '@/mocks/db'
import { MOCK_AUTH_STORAGE_KEY } from '@/mocks/auth-config'
import { PHASE11_SUBMISSIONS, PHASE11_TOKENS } from '@/mocks/phase11-fixtures'
import { TRACKING_TOKENS } from '@/mocks/phase4-fixtures'
import { confirmationToken } from '@/mocks/public'
import { server } from '@/mocks/server'
import { endSession } from '@/mocks/session'

/*
 * Phase 11 in the mock (contract-phase11): messages between the team and the person
 * who sent an idea through the public form. GREEN-13 (owner Grace, confirmed address,
 * four messages), GREEN-14 (Ana's address unconfirmed: tracking page only), GREEN-15
 * (the submitter's details erased), GREEN-10 (held for moderation; Carol asked first),
 * GREEN-9 (Jo: the team hasn't written). Carol is Sustainability's admin; Alice, Emma
 * and Grace are members; Priya is a platform admin; Ivan has no role.
 */

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
beforeEach(() => {
  resetDb()
  localStorage.setItem('soundings-mock-latency', 'none')
})
afterEach(() => {
  server.resetHandlers()
  endSession()
  localStorage.removeItem(MOCK_AUTH_STORAGE_KEY)
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
const submission = (key: string) => api.GET('/api/v1/ideas/{idea}/submission', idea(key))
const list = (key: string) => api.GET('/api/v1/ideas/{idea}/submission/messages', idea(key))
const send = (key: string, body: string) =>
  api.POST('/api/v1/ideas/{idea}/submission/messages', { ...idea(key), body: { body } })
const track = (token: string) => api.POST('/api/v1/public/track', { body: { token } })
const reply = (token: string, body: string) =>
  api.POST('/api/v1/public/track/messages', { body: { token, body } })
const ideaId = (key: string) => {
  const number = Number(key.split('-')[1])
  const found = getDb().ideas.find(
    (i) =>
      i.number === number && getDb().projects.find((p) => p.id === i.project_id)?.key === 'GREEN',
  )
  if (!found) throw new Error(`no ${key}`)
  return found.id
}

describe('public.message_submitter: who sees the conversation', () => {
  it.each([
    ['the owner (a member)', USERS.grace],
    ['the project admin', USERS.carol],
    ['a platform admin', USERS.priya],
  ])('%s reads it, oldest at the end of the newest-first pages', async (_who, user) => {
    await signIn(user)
    const { data } = await submission('GREEN-13')
    expect(data?.messages).toMatchObject({
      count: 4,
      last_direction: 'submitter',
      delivery: 'email',
      blocked: null,
    })
    expect(data?.permissions.can_message).toBe(true)
    const page = await list('GREEN-13')
    expect(page.data?.items.map((m) => m.direction)).toEqual([
      'submitter',
      'team',
      'submitter',
      'team',
    ])
    expect(page.data?.items.at(-1)?.author?.display_name).toBe('Grace Kim')
    expect(page.data?.items[0]?.author).toBeNull()
  })

  it.each([
    ['a member who doesn’t own it', USERS.alice],
    ['another member', USERS.emma],
    ['an internal non-member', USERS.ivan],
  ])('%s learns nothing: no summary, 403 on the routes', async (_who, user) => {
    await signIn(user)
    const { data } = await submission('GREEN-13')
    expect(data?.messages).toBeNull()
    expect(data?.permissions.can_message).toBe(false)
    expect(await rejection(list('GREEN-13'))).toMatchObject({ status: 403 })
    expect(await rejection(send('GREEN-13', 'Hello'))).toMatchObject({ status: 403 })
  })

  it('the break-glass account never reads it (c31)', async () => {
    localStorage.setItem(MOCK_AUTH_STORAGE_KEY, 'break_glass')
    await api.POST('/api/v1/auth/break-glass', {
      body: { username: 'break-glass', password: 'correct horse battery staple' },
    })
    const { data } = await submission('GREEN-13')
    expect(data?.messages).toBeNull()
    expect(await rejection(list('GREEN-13'))).toMatchObject({ status: 403 })
  })

  it('an idea that didn’t come through the form is 404', async () => {
    await signIn(USERS.carol)
    expect(await rejection(list('GREEN-1'))).toMatchObject({ status: 404 })
  })

  it('nothing reaches the feed or moves the idea', async () => {
    await signIn(USERS.grace)
    const before = getDb().ideas.find((i) => i.id === ideaId('GREEN-13'))?.last_activity_at
    const events = getDb().events.length
    await send('GREEN-13', 'Thanks!')
    expect(getDb().ideas.find((i) => i.id === ideaId('GREEN-13'))?.last_activity_at).toBe(before)
    expect(getDb().events).toHaveLength(events)
  })
})

describe('sending', () => {
  it('emails a confirmed address, audits without the text and shows on the tracking page', async () => {
    await signIn(USERS.grace)
    const { data, response } = await send('GREEN-13', '  Line one\r\nLine two  ')
    expect(response.status).toBe(201)
    expect(data).toMatchObject({ direction: 'team', body: 'Line one\nLine two', emailed: true })
    const db = getDb()
    expect(db.outbox.at(-1)).toMatchObject({
      type: 'submission_message',
      idea_id: ideaId('GREEN-13'),
    })
    const entry = db.audit.at(-1)
    expect(entry).toMatchObject({ action: 'submission.message', target_id: ideaId('GREEN-13') })
    expect(JSON.stringify(entry?.details)).not.toContain('Line one')
    const page = await track(PHASE11_TOKENS.sam)
    expect(page.data?.messages.at(-1)).toEqual({
      id: data?.id,
      direction: 'team',
      body: 'Line one\nLine two',
      created_at: data?.created_at,
    })
  })

  it('reaches an unconfirmed address on the tracking page only', async () => {
    await signIn(USERS.carol)
    expect((await submission('GREEN-14')).data?.messages?.delivery).toBe('tracking_page')
    const { data } = await send('GREEN-14', 'One more question')
    expect(data?.emailed).toBe(false)
    expect(
      getDb().outbox.some(
        (row) => row.type === 'submission_message' && row.idea_id === ideaId('GREEN-14'),
      ),
    ).toBe(false)
  })

  it('refuses text that shows nothing, NUL and tag characters, and more than 4,000 characters', async () => {
    await signIn(USERS.grace)
    for (const body of [
      ' \n ',
      'a\u0000b',
      `hi${String.fromCodePoint(0xe0041)}`,
      'x'.repeat(4_001),
    ]) {
      expect(await rejection(send('GREEN-13', body))).toMatchObject({ status: 422 })
    }
  })

  it('says why it can’t: erased details, archived project, public submission off', async () => {
    await signIn(USERS.grace)
    const erased = await submission('GREEN-15')
    expect(erased.data?.messages).toMatchObject({ count: 0, blocked: 'submitter_erased' })
    expect(erased.data?.permissions.can_message).toBe(false)
    expect(await rejection(send('GREEN-15', 'Hello'))).toMatchObject({
      status: 409,
      code: 'submitter_erased',
    })
    getDb().publicSubmissionEnabled = false
    expect(await rejection(send('GREEN-13', 'Hello'))).toMatchObject({
      code: 'public_submission_off',
    })
    const green = getDb().projects.find((p) => p.key === 'GREEN')
    if (green) green.archived_at = new Date().toISOString()
    // The archived project leads the 409s (review C6); reading still works.
    expect(await rejection(send('GREEN-13', 'Hello'))).toMatchObject({ code: 'project_archived' })
    expect((await list('GREEN-13')).data?.items).toHaveLength(4)
  })

  it('stops at 20 team messages to one submitter a day (429 with Retry-After)', async () => {
    await signIn(USERS.carol)
    for (let n = 0; n < 19; n += 1) await send('GREEN-14', `Message ${n}`)
    expect((await submission('GREEN-14')).data?.messages?.blocked).toBe('daily_limit')
    const error = await rejection(send('GREEN-14', 'One too many'))
    expect(error).toMatchObject({ status: 429, code: 'too_many_attempts' })
    expect(error.retryAfterSeconds).toBeGreaterThan(3_600)
  })

  it('may ask before approving an idea held for moderation (c19 doesn’t apply)', async () => {
    await signIn(USERS.carol)
    const { response } = await send('GREEN-10', 'Is the verge ours?')
    expect(response.status).toBe(201)
  })
})

describe('the tracking page', () => {
  it('shows the conversation without people, and the reply box once the team has written', async () => {
    const { data } = await track(PHASE11_TOKENS.sam)
    expect(data?.messages).toHaveLength(4)
    expect(Object.keys(data?.messages[0] ?? {}).sort()).toEqual([
      'body',
      'created_at',
      'direction',
      'id',
    ])
    expect(data).toMatchObject({
      team_messages_emailed: true,
      can_reply: true,
      reply_blocked: null,
      can_remove_email: true,
    })
    const jo = await track(TRACKING_TOKENS.jo)
    expect(jo.data).toMatchObject({
      messages: [],
      can_reply: false,
      reply_blocked: 'awaiting_team',
    })
    expect(await rejection(reply(TRACKING_TOKENS.jo, 'Hello?'))).toMatchObject({
      status: 409,
      code: 'awaiting_team',
    })
  })

  it('a reply notifies the owner and the writers, never with its text', async () => {
    const { data, response } = await reply(PHASE11_TOKENS.sam, 'Here are the numbers.')
    expect(response.status).toBe(201)
    expect(data?.messages.at(-1)).toMatchObject({
      direction: 'submitter',
      body: 'Here are the numbers.',
    })
    const fresh = getDb().notifications.filter(
      (n) => n.type === 'submitter_replied' && n.payload.message_id === data?.messages.at(-1)?.id,
    )
    expect(fresh.map((n) => n.user_id).sort()).toEqual([USERS.carol, USERS.grace].sort())
    expect(JSON.stringify(fresh)).not.toContain('numbers')
    await signIn(USERS.carol)
    const inbox = await api.GET('/api/v1/me/notifications')
    expect(inbox.data?.items[0]).toMatchObject({ type: 'submitter_replied', actor: null })
    await signIn(USERS.alice)
    const alices = await api.GET('/api/v1/me/notifications')
    expect(alices.data?.items.some((item) => item.type === 'submitter_replied')).toBe(false)
  })

  it('emails each recipient at most once an hour per idea (later replies inbox only)', async () => {
    await reply(PHASE11_TOKENS.sam, 'First')
    await reply(PHASE11_TOKENS.sam, 'Second')
    const carol = getDb().notifications.filter(
      (n) => n.type === 'submitter_replied' && n.user_id === USERS.carol,
    )
    // The seeded reply 40 minutes ago was emailed: both new ones reach the inbox only.
    expect(carol.slice(-2).map((n) => n.email_mode)).toEqual(['off', 'off'])
  })

  it('a reply to an idea held for moderation notifies nobody', async () => {
    const before = getDb().notifications.length
    const { response } = await reply(TRACKING_TOKENS.moderated, 'Inside the fence, yes.')
    expect(response.status).toBe(201)
    expect(getDb().notifications).toHaveLength(before)
  })

  it('allows 10 replies after each team message, then waits for the team', async () => {
    for (let n = 0; n < 9; n += 1) await reply(PHASE11_TOKENS.ana, `Reply ${n}`)
    // 9 + Ana's none before: the 10th still goes, the 11th waits.
    await reply(PHASE11_TOKENS.ana, 'Reply 9')
    expect((await track(PHASE11_TOKENS.ana)).data).toMatchObject({
      can_reply: false,
      reply_blocked: 'awaiting_team',
    })
    expect(await rejection(reply(PHASE11_TOKENS.ana, 'Reply 10'))).toMatchObject({
      code: 'awaiting_team',
    })
  })

  it('refuses a reply that isn’t JSON (415) or has no visible text (422)', async () => {
    const response = await fetch('/api/v1/public/track/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: JSON.stringify({ token: PHASE11_TOKENS.sam, body: 'Hi' }),
    })
    expect(response.status).toBe(415)
    expect(await rejection(reply(PHASE11_TOKENS.sam, '\u200b'))).toMatchObject({ status: 422 })
  })
})

describe('“Remove my email address” and the link email', () => {
  it('stops every email, keeps the link and the conversation', async () => {
    const { data } = await api.POST('/api/v1/public/track/forget-email', {
      body: { token: PHASE11_TOKENS.sam },
    })
    expect(data).toMatchObject({
      email_hint: null,
      can_remove_email: false,
      team_messages_emailed: false,
      wants_updates: false,
    })
    expect(data?.messages).toHaveLength(4)
    const submitterRows = getDb().outbox.filter(
      (row) => row.idea_id === ideaId('GREEN-13') && row.type.startsWith('submission'),
    )
    expect(submitterRows).toEqual([])
    await signIn(USERS.grace)
    expect((await submission('GREEN-13')).data?.messages?.delivery).toBe('tracking_page')
  })

  it('is refused while the idea waits for that address to be confirmed', async () => {
    expect(
      await rejection(
        api.POST('/api/v1/public/track/forget-email', {
          body: { token: TRACKING_TOKENS.unconfirmed },
        }),
      ),
    ).toMatchObject({ status: 409, code: 'awaiting_confirmation' })
  })

  it('emails the tracking link on the first confirmation only', async () => {
    const token = confirmationToken('e0000000-0000-4000-8000-0000000f0004')
    const first = await api.POST('/api/v1/public/verify-email', { body: { token } })
    expect(first.data?.tracking_link_emailed).toBe(true)
    expect(
      getDb()
        .outbox.filter((row) => row.type === 'submission_link')
        .at(-1)?.to_address,
    ).toBe('sam@example.org')
    const again = await api.POST('/api/v1/public/verify-email', { body: { token } })
    expect(again.data?.tracking_link_emailed).toBe(false)
  })

  it('erasing the details deletes the conversation', async () => {
    await api.POST('/api/v1/public/track/erase', { body: { token: PHASE11_TOKENS.sam } })
    expect(
      getDb().submissionMessages.filter((m) => m.submission_id === PHASE11_SUBMISSIONS.sam),
    ).toEqual([])
  })
})
