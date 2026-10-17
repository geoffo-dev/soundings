/**
 * Phase 11 in the mock API (contract-phase11): one conversation per public
 * submission between the team and the person who sent the idea, the rule
 * `public.message_submitter`, the limits, the tracking page's reply, "Remove my
 * email address", the tracking-link email and "The submitter replied". Records
 * mirror `submission_messages`; close enough to build and test the screens (the
 * backend and its tests are the authority).
 *
 * Nothing here reaches the feed, search, My work, exports or `last_activity_at`:
 * a hidden conversation must not move the idea or reveal itself to members.
 */
import type {
  EmailType,
  MessageDelivery,
  ReplyBlocked,
  SendBlocked,
  SubmissionMessage,
  SubmissionMessagesSummary,
  TrackedMessage,
} from '@/api/types'

import type { MockDb, MockIdea, MockUser } from './db'
import { effectiveRole, findUser, isProjectAdmin, projectOf, userRefById } from './domain'
import { failValidation } from './http'
import type { MockPublicSubmission } from './public'

const HOUR = 3_600_000
const DAY = 24 * HOUR

/** `app/schemas/public.py` (constants, not settings: contract-phase11 §5). */
export const MESSAGE_MAX_LENGTH = 4_000
export const CONVERSATION_MAX_MESSAGES = 100
export const TEAM_MESSAGES_PER_SUBMISSION_PER_DAY = 20
export const TEAM_MESSAGES_PER_PERSON_PER_HOUR = 30
export const SUBMITTER_MESSAGES_PER_DAY = 10
export const SUBMITTER_MESSAGES_SINCE_TEAM_MESSAGE = 10
export const PUBLIC_REPLIES_PER_IP_PER_HOUR = 30
export const SUBMITTER_REPLIED_EMAIL_INTERVAL_MS = HOUR

/** The one list of submitter email types (`SUBMITTER_EMAIL_TYPES`). */
export const SUBMITTER_EMAIL_TYPES: readonly EmailType[] = [
  'submission_received',
  'submission_status_changed',
  'submission_link',
  'submission_message',
]

export interface MockSubmissionMessage {
  id: string
  submission_id: string
  direction: 'team' | 'submitter'
  /** Team messages only (null for replies, or once the user is gone). */
  author_id: string | null
  body: string
  /** Team messages: an email to their confirmed address was queued. */
  emailed: boolean
  created_at: string
}

/* ------------------------------------------------------------------ */
/* The rule (role matrix table G, c31)                                 */
/* ------------------------------------------------------------------ */

/**
 * `public.message_submitter` (session only; the mock has no API keys): the idea's
 * owner while member or admin, project and platform admins; c31: never a service
 * account or the break-glass account.
 */
export function canMessageSubmitter(db: MockDb, idea: MockIdea, user: MockUser): boolean {
  if (!user.is_active || user.is_service_account || user.is_break_glass) return false
  const project = projectOf(db, idea)
  if (isProjectAdmin(db, project, user)) return true
  const role = effectiveRole(db, project.id, user.id)
  return idea.owner_id === user.id && (role === 'member' || role === 'admin')
}

/* ------------------------------------------------------------------ */
/* Reads                                                               */
/* ------------------------------------------------------------------ */

/** Oldest first. */
export function conversationOf(db: MockDb, submission: MockPublicSubmission) {
  return db.submissionMessages
    .filter((m) => m.submission_id === submission.id)
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))
}

function since(messages: MockSubmissionMessage[], ms: number, now = Date.now()) {
  return messages.filter((m) => Date.parse(m.created_at) > now - ms)
}

/** The address is confirmed and email is set up: team messages are also emailed. */
export function messageDelivery(db: MockDb, submission: MockPublicSubmission): MessageDelivery {
  return db.email.configured && submission.email && submission.email_verified_at
    ? 'email'
    : 'tracking_page'
}

/** Why the team can't send now, in the order checked (contract-phase11 §2.1, C6). */
export function sendBlocked(
  db: MockDb,
  idea: MockIdea,
  submission: MockPublicSubmission,
  now = Date.now(),
): SendBlocked | null {
  if (projectOf(db, idea).archived_at !== null) return 'project_archived'
  if (submission.erased_at !== null) return 'submitter_erased'
  if (!db.publicSubmissionEnabled) return 'public_submission_off'
  const messages = conversationOf(db, submission)
  if (messages.length >= CONVERSATION_MAX_MESSAGES) return 'conversation_full'
  const team = messages.filter((m) => m.direction === 'team')
  if (since(team, DAY, now).length >= TEAM_MESSAGES_PER_SUBMISSION_PER_DAY) return 'daily_limit'
  return null
}

/** Why the submitter can't reply now, in the order checked (§2.1, S6). */
export function replyBlocked(
  db: MockDb,
  idea: MockIdea,
  submission: MockPublicSubmission,
  now = Date.now(),
): ReplyBlocked | null {
  if (projectOf(db, idea).archived_at !== null) return 'project_archived'
  const messages = conversationOf(db, submission)
  const lastTeam = messages.findLastIndex((m) => m.direction === 'team')
  if (lastTeam === -1) return 'awaiting_team'
  if (messages.length - lastTeam - 1 >= SUBMITTER_MESSAGES_SINCE_TEAM_MESSAGE) {
    return 'awaiting_team'
  }
  if (messages.length >= CONVERSATION_MAX_MESSAGES) return 'conversation_full'
  const replies = messages.filter((m) => m.direction === 'submitter')
  if (since(replies, DAY, now).length >= SUBMITTER_MESSAGES_PER_DAY) return 'daily_limit'
  return null
}

/** `IdeaSubmission.messages` for a holder of the rule (null for everyone else). */
export function messagesSummary(
  db: MockDb,
  idea: MockIdea,
  submission: MockPublicSubmission,
  user: MockUser,
): SubmissionMessagesSummary | null {
  if (!canMessageSubmitter(db, idea, user)) return null
  const messages = conversationOf(db, submission)
  const last = messages.at(-1)
  return {
    count: messages.length,
    last_message_at: last?.created_at ?? null,
    last_direction: last?.direction ?? null,
    delivery: messageDelivery(db, submission),
    blocked: sendBlocked(db, idea, submission),
  }
}

/** The team's view of a message (with its author). */
export function teamMessage(db: MockDb, message: MockSubmissionMessage): SubmissionMessage {
  return {
    id: message.id,
    direction: message.direction,
    body: message.body,
    created_at: message.created_at,
    author: message.direction === 'team' ? userRefById(db, message.author_id) : null,
    emailed: message.direction === 'team' && message.emailed,
  }
}

/** The tracking page's view: no author, ever (public pages show no people). */
export function trackedMessage(message: MockSubmissionMessage): TrackedMessage {
  return {
    id: message.id,
    direction: message.direction,
    body: message.body,
    created_at: message.created_at,
  }
}

/* ------------------------------------------------------------------ */
/* Text rules (`MessageBody`)                                          */
/* ------------------------------------------------------------------ */

/** Invisible characters removed (as `VisibleText`); ZWJ and ZWNJ stay. */
const INVISIBLE =
  /[\u00ad\u061c\u180e\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb]/g
// eslint-disable-next-line no-control-regex -- NUL is exactly what is refused
const REFUSED = /[\u0000]|[\u{E0000}-\u{E007F}]/u

/**
 * 1-4,000 characters with a visible one; NUL and Unicode tag characters are a 422;
 * line breaks (CRLF, CR, U+2028, U+2029) become `\n`; the ends are trimmed.
 */
export function messageBody(body: Record<string, unknown>): string {
  const value = body.body
  if (typeof value !== 'string') {
    failValidation([
      {
        loc: ['body', 'body'],
        msg: value === undefined ? 'Field required' : 'Input should be a valid string',
        type: value === undefined ? 'missing' : 'string_type',
      },
    ])
  }
  if (value.length > MESSAGE_MAX_LENGTH) {
    failValidation([
      {
        loc: ['body', 'body'],
        msg: `String should have at most ${MESSAGE_MAX_LENGTH} characters`,
        type: 'string_too_long',
      },
    ])
  }
  if (REFUSED.test(value)) {
    failValidation([
      {
        loc: ['body', 'body'],
        msg: 'Contains characters that aren’t allowed',
        type: 'value_error',
      },
    ])
  }
  const text = value
    .replace(/\r\n?|[\u2028\u2029]/g, '\n')
    .replace(INVISIBLE, '')
    .trim()
  if (!text) {
    failValidation([
      { loc: ['body', 'body'], msg: 'Write something to send', type: 'string_too_short' },
    ])
  }
  return text
}

/* ------------------------------------------------------------------ */
/* Limits                                                              */
/* ------------------------------------------------------------------ */

/** Seconds until the oldest counted message leaves its window (at least 1). */
export function retryAfter(messages: MockSubmissionMessage[], windowMs: number, now = Date.now()) {
  const oldest = Math.min(...messages.map((m) => Date.parse(m.created_at)))
  return Math.max(1, Math.ceil((oldest + windowMs - now) / 1000))
}

/** A person's team messages to every submitter in the last hour. */
export function sentByLastHour(db: MockDb, userId: string, now = Date.now()) {
  return since(
    db.submissionMessages.filter((m) => m.direction === 'team' && m.author_id === userId),
    HOUR,
    now,
  )
}

export function teamMessagesToday(db: MockDb, submission: MockPublicSubmission, now = Date.now()) {
  return since(
    conversationOf(db, submission).filter((m) => m.direction === 'team'),
    DAY,
    now,
  )
}

export function repliesToday(db: MockDb, submission: MockPublicSubmission, now = Date.now()) {
  return since(
    conversationOf(db, submission).filter((m) => m.direction === 'submitter'),
    DAY,
    now,
  )
}

/* ------------------------------------------------------------------ */
/* "The submitter replied" recipients (§6)                             */
/* ------------------------------------------------------------------ */

/**
 * The idea's owner and everyone who has written to the submitter, each still
 * holding the rule (re-checked when shown); nobody while the idea is held.
 */
export function replyRecipients(
  db: MockDb,
  idea: MockIdea,
  submission: MockPublicSubmission,
): MockUser[] {
  if (idea.held_for) return []
  const ids = new Set<string>()
  if (idea.owner_id) ids.add(idea.owner_id)
  for (const message of conversationOf(db, submission)) {
    if (message.direction === 'team' && message.author_id) ids.add(message.author_id)
  }
  return [...ids]
    .map((id) => findUser(db, id))
    .filter((user): user is MockUser => Boolean(user && canMessageSubmitter(db, idea, user)))
}

/** At most one immediate "The submitter replied" email per recipient and idea an hour. */
export function repliedEmailedRecently(
  db: MockDb,
  userId: string,
  ideaId: string,
  now = Date.now(),
): boolean {
  return db.notifications.some(
    (n) =>
      n.type === 'submitter_replied' &&
      n.user_id === userId &&
      n.idea_id === ideaId &&
      n.email_mode === 'immediate' &&
      Date.parse(n.created_at) > now - SUBMITTER_REPLIED_EMAIL_INTERVAL_MS,
  )
}

/** Shown in the inbox only while the viewer still holds the rule and the idea isn't held. */
export function submitterRepliedVisible(db: MockDb, idea: MockIdea, viewer: MockUser): boolean {
  return !idea.held_for && canMessageSubmitter(db, idea, viewer)
}
