import type { EmailStatus, EmailType } from '@/api/types'
import { recordAudit } from '@/mocks/access'
import { paginate } from '@/mocks/domain'
import {
  accepted,
  allowOnly,
  conflict,
  failValidation,
  forbidden,
  notFound,
  problemResponse,
  queryEnum,
  queryLimit,
  readJson,
  route,
  type RouteContext,
} from '@/mocks/http'
import {
  canReceiveEmail,
  emailConfig,
  isRetryable,
  outboxEmail,
  queueEmail,
  runMockWorker,
} from '@/mocks/notifications'

import { uuidParam } from '@/mocks/handlers/common'

/**
 * Admin settings → Email (contract-phase3 §2 "Admin: email", §3.10): the
 * config view, the test email, the outbox and retry. Platform admins only;
 * check order 401 → 422 shape → 403 → 404 → 422 business → 409 → 429.
 */

const STATUSES: EmailStatus[] = ['queued', 'sending', 'sent', 'failed', 'cancelled']
const TYPES: EmailType[] = [
  'owner_assigned',
  'evaluator_invited',
  'evaluation_reminder',
  'evaluations_complete',
  'status_changed',
  'comment',
  'mention',
  'digest',
  'test',
  'submission_received',
  'submission_status_changed',
]
/** `app.config.MAIL_ADDRESS_PATTERN`: one plain ASCII address, no names or lists. */
const MAIL_ADDRESS =
  /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/
const TEST_LIMIT = 5
const TEST_WINDOW_MS = 10 * 60_000

function requirePlatformAdmin(ctx: RouteContext): void {
  if (!ctx.user.is_platform_admin) forbidden('forbidden', 'Only platform admins can do this.')
}

function requireSmtp(ctx: RouteContext): void {
  if (!ctx.db.email.configured) {
    conflict('smtp_not_configured', 'Email is not configured (SOUNDINGS_SMTP_HOST).')
  }
}

function findEmail(ctx: RouteContext) {
  const id = uuidParam(ctx, 'emailId')
  requirePlatformAdmin(ctx)
  const row = ctx.db.outbox.find((email) => email.id === id)
  if (!row) notFound('Email not found.')
  return row
}

function badAddress(msg: string): never {
  failValidation([{ loc: ['body', 'to'], msg, type: 'value_error' }])
}

export const adminEmailHandlers = [
  route('get', '/admin/email', (ctx) => {
    requirePlatformAdmin(ctx)
    runMockWorker(ctx.db)
    return emailConfig(ctx.db)
  }),

  route('post', '/admin/email/test', async (ctx) => {
    const body = await readJson(ctx.request)
    allowOnly(body, ['to'])
    const raw = body.to
    if (raw !== undefined && raw !== null && typeof raw !== 'string') {
      failValidation([
        { loc: ['body', 'to'], msg: 'Input should be a valid string', type: 'string_type' },
      ])
    }
    const to = typeof raw === 'string' ? raw.trim() : null
    if (
      to !== null &&
      (to.length > 254 || !MAIL_ADDRESS.test(to) || (to.split('@')[0] ?? '').length > 64)
    ) {
      badAddress('must be one plain email address such as ops@example.com')
    }
    if (to !== null && /\.invalid$/i.test(to)) {
      badAddress('addresses under .invalid are reserved for system accounts')
    }
    requirePlatformAdmin(ctx)
    if (to === null && !canReceiveEmail(ctx.user)) {
      badAddress('Your own address can’t receive email: enter an address')
    }
    requireSmtp(ctx)
    const now = Date.now()
    const recent = ctx.db.outbox
      .filter(
        (row) =>
          row.type === 'test' &&
          row.requested_by_id === ctx.user.id &&
          Date.parse(row.created_at) > now - TEST_WINDOW_MS,
      )
      .map((row) => Date.parse(row.created_at))
      .sort((a, b) => a - b)
    if (recent.length >= TEST_LIMIT) {
      const wait = Math.max(1, Math.ceil(((recent[0] ?? now) + TEST_WINDOW_MS - now) / 1000))
      const response = problemResponse(429, 'too_many_attempts', 'Too many test emails.')
      response.headers.set('Retry-After', String(wait))
      throw response
    }
    const row = queueEmail(ctx.db, {
      type: 'test',
      recipient_user_id: to === null ? ctx.user.id : null,
      to_address: to,
      requested_by_id: ctx.user.id,
      max_attempts: 1,
      now,
    })
    recordAudit(ctx.db, ctx.user, 'email.test_send', null, {
      outbound_email_id: row.id,
      to_self: to === null,
    })
    return accepted(outboxEmail(ctx.db, row))
  }),

  route('get', '/admin/email/outbox', (ctx) => {
    const status = queryEnum(ctx.url, 'status', STATUSES)
    const type = queryEnum(ctx.url, 'type', TYPES)
    const limit = queryLimit(ctx.url, 50, 200)
    requirePlatformAdmin(ctx)
    runMockWorker(ctx.db)
    const rows = ctx.db.outbox
      .filter((row) => status.length === 0 || status.includes(row.status))
      .filter((row) => type.length === 0 || type.includes(row.type))
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
    const { page, next_cursor } = paginate(
      rows,
      ctx.url.searchParams.get('cursor'),
      limit,
      `outbox:${[...status].sort().join(',')}:${[...type].sort().join(',')}`,
    )
    return { items: page.map((row) => outboxEmail(ctx.db, row)), next_cursor }
  }),

  route('get', '/admin/email/outbox/:emailId', (ctx) => {
    runMockWorker(ctx.db)
    return outboxEmail(ctx.db, findEmail(ctx))
  }),

  route('post', '/admin/email/outbox/retry-failed', (ctx) => {
    requirePlatformAdmin(ctx)
    requireSmtp(ctx)
    const now = Date.now()
    const rows = ctx.db.outbox.filter((row) => isRetryable(row, now))
    for (const row of rows) {
      Object.assign(row, {
        status: 'queued',
        attempts: 0,
        last_error: null,
        next_attempt_at: new Date(now + 1_500).toISOString(),
        updated_at: new Date(now).toISOString(),
      })
    }
    recordAudit(ctx.db, ctx.user, 'email.retry', null, { count: rows.length })
    return { retried: rows.length }
  }),

  route('post', '/admin/email/outbox/:emailId/retry', (ctx) => {
    const row = findEmail(ctx)
    requireSmtp(ctx)
    const now = Date.now()
    if (!isRetryable(row, now)) {
      conflict('email_not_retryable', 'Only failed emails from the last few days can be retried.')
    }
    Object.assign(row, {
      status: 'queued',
      attempts: 0,
      last_error: null,
      next_attempt_at: new Date(now + 1_500).toISOString(),
      updated_at: new Date(now).toISOString(),
    })
    recordAudit(ctx.db, ctx.user, 'email.retry', null, { outbound_email_id: row.id })
    return outboxEmail(ctx.db, row, now)
  }),
]
