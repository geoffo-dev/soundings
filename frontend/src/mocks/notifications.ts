/**
 * Phase 3 rules of the mock API (docs/api/contract-phase3.md): the notification
 * fan-out, email preferences, the inbox items, the outbox with a pretend worker,
 * the admin email view and unsubscribe tokens. Close enough to build and test
 * the screens; the backend and its tests are the authority.
 *
 * Blind-safe like the API: nothing here ever reads or returns score data.
 */
import type {
  EmailConfig,
  EmailType,
  NotificationItem,
  NotificationMode,
  NotificationPreferences,
  NotificationSummary,
  NotificationType,
  OutboxEmail,
  OutboxStats,
  UnsubscribeInfo,
  UnsubscribeScope,
} from '@/api/types'
import { MAX_MENTIONS, mentionedUserIds, mentionLabel, MENTION_PATTERN } from '@/lib/mentions'

import type {
  MockComment,
  MockDb,
  MockEvent,
  MockIdea,
  MockNotification,
  MockOutboxEmail,
  MockUser,
} from './db'
import {
  canViewIdea,
  effectiveRole,
  evaluationOf,
  evaluationOpen,
  findUser,
  ideaRef,
  isPendingEvaluator,
  projectOf,
  rowsForIdea,
  statusLabel,
  userRef,
  userRefById,
} from './domain'

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

export const NOTIFICATION_TYPES: NotificationType[] = [
  'owner_assigned',
  'evaluator_invited',
  'evaluation_reminder',
  'evaluations_complete',
  'status_changed',
  'comment',
  'mention',
]

/** `app.schemas.notifications.DEFAULT_MODES`. */
export const DEFAULT_MODES: Record<NotificationType, NotificationMode> = {
  owner_assigned: 'immediate',
  evaluator_invited: 'immediate',
  evaluation_reminder: 'immediate',
  evaluations_complete: 'immediate',
  status_changed: 'digest',
  comment: 'digest',
  mention: 'immediate',
}

/** The mock instance's schedule (`SOUNDINGS_TIMEZONE`, `_DIGEST_HOUR`, `_REMINDER_DAYS`). */
export const MOCK_SCHEDULE = { timezone: 'Europe/London', digestHour: 8, reminderDays: [2, 0] }
export const MAX_ATTEMPTS = 12
const UNREAD_CAP = 100
const MENTION_EMAIL_CAP = 50
/** The pretend worker picks up new mail after this long (so "Sending…" is visible). */
const WORKER_DELAY_MS = 1_500

const iso = (ms: number) => new Date(ms).toISOString()

function nextId(db: MockDb, kind: string): string {
  db.seq += 1
  return `${kind}0000000-0000-4000-8000-${db.seq.toString(16).padStart(12, '0')}`
}

/* ------------------------------------------------------------------ */
/* Preferences                                                         */
/* ------------------------------------------------------------------ */

export function preferenceMode(db: MockDb, userId: string, type: NotificationType) {
  return db.notificationPrefs[userId]?.[type] ?? DEFAULT_MODES[type]
}

export function notificationPreferences(db: MockDb, user: MockUser): NotificationPreferences {
  return {
    email_available: db.email.configured,
    digest_hour: MOCK_SCHEDULE.digestHour,
    timezone: MOCK_SCHEDULE.timezone,
    items: NOTIFICATION_TYPES.map((type) => ({
      type,
      mode: preferenceMode(db, user.id, type),
      default_mode: DEFAULT_MODES[type],
    })),
  }
}

/** Stores only choices that differ from the default (choosing the default clears it). */
export function setPreference(
  db: MockDb,
  userId: string,
  type: NotificationType,
  mode: NotificationMode,
): void {
  const { [type]: _previous, ...others } = db.notificationPrefs[userId] ?? {}
  db.notificationPrefs[userId] = mode === DEFAULT_MODES[type] ? others : { ...others, [type]: mode }
}

/** One plain address that isn't reserved (§3.9 step 2). */
export function canReceiveEmail(user: MockUser): boolean {
  return (
    /^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/.test(user.email) &&
    !/\.invalid$/i.test(user.email)
  )
}

/* ------------------------------------------------------------------ */
/* Fan-out (§3.3)                                                      */
/* ------------------------------------------------------------------ */

interface Candidate {
  userId: string
  type: NotificationType
  payload?: Record<string, unknown>
  commentId?: string | null
  dedupeKey: string
}

function isNotifiable(
  db: MockDb,
  idea: MockIdea,
  user: MockUser | undefined,
  actorId: string | null,
) {
  if (!user || user.id === actorId) return false
  if (!user.is_active || user.is_service_account || user.is_break_glass) return false
  return canViewIdea(db, idea, user)
}

/** `evaluation.submit_own`: assigned, member or admin, evaluation open, not submitted. */
function mayEvaluate(db: MockDb, idea: MockIdea, userId: string): boolean {
  const role = effectiveRole(db, idea.project_id, userId)
  return (
    (role === 'member' || role === 'admin') &&
    isPendingEvaluator(db, idea, userId) &&
    evaluationOpen(idea) &&
    projectOf(db, idea).archived_at === null
  )
}

function mentionEmailsLastHour(db: MockDb, actorId: string, now: number): number {
  return db.notifications.filter(
    (n) =>
      n.type === 'mention' &&
      n.actor_id === actorId &&
      n.email_mode !== 'off' &&
      Date.parse(n.created_at) > now - HOUR,
  ).length
}

/** Inserts the notifications (one per person, deduplicated) and their immediate emails. */
export function notify(
  db: MockDb,
  idea: MockIdea,
  actorId: string | null,
  candidates: Candidate[],
  now = Date.now(),
): MockNotification[] {
  const created: MockNotification[] = []
  const seen = new Set<string>()
  for (const candidate of candidates) {
    if (seen.has(candidate.userId)) continue
    seen.add(candidate.userId)
    const user = findUser(db, candidate.userId)
    if (!user || !isNotifiable(db, idea, user, actorId)) continue
    const exists = db.notifications.some(
      (n) => n.user_id === user.id && n.dedupe_key === candidate.dedupeKey,
    )
    if (exists) continue
    let mode: NotificationMode =
      db.email.configured && canReceiveEmail(user)
        ? preferenceMode(db, user.id, candidate.type)
        : 'off'
    if (
      candidate.type === 'mention' &&
      actorId &&
      mentionEmailsLastHour(db, actorId, now) >= MENTION_EMAIL_CAP
    ) {
      mode = 'off'
    }
    const notification: MockNotification = {
      id: nextId(db, 'c'),
      user_id: user.id,
      type: candidate.type,
      idea_id: idea.id,
      actor_id: actorId,
      comment_id: candidate.commentId ?? null,
      payload: candidate.payload ?? {},
      dedupe_key: candidate.dedupeKey,
      email_mode: mode,
      email_id: null,
      created_at: iso(now),
      read_at: null,
    }
    if (mode === 'immediate') {
      notification.email_id = queueEmail(db, {
        type: candidate.type,
        recipient_user_id: user.id,
        now,
      }).id
    }
    db.notifications.push(notification)
    created.push(notification)
  }
  return created
}

/** Puts an email in the outbox (`queued`); the pretend worker sends it shortly. */
export function queueEmail(
  db: MockDb,
  {
    type,
    recipient_user_id = null,
    to_address = null,
    requested_by_id = null,
    max_attempts = MAX_ATTEMPTS,
    now = Date.now(),
  }: {
    type: EmailType
    recipient_user_id?: string | null
    to_address?: string | null
    requested_by_id?: string | null
    max_attempts?: number
    now?: number
  },
): MockOutboxEmail {
  const row: MockOutboxEmail = {
    id: nextId(db, 'd'),
    type,
    status: 'queued',
    recipient_user_id,
    to_address,
    requested_by_id,
    attempts: 0,
    max_attempts,
    next_attempt_at: iso(now + WORKER_DELAY_MS),
    last_error: null,
    created_at: iso(now),
    updated_at: iso(now),
    sent_at: null,
  }
  db.outbox.push(row)
  return row
}

function watchersOf(db: MockDb, ideaId: string): string[] {
  const prefix = `${ideaId}:`
  return [...db.watchers]
    .filter((key) => key.startsWith(prefix))
    .map((key) => key.slice(prefix.length))
}

/** People mentioned in `body` who have a role in the idea's project (the picker's people). */
function mentionRecipients(db: MockDb, idea: MockIdea, body: string): string[] {
  return mentionedUserIds(body).filter(
    (userId) => effectiveRole(db, idea.project_id, userId) !== null,
  )
}

/** `mention` notifications for the people a comment newly mentions (§3.8). */
export function notifyMentions(
  db: MockDb,
  idea: MockIdea,
  comment: MockComment,
  actorId: string,
  previousBody = '',
): void {
  const before = new Set(mentionedUserIds(previousBody))
  notify(
    db,
    idea,
    actorId,
    mentionRecipients(db, idea, comment.body_md)
      .filter((userId) => !before.has(userId))
      .map((userId) => ({
        userId,
        type: 'mention' as const,
        commentId: comment.id,
        dedupeKey: `mention:${comment.id}`,
      })),
  )
}

function allEvaluationsIn(db: MockDb, idea: MockIdea): number | null {
  const assigned = rowsForIdea(db.assignments, idea.id)
  if (assigned.length === 0) return null
  const done = assigned.every((a) => evaluationOf(db, idea.id, a.user_id)?.status === 'submitted')
  return done ? assigned.length : null
}

/** The notifications one activity event causes (run after the request's last write). */
export function fanOut(db: MockDb, event: MockEvent): void {
  const idea = db.ideas.find((i) => i.id === event.idea_id)
  if (!idea) return
  const actor = event.actor_id
  const key = (type: NotificationType) => `${type}:${event.id}`
  const payload = event.payload
  switch (event.type) {
    case 'owner_changed': {
      const owner = typeof payload.to_owner_id === 'string' ? payload.to_owner_id : null
      if (!owner || payload.volunteered === true || idea.owner_id !== owner) return
      notify(db, idea, actor, [
        { userId: owner, type: 'owner_assigned', dedupeKey: key('owner_assigned') },
      ])
      return
    }
    case 'evaluator_added': {
      const evaluator = typeof payload.evaluator_id === 'string' ? payload.evaluator_id : null
      if (!evaluator || !mayEvaluate(db, idea, evaluator)) return
      notify(db, idea, actor, [
        {
          userId: evaluator,
          type: 'evaluator_invited',
          payload: { due_at: idea.evaluation_due_at },
          dedupeKey: key('evaluator_invited'),
        },
      ])
      return
    }
    case 'evaluation_submitted':
    case 'evaluator_removed': {
      const count = allEvaluationsIn(db, idea)
      if (count === null || !idea.owner_id) return
      notify(db, idea, actor, [
        {
          userId: idea.owner_id,
          type: 'evaluations_complete',
          payload: { evaluator_count: count },
          dedupeKey: key('evaluations_complete'),
        },
      ])
      return
    }
    case 'status_changed': {
      const people = [
        ...(idea.owner_id ? [idea.owner_id] : []),
        ...rowsForIdea(db.assignments, idea.id).map((a) => a.user_id),
        ...watchersOf(db, idea.id),
      ]
      notify(
        db,
        idea,
        actor,
        people.map((userId) => ({
          userId,
          type: 'status_changed' as const,
          payload: {
            from_status: payload.from_status,
            from_resolution: payload.from_resolution ?? null,
            to_status: payload.to_status,
            to_resolution: payload.to_resolution ?? null,
          },
          dedupeKey: key('status_changed'),
        })),
      )
      return
    }
    case 'comment': {
      const comment = db.comments.find((c) => c.id === event.comment_id)
      if (!comment || comment.deleted_at || !actor) return
      notifyMentions(db, idea, comment, actor)
      const mentioned = new Set(mentionRecipients(db, idea, comment.body_md))
      notify(
        db,
        idea,
        actor,
        watchersOf(db, idea.id)
          .filter((userId) => !mentioned.has(userId))
          .map((userId) => ({
            userId,
            type: 'comment' as const,
            commentId: comment.id,
            dedupeKey: key('comment'),
          })),
      )
      return
    }
    default:
      return
  }
}

/** Events emitted by the current request; fanned out once after its last write. */
export function flushFanOut(db: MockDb): void {
  const events = db.pendingEvents.splice(0)
  for (const event of events) fanOut(db, event)
}

/* ------------------------------------------------------------------ */
/* Mentions in comment bodies (§3.8)                                   */
/* ------------------------------------------------------------------ */

export type MentionRewrite =
  { ok: true; body: string } | { ok: false; code: 'too_many_mentions' | 'too_long' }

/**
 * What the API stores: more than 20 people → too_many_mentions; tokens naming
 * an active person get their current name, others become plain `@Label`; the
 * result must still fit 10,000 characters.
 */
export function rewriteMentions(db: MockDb, body: string, max = 10_000): MentionRewrite {
  if (mentionedUserIds(body).length > MAX_MENTIONS) return { ok: false, code: 'too_many_mentions' }
  const rewritten = body.replace(MENTION_PATTERN, (_token, label: string, id: string) => {
    const user = findUser(db, id.toLowerCase())
    if (!user?.is_active || user.is_service_account) return `@${label}`
    return `@[${mentionLabel(user.display_name)}](user:${user.id})`
  })
  if (rewritten.length > max) return { ok: false, code: 'too_long' }
  return { ok: true, body: rewritten }
}

/** Plain text of a comment for excerpts: Markdown removed, mentions as @Name, ≤ 200. */
export function commentExcerpt(body: string): string {
  const text = body
    .replace(MENTION_PATTERN, (_token, label: string) => `@${label}`)
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, '')
    .replace(/[*_~`]+/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return text.length > 200 ? `${text.slice(0, 199).trimEnd()}…` : text
}

/* ------------------------------------------------------------------ */
/* The inbox (§3.2)                                                    */
/* ------------------------------------------------------------------ */

/** One inbox entry for its owner, or null when its idea is gone or not viewable now. */
export function notificationItem(
  db: MockDb,
  n: MockNotification,
  viewer: MockUser,
): NotificationItem | null {
  const idea = db.ideas.find((i) => i.id === n.idea_id)
  if (!idea || !canViewIdea(db, idea, viewer)) return null
  const base = {
    id: n.id,
    created_at: n.created_at,
    read_at: n.read_at,
    idea: ideaRef(db, idea),
    actor: n.type === 'evaluation_reminder' ? null : userRefById(db, n.actor_id),
  }
  const p = n.payload
  switch (n.type) {
    case 'owner_assigned':
      return { ...base, type: 'owner_assigned' }
    case 'evaluator_invited':
      return {
        ...base,
        type: 'evaluator_invited',
        due_at: typeof p.due_at === 'string' ? p.due_at : null,
      }
    case 'evaluation_reminder':
      return {
        ...base,
        type: 'evaluation_reminder',
        due_at: String(p.due_at),
        days_before: Number(p.days_before ?? 0),
      }
    case 'evaluations_complete':
      return {
        ...base,
        type: 'evaluations_complete',
        evaluator_count: Number(p.evaluator_count ?? 1),
      }
    case 'status_changed': {
      const project = projectOf(db, idea)
      const from = {
        status: p.from_status as MockIdea['status'],
        resolution: (p.from_resolution ?? null) as MockIdea['resolution'],
      }
      const to = {
        status: p.to_status as MockIdea['status'],
        resolution: (p.to_resolution ?? null) as MockIdea['resolution'],
      }
      return {
        ...base,
        type: 'status_changed',
        from_status: from.status,
        from_resolution: from.resolution,
        from_label: statusLabel(project, from),
        to_status: to.status,
        to_resolution: to.resolution,
        to_label: statusLabel(project, to),
      }
    }
    case 'comment':
    case 'mention': {
      const comment = db.comments.find((c) => c.id === n.comment_id && c.deleted_at === null)
      return {
        ...base,
        type: n.type,
        comment: {
          id: n.comment_id ?? '',
          excerpt: comment ? commentExcerpt(comment.body_md) : '',
          deleted: !comment,
        },
      }
    }
  }
}

/** The viewer's notifications they can view now, newest first. */
export function inbox(db: MockDb, viewer: MockUser, unreadOnly = false): MockNotification[] {
  return db.notifications
    .filter((n) => n.user_id === viewer.id && (!unreadOnly || n.read_at === null))
    .filter((n) => {
      const idea = db.ideas.find((i) => i.id === n.idea_id)
      return Boolean(idea && canViewIdea(db, idea, viewer))
    })
    .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id))
}

/** For platform admins while email is on: a failure in the last 24 h or mail queued > 15 min. */
export function emailTrouble(db: MockDb, now = Date.now()): boolean {
  if (!db.email.configured) return false
  return db.outbox.some(
    (row) =>
      (row.status === 'failed' && Date.parse(row.updated_at) > now - DAY) ||
      (row.status === 'queued' && Date.parse(row.created_at) < now - 15 * MINUTE),
  )
}

export function notificationSummary(db: MockDb, viewer: MockUser): NotificationSummary {
  return {
    unread_count: Math.min(inbox(db, viewer, true).length, UNREAD_CAP),
    email_available: db.email.configured,
    email_trouble: viewer.is_platform_admin && emailTrouble(db),
  }
}

/* ------------------------------------------------------------------ */
/* The outbox and the pretend worker (§3.9, §3.10)                     */
/* ------------------------------------------------------------------ */

/** `min(30 s × 2^(a−1), 1 h)` (no jitter in the mock). */
export function backoffMs(attempts: number): number {
  return Math.min(30_000 * 2 ** Math.max(0, attempts - 1), HOUR)
}

/** Sends (or, with `failing`, fails) every queued email that is due. */
export function runMockWorker(db: MockDb, now = Date.now()): void {
  if (!db.email.configured) return
  for (const row of db.outbox) {
    if (row.status !== 'queued' || !row.next_attempt_at) continue
    if (Date.parse(row.next_attempt_at) > now) continue
    row.attempts += 1
    row.updated_at = iso(now)
    if (db.email.failing) {
      row.last_error = 'connection refused'
      if (row.attempts >= row.max_attempts) {
        row.status = 'failed'
        row.next_attempt_at = null
      } else {
        row.next_attempt_at = iso(now + backoffMs(row.attempts))
      }
    } else {
      row.status = 'sent'
      row.sent_at = iso(now)
      row.last_error = null
      row.next_attempt_at = null
    }
  }
}

const MAX_AGE_MS = 3 * DAY
const DIGEST_MAX_AGE_MS = 2 * DAY

export function isRetryable(row: MockOutboxEmail, now = Date.now()): boolean {
  const maxAge = row.type === 'digest' ? DIGEST_MAX_AGE_MS : MAX_AGE_MS
  return row.status === 'failed' && Date.parse(row.created_at) > now - maxAge
}

/** "a•••@example.com" (first character, dots, the domain). */
export function maskEmail(address: string): string {
  const [local = '', domain = ''] = address.split('@')
  return `${local.slice(0, 1)}•••@${domain}`
}

export function outboxEmail(db: MockDb, row: MockOutboxEmail, now = Date.now()): OutboxEmail {
  const recipient = findUser(db, row.recipient_user_id)
  const notification = db.notifications.find((n) => n.email_id === row.id)
  const idea =
    row.type !== 'digest' && notification
      ? db.ideas.find((i) => i.id === notification.idea_id)
      : undefined
  return {
    id: row.id,
    type: row.type,
    status: row.status,
    recipient: recipient ? userRef(recipient) : null,
    address_hint: row.to_address ? maskEmail(row.to_address) : null,
    idea: idea ? ideaRef(db, idea) : null,
    requested_by: userRefById(db, row.requested_by_id),
    attempts: row.attempts,
    max_attempts: row.max_attempts,
    next_attempt_at: row.next_attempt_at,
    last_error: row.last_error,
    created_at: row.created_at,
    sent_at: row.sent_at,
    retryable: isRetryable(row, now),
  }
}

export function outboxStats(db: MockDb, now = Date.now()): OutboxStats {
  const queued = db.outbox.filter((row) => row.status === 'queued')
  const sent = db.outbox.filter((row) => row.status === 'sent' && row.sent_at)
  const oldest = queued.map((row) => row.created_at).sort()[0] ?? null
  const last =
    sent
      .map((row) => row.sent_at ?? '')
      .sort()
      .at(-1) ?? null
  return {
    queued: queued.length,
    sending: db.outbox.filter((row) => row.status === 'sending').length,
    failed: db.outbox.filter((row) => row.status === 'failed').length,
    sent_last_24h: sent.filter((row) => Date.parse(row.sent_at ?? '') > now - DAY).length,
    oldest_queued_at: oldest,
    last_sent_at: last,
  }
}

export function emailConfig(db: MockDb): EmailConfig {
  const on = db.email.configured
  return {
    configured: on,
    host: on ? 'smtp.example.com' : null,
    port: 587,
    security: 'starttls',
    username_set: on,
    password_set: on,
    from_address: on ? 'ideas@example.com' : null,
    from_name: 'Soundings',
    reply_to: on ? 'innovation@example.com' : null,
    ca_bundle: on ? '/etc/soundings/smtp-ca/ca.crt' : null,
    timeout_seconds: 10,
    links_base_url: typeof window === 'undefined' ? 'http://localhost' : window.location.origin,
    timezone: MOCK_SCHEDULE.timezone,
    digest_hour: MOCK_SCHEDULE.digestHour,
    reminder_days: [...MOCK_SCHEDULE.reminderDays],
    outbox: outboxStats(db),
  }
}

/* ------------------------------------------------------------------ */
/* Unsubscribe tokens (§3.5)                                           */
/* ------------------------------------------------------------------ */

const SCOPES: UnsubscribeScope[] = [...NOTIFICATION_TYPES, 'digest', 'all']

function base64url(text: string): string {
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fromBase64url(text: string): string {
  const padded = text.replace(/-/g, '+').replace(/_/g, '/')
  return atob(padded + '='.repeat((4 - (padded.length % 4)) % 4))
}

/** Not a real signature: a stable checksum so edited tokens fail like forged ones. */
function mockSignature(payload: string): string {
  let hash = 0x811c9dc5
  for (const char of `soundings/unsubscribe/v1:${payload}`) {
    hash ^= char.charCodeAt(0)
    hash = Math.imul(hash, 0x01000193) >>> 0
  }
  return base64url(`mock-${hash.toString(16)}`)
}

/** `base64url(payload).base64url(signature)`, payload `{"v":1,"u":<user>,"s":<scope>}`. */
export function unsubscribeToken(userId: string, scope: UnsubscribeScope): string {
  const payload = base64url(JSON.stringify({ v: 1, u: userId, s: scope }))
  return `${payload}.${mockSignature(payload)}`
}

/** The token's active user and scope, or null (forged, truncated, unknown or inactive user). */
export function readUnsubscribeToken(
  db: MockDb,
  token: string,
): { user: MockUser; scope: UnsubscribeScope } | null {
  const [payload, signature, extra] = token.split('.')
  if (!payload || !signature || extra !== undefined) return null
  if (signature !== mockSignature(payload)) return null
  try {
    const value = JSON.parse(fromBase64url(payload)) as { v?: unknown; u?: unknown; s?: unknown }
    if (
      value.v !== 1 ||
      typeof value.u !== 'string' ||
      !SCOPES.includes(value.s as UnsubscribeScope)
    ) {
      return null
    }
    const user = findUser(db, value.u)
    if (!user?.is_active) return null
    return { user, scope: value.s as UnsubscribeScope }
  } catch {
    return null
  }
}

/** The types a scope turns off now (digest: the types currently in digest mode). */
export function scopeTypes(
  db: MockDb,
  user: MockUser,
  scope: UnsubscribeScope,
): NotificationType[] {
  if (scope === 'all') return [...NOTIFICATION_TYPES]
  if (scope === 'digest') {
    return NOTIFICATION_TYPES.filter((type) => preferenceMode(db, user.id, type) === 'digest')
  }
  return [scope]
}

export function unsubscribeInfo(
  db: MockDb,
  user: MockUser,
  scope: UnsubscribeScope,
  types: NotificationType[],
): UnsubscribeInfo {
  return {
    scope,
    types,
    unsubscribed: types.every((type) => preferenceMode(db, user.id, type) === 'off'),
    email_hint: maskEmail(user.email),
  }
}
