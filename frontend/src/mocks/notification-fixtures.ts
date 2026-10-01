/**
 * Phase 3 fixtures (contract-phase3): inboxes for Alice (every type, five
 * unread), Priya, Bob, Emma and Hannah; a few email preferences that differ
 * from the defaults; and an outbox with sent mail, digests, a test email, a
 * retrying email, failures (recent and too old to retry) and cancellations.
 * Deterministic, relative to `db.now`. Nothing here carries a score.
 *
 * Knob `soundings-mock-email`: `off` (SMTP not configured: `email_available`
 * false, the admin banner) or `failing` (SMTP down: a recent failure and mail
 * stuck in the queue, so admins see "Some emails aren't going out").
 */
import type { EmailStatus, EmailType, NotificationMode, NotificationType } from '@/api/types'

import type { MockDb, MockIdea, MockNotification, MockOutboxEmail, USERS as UsersMap } from './db'

type Users = typeof UsersMap
type UserKey = keyof Users

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

const DEFAULTS: Record<NotificationType, NotificationMode> = {
  owner_assigned: 'immediate',
  evaluator_invited: 'immediate',
  evaluation_reminder: 'immediate',
  evaluations_complete: 'immediate',
  status_changed: 'digest',
  comment: 'digest',
  mention: 'immediate',
}

interface NotificationSpec {
  to: UserKey
  type: NotificationType
  idea: string
  actor?: UserKey
  /** Minutes ago. */
  ago: number
  read?: boolean
  payload?: Record<string, unknown>
  /** For comment/mention: the start of an existing comment's text… */
  comment?: string
  /** …or a new comment by `actor`, posted `ago` minutes ago (mentions use `{alice}` etc.). */
  newComment?: string
  /** The email: by default sent when immediate; or this outcome. */
  email?: { status: EmailStatus; attempts?: number; error?: string; failedAgo?: number }
}

const NOTIFICATIONS: NotificationSpec[] = [
  // Alice Anders: one of every type, five unread.
  {
    to: 'alice',
    type: 'mention',
    idea: 'Self-serve returns portal',
    actor: 'carol',
    ago: 12,
    newComment:
      '{alice} could you check whether the carrier API copes with **peak season** volumes before you score this?',
  },
  {
    to: 'alice',
    type: 'comment',
    idea: 'Self-serve returns portal',
    actor: 'bob',
    ago: 20,
    comment: 'Good point',
  },
  {
    to: 'alice',
    type: 'comment',
    idea: 'Print-free returns with a QR code',
    actor: 'dave',
    ago: 26,
    comment: 'I can take a look',
  },
  {
    to: 'alice',
    type: 'evaluations_complete',
    idea: 'Flaky test dashboard',
    actor: 'farid',
    ago: 20 * 60,
    payload: { evaluator_count: 3 },
  },
  {
    to: 'alice',
    type: 'evaluation_reminder',
    idea: 'Self-serve returns portal',
    ago: 26 * 60,
    payload: { days_before: 2 },
  },
  {
    to: 'alice',
    type: 'evaluator_invited',
    idea: 'Shared test data service',
    actor: 'dave',
    ago: 2 * 24 * 60,
    read: true,
  },
  {
    to: 'alice',
    type: 'status_changed',
    idea: 'Delivery time slots at checkout',
    actor: 'dave',
    ago: 3 * 24 * 60 + 90,
    read: true,
    payload: { from_status: 'evaluating', to_status: 'shortlisted' },
  },
  {
    to: 'alice',
    type: 'owner_assigned',
    idea: 'Release notes generator',
    actor: 'bob',
    ago: 4 * 24 * 60,
    read: true,
  },
  {
    to: 'alice',
    type: 'status_changed',
    idea: 'Solar panels on the warehouse roof',
    actor: 'carol',
    ago: 5 * 24 * 60 + 200,
    read: true,
    payload: { from_status: 'evaluating', to_status: 'shortlisted' },
  },
  {
    to: 'alice',
    type: 'evaluator_invited',
    idea: 'Gift cards with personal video messages',
    actor: 'carol',
    ago: 6 * 24 * 60,
    read: true,
  },
  {
    to: 'alice',
    type: 'mention',
    idea: 'Green supplier scorecard',
    actor: 'emma',
    ago: 8 * 24 * 60,
    read: true,
    newComment: 'Thanks {alice}, your notes on supplier audits helped a lot.',
  },
  {
    to: 'alice',
    type: 'status_changed',
    idea: 'Carbon-neutral shipping option',
    actor: 'priya',
    ago: 9 * 24 * 60,
    read: true,
    payload: { from_status: 'shortlisted', to_status: 'closed', to_resolution: 'accepted' },
  },
  // Priya Natarajan (platform admin).
  {
    to: 'priya',
    type: 'mention',
    idea: 'Self-serve returns portal',
    actor: 'alice',
    ago: 16,
    newComment: '{priya} can legal look at the carrier terms before we decide?',
  },
  {
    to: 'priya',
    type: 'status_changed',
    idea: 'Subscription boxes for repeat buyers',
    actor: 'alice',
    ago: 2 * 24 * 60,
    read: true,
    payload: { from_status: 'shortlisted', to_status: 'proposal' },
  },
  // Bob Chen.
  {
    to: 'bob',
    type: 'comment',
    idea: 'Self-serve returns portal',
    actor: 'carol',
    ago: 30,
    comment: 'Have we checked',
  },
  {
    to: 'bob',
    type: 'evaluations_complete',
    idea: 'One-click reorder from order history',
    actor: 'farid',
    ago: 26 * 60,
    read: true,
    payload: { evaluator_count: 3 },
  },
  {
    to: 'bob',
    type: 'evaluation_reminder',
    idea: 'Proactive delay notifications by SMS',
    ago: 50 * 60,
    read: true,
    payload: { days_before: 2 },
    email: { status: 'cancelled', error: 'Not sent: no longer applies' },
  },
  // Emma Lindqvist: the Internal Tools one is hidden (private project, no role).
  {
    to: 'emma',
    type: 'status_changed',
    idea: 'Flaky test dashboard',
    actor: 'alice',
    ago: 3 * 60,
    payload: { from_status: 'new', to_status: 'evaluating' },
  },
  {
    to: 'emma',
    type: 'evaluations_complete',
    idea: 'Paperless invoicing',
    actor: 'carol',
    ago: 5 * 60,
    payload: { evaluator_count: 2 },
  },
  // Mail that didn't go out (Admin → Email).
  {
    to: 'hannah',
    type: 'evaluator_invited',
    idea: 'Price-drop alerts on wishlists',
    actor: 'farid',
    ago: 30 * 60,
    email: {
      status: 'failed',
      attempts: 12,
      error: 'SMTP 535: authentication failed',
      failedAgo: 25 * 60,
    },
  },
  {
    to: 'carol',
    type: 'evaluations_complete',
    idea: 'Solar panels on the warehouse roof',
    actor: 'grace',
    ago: 28 * 60,
    read: true,
    payload: { evaluator_count: 3 },
    email: {
      status: 'failed',
      attempts: 1,
      error: 'SMTP 550: recipient refused',
      failedAgo: 28 * 60,
    },
  },
  {
    to: 'farid',
    type: 'mention',
    idea: 'Self-serve returns portal',
    actor: 'hannah',
    ago: 10,
    newComment: '{farid} do the carrier slots include Saturdays?',
    email: { status: 'queued', attempts: 2, error: 'connection timed out' },
  },
  {
    to: 'grace',
    type: 'owner_assigned',
    idea: 'Bike-to-work scheme',
    actor: 'carol',
    ago: 3 * 24 * 60 + 600,
    read: true,
    email: { status: 'cancelled', error: 'Not sent: turned off by the recipient' },
  },
]

/** Sent mail that has no inbox row of its own here: [type, to, hours ago]. */
const SENT: [EmailType, UserKey, number][] = [
  ['digest', 'alice', 24 + 15],
  ['digest', 'bob', 24 + 15],
  ['digest', 'carol', 24 + 15],
  ['digest', 'alice', 48 + 15],
  ['digest', 'dave', 48 + 15],
  ['evaluator_invited', 'dave', 7],
  ['evaluator_invited', 'farid', 9],
  ['owner_assigned', 'hannah', 11],
  ['mention', 'bob', 13],
  ['evaluations_complete', 'dave', 30],
  ['evaluation_reminder', 'farid', 32],
  ['evaluation_reminder', 'dave', 56],
  ['comment', 'carol', 60],
  ['status_changed', 'grace', 70],
]

const PREFERENCES: [UserKey, NotificationType, NotificationMode][] = [
  ['alice', 'comment', 'immediate'],
  ['grace', 'owner_assigned', 'off'],
  ['bob', 'status_changed', 'off'],
]

export function seedNotifications(
  db: MockDb,
  { users, nextId }: { users: Users; nextId: (kind: number | string) => string },
): void {
  const now = db.now
  const iso = (ms: number) => new Date(ms).toISOString()
  const findIdea = (title: string): MockIdea => {
    const idea = db.ideas.find((i) => i.title === title)
    if (!idea) throw new Error(`notification fixture: no idea "${title}"`)
    return idea
  }
  const name = (key: UserKey) => db.users.find((u) => u.id === users[key])?.display_name ?? key
  const token = (key: UserKey) => `@[${name(key)}](user:${users[key]})`

  const outboxRow = (
    row: Partial<MockOutboxEmail> & { type: EmailType; created: number },
  ): MockOutboxEmail => {
    const { created, ...rest } = row
    const email: MockOutboxEmail = {
      id: nextId('d'),
      status: 'sent',
      recipient_user_id: null,
      to_address: null,
      requested_by_id: null,
      attempts: 1,
      max_attempts: 12,
      next_attempt_at: null,
      last_error: null,
      created_at: iso(created),
      updated_at: iso(created + 20_000),
      sent_at: iso(created + 20_000),
      ...rest,
    }
    db.outbox.push(email)
    return email
  }

  for (const [user, type, mode] of PREFERENCES) {
    ;(db.notificationPrefs[users[user]] ??= {})[type] = mode
  }

  for (const spec of NOTIFICATIONS) {
    const idea = findIdea(spec.idea)
    const at = now - spec.ago * MINUTE
    const actorId = spec.actor ? users[spec.actor] : null
    let commentId: string | null = null
    if (spec.newComment && actorId) {
      commentId = nextId(6)
      const body = spec.newComment.replace(/\{(\w+)\}/g, (_m, key: string) => token(key as UserKey))
      db.comments.push({
        id: commentId,
        idea_id: idea.id,
        author_id: actorId,
        body_md: body,
        created_at: iso(at),
        edited_at: null,
        deleted_at: null,
      })
      db.events.push({
        id: nextId(7),
        idea_id: idea.id,
        actor_id: actorId,
        type: 'comment',
        payload: {},
        comment_id: commentId,
        created_at: iso(at),
      })
      db.watchers.add(`${idea.id}:${actorId}`)
      if (Date.parse(idea.last_activity_at) < at) idea.last_activity_at = iso(at)
    } else if (spec.comment) {
      const prefix = spec.comment
      commentId =
        db.comments.find((c) => c.idea_id === idea.id && c.body_md.startsWith(prefix))?.id ?? null
    }

    const payload: Record<string, unknown> = { ...spec.payload }
    if (spec.type === 'evaluator_invited') payload.due_at = idea.evaluation_due_at
    if (spec.type === 'evaluation_reminder')
      payload.due_at = idea.evaluation_due_at ?? iso(now + DAY)
    if (spec.type === 'status_changed') {
      payload.from_resolution ??= null
      payload.to_resolution ??= null
    }

    const mode = db.notificationPrefs[users[spec.to]]?.[spec.type] ?? DEFAULTS[spec.type]
    const emailMode: NotificationMode = db.email.configured ? mode : 'off'
    const notification: MockNotification = {
      id: nextId('c'),
      user_id: users[spec.to],
      type: spec.type,
      idea_id: idea.id,
      actor_id: actorId,
      comment_id: commentId,
      payload,
      dedupe_key: `${spec.type}:fixture-${db.notifications.length + 1}`,
      email_mode: emailMode,
      email_id: null,
      created_at: iso(at),
      read_at: spec.read ? iso(Math.min(now, at + 2 * HOUR)) : null,
    }
    if (spec.email || emailMode === 'immediate') {
      const outcome = spec.email ?? { status: 'sent' as const }
      const failedAt = now - (outcome.failedAgo ?? spec.ago) * MINUTE
      notification.email_id = outboxRow({
        type: spec.type,
        recipient_user_id: users[spec.to],
        created: at,
        status: outcome.status,
        attempts: outcome.attempts ?? (outcome.status === 'cancelled' ? 0 : 1),
        last_error: outcome.error ?? null,
        sent_at: outcome.status === 'sent' ? iso(at + 20_000) : null,
        updated_at: iso(outcome.status === 'failed' ? failedAt : at + 20_000),
        // A retry waiting for its turn: still queued when the page is looked at.
        next_attempt_at: outcome.status === 'queued' ? iso(now + 2 * MINUTE) : null,
      }).id
    }
    db.notifications.push(notification)
  }

  for (const [type, to, hoursAgo] of SENT) {
    outboxRow({ type, recipient_user_id: users[to], created: now - hoursAgo * HOUR })
  }
  // A test email from Priya, and a digest that kept failing four days ago (too old to retry).
  outboxRow({
    type: 'test',
    to_address: 'ops@example.com',
    requested_by_id: users.priya,
    max_attempts: 1,
    created: now - 3 * DAY,
  })
  outboxRow({
    type: 'digest',
    recipient_user_id: users.dave,
    created: now - 4 * DAY,
    status: 'failed',
    attempts: 12,
    sent_at: null,
    last_error: 'connection refused',
    updated_at: iso(now - 4 * DAY + 5 * HOUR),
  })

  if (db.email.failing) {
    // SMTP has been down for a while: a failure today and mail waiting for 40 minutes.
    outboxRow({
      type: 'evaluator_invited',
      recipient_user_id: users.bob,
      created: now - 6 * HOUR,
      status: 'failed',
      attempts: 12,
      sent_at: null,
      last_error: 'connection refused',
      updated_at: iso(now - HOUR),
    })
    outboxRow({
      type: 'mention',
      recipient_user_id: users.carol,
      created: now - 40 * MINUTE,
      status: 'queued',
      attempts: 5,
      sent_at: null,
      last_error: 'connection refused',
      updated_at: iso(now - 4 * MINUTE),
      next_attempt_at: iso(now + 4 * MINUTE),
    })
  }

  db.outbox.sort((a, b) => a.created_at.localeCompare(b.created_at))
  db.events.sort((a, b) => a.created_at.localeCompare(b.created_at))
}
